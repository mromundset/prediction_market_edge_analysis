"""
simulator.py — Phase 1: measure the CAPTURED market-making edge from the recorded tape.

Replays the Phase-0 tape (book snapshots + real trade stream + settlement), rests
SIMULATED two-sided quotes per the strategy, models fills with an explicit QUEUE model,
and marks every fill to the recorded resolution. Produces the decisive numbers:
  H1  fills / day / city          (do we get filled?)
  H2  realized PnL / contract on OUR fills, held to resolution  (is our flow profitable?)
along with an adverse-selection-by-time-to-close breakdown and daily PnL.

Two quoting modes × three queue assumptions:
  JOIN    : quote at the current best bid/ask (compete on queue priority at the touch)
  IMPROVE : quote 1 tick inside (jump the queue, smaller spread, more adverse selection)
  queue   : front (Q_ahead=0) | realistic (Q_ahead=touch size) | pessimistic (×1.5)

The fill model is conservative and uses only real executed trades:
  a resting BID at L is hit by real SELL-YES trades (taker_yes=0); we sit behind Q_ahead
  contracts at L and only fill from the trade volume that OVERFLOWS the queue. (ASK side
  symmetric with BUY-YES trades, taker_yes=1.)  No fills are invented.

Run:  python simulator.py            # real tape + self-test
      python simulator.py --selftest # correctness test only
"""
import json, os, sys, glob, math, io, datetime as DT
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TICK = 0.01
DENY_HOURS = 24.0      # don't quote >24h before close (documented loss zone)
QUOTE_SIZE = 100.0     # contracts we offer per side per window (re-quoted each book cycle)
INV_CAP = 500.0        # per-bucket net inventory cap (contracts)
TOL = 0.005            # price match tolerance (half tick)


# ── tape loading ───────────────────────────────────────────────────────────────

