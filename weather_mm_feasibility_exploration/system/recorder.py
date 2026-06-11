"""
recorder.py — Phase 0: continuous READ-ONLY book + trade tape for Kalshi weather ladders.

Builds the microstructure substrate the historical study lacked (live book over time +
full deduped trade stream), so the Phase-1 simulator can model fills/queue and measure
the CAPTURED edge `s`. Zero capital, zero auth. Config-driven; runs anywhere.

Output (append-only JSONL, rotated by UTC day, under OUT_DIR):
  books_YYYYMMDD.jsonl  : {"ty":"book","t":..,"tk":..,"yb":..,"ya":..,"yes":[[px,sz]],"no":[...]}
  trades_YYYYMMDD.jsonl : {"ty":"trade","t":..,"tk":..,"p":..,"c":..,"taker_yes":0/1,"id":..}
  meta.jsonl            : {"ty":"meta","t":..,"tk":..,"floor":..,"cap":..,"close":..,"result":..}

Design:
  - records only markets within ACTIVE_WINDOW_H of close (the tradeable window; the
    >24h-from-close period is the documented loss zone and is skipped to save space).
  - book snapshot every BOOK_CADENCE_S; trades polled every TRADE_CADENCE_S, deduped by
    trade_id (seen-set rebuilt from today's file on restart for crash safety).
  - never crashes on a single market/network error; clean Ctrl-C shutdown.
"""
import json, os, sys, time, signal, datetime as DT, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_client as kc

# ── config ────────────────────────────────────────────────────────────────────
SERIES = {"NYC": "KXHIGHNY", "CHI": "KXHIGHCHI", "MIA": "KXHIGHMIA",
          "LAX": "KXHIGHLAX", "AUS": "KXHIGHAUS"}
OUT_DIR = os.environ.get("TAPE_DIR", os.path.join(HERE, "tape"))
BOOK_CADENCE_S = int(os.environ.get("BOOK_CADENCE_S", "20"))    # full-book snapshot interval
TRADE_CADENCE_S = int(os.environ.get("TRADE_CADENCE_S", "10"))  # trade poll interval
MARKET_REFRESH_S = 600        # re-discover open markets every 10 min
ACTIVE_WINDOW_H = 30          # only record markets within this many hours of close
BOOK_DEPTH = 20               # levels per side to store

os.makedirs(OUT_DIR, exist_ok=True)
_RUN = True


def _stop(*_):
    global _RUN
    _RUN = False
    print("\n[recorder] shutdown requested, finishing cycle…")


signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)


def utc_day():
    return DT.datetime.now(DT.timezone.utc).strftime("%Y%m%d")


def fpath(kind):
    if kind == "meta":
        return os.path.join(OUT_DIR, "meta.jsonl")
    return os.path.join(OUT_DIR, f"{kind}_{utc_day()}.jsonl")


def append(kind, obj):
    with open(fpath(kind), "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def load_seen_today():
    """Rebuild per-ticker seen trade_id sets from today's trades file (crash recovery)."""
    seen = {}
    p = fpath("trades")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                    seen.setdefault(o["tk"], set()).add(o["id"])
                except Exception:
                    pass
    return seen


def hours_to_close(close_iso):
    try:
        ct = DT.datetime.fromisoformat(close_iso.replace("Z", "+00:00")).timestamp()
        return (ct - time.time()) / 3600.0
    except Exception:
        return None


def discover():
    """Open target markets within the active window. Returns {ticker: market_dict}."""
    out = {}
    for city, ser in SERIES.items():
        try:
            for m in kc.open_markets(ser):
                h = hours_to_close(m["close_time"])
                if h is None or not (-2 <= h <= ACTIVE_WINDOW_H):
                    continue
                m["city"] = city
                out[m["ticker"]] = m
        except Exception as e:
            print(f"[discover] {city} error: {str(e)[:80]}")
    return out


def main():
    print(f"[recorder] OUT_DIR={OUT_DIR}  book={BOOK_CADENCE_S}s trade={TRADE_CADENCE_S}s "
          f"window={ACTIVE_WINDOW_H}h cities={list(SERIES)}")
    seen = load_seen_today()
    if seen:
        print(f"[recorder] resumed: {sum(len(v) for v in seen.values())} trade ids in today's tape")
    markets = discover()
    print(f"[recorder] tracking {len(markets)} markets")
    settled_logged = set()
    last_book = 0.0
    last_trade = 0.0
    last_discover = time.time()
    cyc = 0

    while _RUN:
        now = time.time()
        if now - last_discover >= MARKET_REFRESH_S:
            markets = discover()
            last_discover = now

        # ── trades (more frequent) ──────────────────────────────────────────
        if now - last_trade >= TRADE_CADENCE_S:
            ntr = 0
            for tk, m in list(markets.items()):
                try:
                    sset = seen.setdefault(tk, set())
                    new = kc.trades_since(tk, sset)
                    for t in new:
                        sset.add(t["id"])
                        append("trades", {"ty": "trade", "t": t["t"], "tk": tk,
                                          "p": t["p"], "c": t["c"],
                                          "taker_yes": t["ty"], "id": t["id"]})
                        ntr += 1
                except Exception as e:
                    print(f"[trades] {tk}: {str(e)[:60]}")
            last_trade = now
            tcount = ntr
        else:
            tcount = None

        # ── book snapshots ──────────────────────────────────────────────────
        if now - last_book >= BOOK_CADENCE_S:
            nb = 0
            for tk, m in list(markets.items()):
                try:
                    ob = kc.orderbook(tk, depth=BOOK_DEPTH)
                    append("books", {"ty": "book", "t": ob["ts"], "tk": tk,
                                     "yb": ob["yes_bid"], "ya": ob["yes_ask"],
                                     "yes": ob["yes"], "no": ob["no"]})
                    nb += 1
                except Exception as e:
                    print(f"[book] {tk}: {str(e)[:60]}")
            last_book = now
            cyc += 1
            print(f"[{DT.datetime.now(DT.timezone.utc).strftime('%H:%M:%S')}Z] "
                  f"cycle {cyc}: {len(markets)} mkts, {nb} books, "
                  f"+{tcount if tcount is not None else 0} trades")

        # ── settlement capture ──────────────────────────────────────────────
        for tk, m in list(markets.items()):
            h = hours_to_close(m["close_time"])
            if h is not None and h < -1 and tk not in settled_logged:
                try:
                    fresh = kc.market(tk)
                    if fresh.get("result") in ("yes", "no"):
                        append("meta", {"ty": "meta", "t": time.time(), "tk": tk,
                                        "city": m.get("city"), "floor": m["floor"],
                                        "cap": m["cap"], "close": m["close_time"],
                                        "result": fresh["result"]})
                        settled_logged.add(tk)
                        print(f"[settle] {tk} -> {fresh['result']}")
                except Exception as e:
                    print(f"[settle] {tk}: {str(e)[:60]}")

        time.sleep(min(TRADE_CADENCE_S, BOOK_CADENCE_S) / 2.0)

    print("[recorder] stopped cleanly.")


if __name__ == "__main__":
    main()