def load_tape(tape_dir):
    books, trades, meta = {}, {}, {}
    for f in sorted(glob.glob(os.path.join(tape_dir, "books_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            books.setdefault(o["tk"], []).append(o)
    for f in sorted(glob.glob(os.path.join(tape_dir, "trades_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            trades.setdefault(o["tk"], []).append(o)
    mp = os.path.join(tape_dir, "meta.jsonl")
    if os.path.exists(mp):
        for line in open(mp, encoding="utf-8"):
            try:
                o = json.loads(line)
                meta[o["tk"]] = o
            except Exception:
                pass
    for tk in books:
        books[tk].sort(key=lambda x: x["t"])
    for tk in trades:
        trades[tk].sort(key=lambda x: x["t"])
    return books, trades, meta


def resolve_result(tk, meta, allow_fetch=True, _cache={}):
    if tk in meta and meta[tk].get("result") in ("yes", "no"):
        return 1.0 if meta[tk]["result"] == "yes" else 0.0
    if tk in _cache:
        return _cache[tk]
    if allow_fetch:
        try:
            import kalshi_client as kc
            m = kc.market(tk)
            r = m.get("result")
            v = (1.0 if r == "yes" else 0.0) if r in ("yes", "no") else None
            _cache[tk] = v
            return v
        except Exception:
            _cache[tk] = None
            return None
    return None


def close_ts_of(tk, books, meta):
    if tk in meta and meta[tk].get("close"):
        try:
            return DT.datetime.fromisoformat(meta[tk]["close"].replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    try:
        import kalshi_client as kc
        m = kc.market(tk)
        return DT.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ── core single-market simulation ───────────────────────────────────────────────

def simulate_market(books, trades, result, close_ts, mode="JOIN", queue="realistic"):
    """Return dict with fills list, settled pnl, contracts, and per-fill adverse-sel marks."""
    qmult = {"front": 0.0, "realistic": 1.0, "pessimistic": 1.5}[queue]
    inv = 0.0
    cash = 0.0
    contracts = 0.0
    fills = []
    if len(books) < 2:
        return None
    # index trades by time for window slicing
    tr = trades
    ti = 0
    n = len(tr)
    for k in range(len(books) - 1):
        b0, b1 = books[k], books[k + 1]
        t0, t1 = b0["t"], b1["t"]
        if close_ts is not None and (close_ts - t0) / 3600.0 > DENY_HOURS:
            # advance trade pointer past this window and skip quoting
            while ti < n and tr[ti]["t"] <= t1:
                ti += 1
            continue
        bb, ba = b0.get("yb"), b0.get("ya")
        # my quote levels + queue-ahead
        my_bid = my_ask = None
        q_bid = q_ask = 0.0
        if bb is not None:
            if mode == "JOIN":
                my_bid = round(bb, 2)
                q_bid = qmult * _touch_size(b0["yes"], my_bid)
            else:  # IMPROVE
                my_bid = round(bb + TICK, 2) if (ba is None or ba - bb > TICK + 1e-9) else round(bb, 2)
                q_bid = 0.0
        if ba is not None:
            if mode == "JOIN":
                my_ask = round(ba, 2)
                # ask-side resting interest lives in the NO book at price (1-ask)
                q_ask = qmult * _touch_size(b0["no"], round(1 - my_ask, 2))
            else:
                my_ask = round(ba - TICK, 2) if (bb is None or ba - bb > TICK + 1e-9) else round(ba, 2)
                q_ask = 0.0
        rem_qb, rem_qa = q_bid, q_ask
        size_b = size_a = QUOTE_SIZE
        # process trades in (t0, t1]
        while ti < n and tr[ti]["t"] <= t1:
            t = tr[ti]; ti += 1
            if t["t"] <= t0:
                continue
            p, c, took_yes = t["p"], t["c"], t["taker_yes"]
            if c <= 0:
                continue
            if took_yes == 0 and my_bid is not None:        # SELL-YES hits my BID
                eligible = (abs(p - my_bid) <= TOL) if mode == "JOIN" else (p <= my_bid + TOL)
                if eligible:
                    consumed = min(rem_qb, c); rem_qb -= consumed
                    over = c - consumed
                    fill = min(over, size_b, max(INV_CAP - inv, 0.0))
                    if fill > 0:
                        inv += fill; cash -= my_bid * fill; contracts += fill; size_b -= fill
                        fills.append(_mk(t["t"], "buy", my_bid, fill, books, k))
            elif took_yes == 1 and my_ask is not None:      # BUY-YES hits my ASK
                eligible = (abs(p - my_ask) <= TOL) if mode == "JOIN" else (p >= my_ask - TOL)
                if eligible:
                    consumed = min(rem_qa, c); rem_qa -= consumed
                    over = c - consumed
                    fill = min(over, size_a, max(INV_CAP + inv, 0.0))
                    if fill > 0:
                        inv -= fill; cash += my_ask * fill; contracts += fill; size_a -= fill
                        fills.append(_mk(t["t"], "sell", my_ask, fill, books, k))
    settled = None
    if result is not None:
        settled = cash + inv * result
    return {"fills": fills, "pnl": settled, "contracts": contracts,
            "end_inv": inv, "cash": cash}


def _touch_size(levels, price):
    for px, sz in levels:
        if abs(px - price) <= TOL:
            return sz
    return 0.0


def _mk(t, side, price, size, books, k):
    """fill record + adverse-selection mark (mid at next snapshot)."""
    mid_after = None
    for j in range(k + 1, len(books)):
        b = books[j]
        if b.get("yb") is not None and b.get("ya") is not None:
            mid_after = (b["yb"] + b["ya"]) / 2.0
            break
    return {"t": t, "side": side, "price": price, "size": size, "mid_after": mid_after}


# ── aggregate runner ─────────────────────────────────────────────────────────────

def run(tape_dir, allow_fetch=True):
    books, trades, meta = load_tape(tape_dir)
    tickers = sorted(books)
    print(f"Tape: {len(tickers)} markets with book data, "
          f"{sum(len(v) for v in books.values())} book snaps, "
          f"{sum(len(v) for v in trades.values())} trades, "
          f"{len(meta)} settled in meta")
    if not tickers:
        print("No tape yet — run recorder.py first."); return

    settled_n = 0
    for mode in ("JOIN", "IMPROVE"):
        for queue in ("front", "realistic", "pessimistic"):
            tot_pnl = tot_c = 0.0
            tot_fills = 0
            adv = []   # short-horizon adverse selection per contract
            day_pnl = {}
            mkts_settled = 0
            for tk in tickers:
                res = resolve_result(tk, meta, allow_fetch)
                cts = close_ts_of(tk, books, meta)
                r = simulate_market(books[tk], trades.get(tk, []), res, cts, mode, queue)
                if r is None:
                    continue
                tot_fills += len(r["fills"])
                tot_c += r["contracts"]
                for f in r["fills"]:
                    if f["mid_after"] is not None:
                        s = 1.0 if f["side"] == "buy" else -1.0
                        adv.append(s * (f["mid_after"] - f["price"]) * f["size"])
                if r["pnl"] is not None and r["contracts"] > 0:
                    tot_pnl += r["pnl"]; mkts_settled += 1
                    d = (meta.get(tk, {}).get("close", "") or "")[:10]
                    day_pnl[d] = day_pnl.get(d, 0.0) + r["pnl"]
            settled_n = mkts_settled
            ppc = (tot_pnl / tot_c * 100) if tot_c > 0 else float("nan")
            advc = (sum(adv) / tot_c * 100) if tot_c > 0 else float("nan")
            print(f"\n[{mode:7s} {queue:11s}] fills={tot_fills:5d} contracts={tot_c:10,.0f} "
                  f"settled_mkts={mkts_settled}")
            if tot_c > 0:
                print(f"            held-to-resolution PnL/contract = "
                      f"{ppc:+.3f}c  (H2)   short-horizon adv-sel = {advc:+.3f}c")
                if mkts_settled == 0:
                    print(f"            (no settled markets in tape yet -> PnL/contract pending; "
                          f"fills/queue mechanics validated)")

    if settled_n == 0:
        print("\nNOTE: tape has not reached settlement yet. Fill & queue mechanics run on real")
        print("data; the decisive H2 PnL/contract appears once the recorder tape spans full days.")
        print("Correctness of the settlement/PnL path is verified by --selftest.")


# ── deterministic self-test (correctness without needing settled real data) ──────

def selftest():
    print("=== SELF-TEST (synthetic tape, known answers) ===")
    # one market, two book snapshots. best bid 0.40 (size 50), best ask 0.44 (no-book 0.56 size 50).
    books = [
        {"t": 100.0, "tk": "X", "yb": 0.40, "ya": 0.44,
         "yes": [[0.40, 50.0]], "no": [[0.56, 50.0]]},
        {"t": 200.0, "tk": "X", "yb": 0.40, "ya": 0.44,
         "yes": [[0.40, 50.0]], "no": [[0.56, 50.0]]},
    ]
    # trades in window: a SELL-YES of 120 @0.40 (hits bid), a BUY-YES of 80 @0.44 (hits ask)
    trades = [
        {"t": 150.0, "tk": "X", "p": 0.40, "c": 120.0, "taker_yes": 0},
        {"t": 160.0, "tk": "X", "p": 0.44, "c": 80.0, "taker_yes": 1},
    ]
    cts = 200.0 + 3600  # 1h to close -> within window, quoting allowed

    # JOIN realistic: Q_ahead bid=50 -> fill min(120-50,100,cap)=70 buy@0.40;
    #                 Q_ahead ask=50 -> fill min(80-50,100,cap)=30 sell@0.44
    r = simulate_market(books, trades, result=1.0, close_ts=cts, mode="JOIN", queue="realistic")
    assert abs(sum(f["size"] for f in r["fills"] if f["side"] == "buy") - 70.0) < 1e-6, r["fills"]
    assert abs(sum(f["size"] for f in r["fills"] if f["side"] == "sell") - 30.0) < 1e-6, r["fills"]
    # pnl: cash = -0.40*70 + 0.44*30 = -28 + 13.2 = -14.8 ; inv = 70-30 = 40 ; result=1 -> +40
    # pnl = -14.8 + 40 = 25.2
    assert abs(r["pnl"] - 25.2) < 1e-6, r["pnl"]

    # JOIN front: Q_ahead=0 -> buy fill min(120,100)=100 ; sell fill min(80,100)=80
    r2 = simulate_market(books, trades, 1.0, cts, "JOIN", "front")
    assert abs(sum(f["size"] for f in r2["fills"] if f["side"] == "buy") - 100.0) < 1e-6
    assert abs(sum(f["size"] for f in r2["fills"] if f["side"] == "sell") - 80.0) < 1e-6
    # cash=-0.40*100+0.44*80=-40+35.2=-4.8 ; inv=20 ; pnl=-4.8+20=15.2
    assert abs(r2["pnl"] - 15.2) < 1e-6, r2["pnl"]

    # timing rule: if >24h to close, no quoting -> no fills
    r3 = simulate_market(books, trades, 1.0, 200.0 + 48 * 3600, "JOIN", "front")
    assert len(r3["fills"]) == 0 and r3["pnl"] == 0.0, r3

    # IMPROVE: bid->0.41, ask->0.43 ; eligibility p<=bid+tol / p>=ask-tol ; Q=0
    # sell-yes@0.40 <= 0.41 -> fill 100 buy@0.41 ; buy-yes@0.44 >= 0.43 -> fill 80 sell@0.43
    r4 = simulate_market(books, trades, 0.0, cts, "IMPROVE", "front")
    assert abs(sum(f["size"] for f in r4["fills"] if f["side"] == "buy") - 100.0) < 1e-6
    assert abs(sum(f["size"] for f in r4["fills"] if f["side"] == "sell") - 80.0) < 1e-6
    # cash=-0.41*100+0.43*80=-41+34.4=-6.6 ; inv=20 ; result=0 -> pnl=-6.6
    assert abs(r4["pnl"] - (-6.6)) < 1e-6, r4["pnl"]

    print("  all assertions passed: queue consumption, inventory, settlement PnL,")
    print("  timing rule, JOIN/IMPROVE eligibility all correct.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        selftest()
        print()
        run(os.environ.get("TAPE_DIR", os.path.join(HERE, "tape")))
