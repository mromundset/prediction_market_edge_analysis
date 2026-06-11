"""
fetch_data.py — collect everything needed to backtest strategy A1 (Polymarket daily
crypto digitals vs Deribit options-implied probability) over the full life of the
daily product (2026-05-22 .. 2026-06-10, BTC + ETH).

Caches each piece under data_cache/ so re-runs are free:
  events_{cur}.json          resolved PM daily events with strikes/outcomes/tokens
  clob_{tokenid}.json        PM price history around the two decision times
  deribit_{cur}_{day}_{dec}.json   option trades (with IV) in a 3h window per decision
  spot_{sym}_{ts}.json       Binance 1m close at each decision timestamp (resolution index)

Decision times per event date D (resolution 16:00 UTC = noon ET):
  "D-1 20:00 UTC"  -> T = 20h  (Deribit expiries D 08:00 and D+1 08:00 bracket resolution)
  "D   10:00 UTC"  -> T = 6h   (only D+1 08:00 left -> flat-vol extrapolation, flagged)
"""
import json, os, re, time, urllib.request, datetime as DT

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_cache")
os.makedirs(CACHE, exist_ok=True)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DHIST = "https://history.deribit.com/api/v2"
BINANCE = "https://api.binance.com/api/v3"

START = DT.date(2026, 5, 22)
END = DT.date(2026, 6, 10)          # last fully-resolved daily event
CURS = {"BTC": ("bitcoin", "BTCUSDT"), "ETH": ("ethereum", "ETHUSDT")}
MONTHS = ["january","february","march","april","may","june","july","august",
          "september","october","november","december"]


def get(url, t=60, retries=4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=t) as r:
                return json.load(r)
        except Exception as e:                          # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def cached(name, fn):
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    val = fn()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(val, f)
    time.sleep(0.15)
    return val


def daterange():
    d = START
    while d <= END:
        yield d
        d += DT.timedelta(days=1)


def decision_times(d):
    """(label, decision datetime, resolution datetime) for event date d."""
    res = DT.datetime(d.year, d.month, d.day, 16, 0, tzinfo=DT.timezone.utc)
    return [
        ("D-1_20Z", DT.datetime(d.year, d.month, d.day, 20, 0, tzinfo=DT.timezone.utc)
         - DT.timedelta(days=1), res),
        ("D_10Z", DT.datetime(d.year, d.month, d.day, 10, 0, tzinfo=DT.timezone.utc), res),
    ]


# ---------- 1. Polymarket events ----------
def fetch_events(cur):
    coin = CURS[cur][0]
    evs = []
    for d in daterange():
        slug = f"{coin}-above-on-{MONTHS[d.month-1]}-{d.day}-{d.year}"
        try:
            e = get(f"{GAMMA}/events/slug/{slug}")
        except Exception:                               # noqa: BLE001
            print(f"  missing: {slug}")
            continue
        e = e[0] if isinstance(e, list) else e
        mkts = []
        for m in e.get("markets", []):
            mk = re.search(r"\$([\d,]+)", m.get("question", ""))
            pr = m.get("outcomePrices")
            pr = json.loads(pr) if isinstance(pr, str) else pr
            cl = m.get("clobTokenIds")
            cl = json.loads(cl) if isinstance(cl, str) else cl
            if not (mk and pr and cl):
                continue
            outcome = 1 if float(pr[0]) > 0.5 else 0    # resolved 1/0
            mkts.append({"strike": float(mk.group(1).replace(",", "")),
                         "outcome": outcome, "tok": cl[0],
                         "q": m.get("question", "")})
        evs.append({"date": d.isoformat(), "slug": slug, "markets": mkts})
        time.sleep(0.1)
    return evs


# ---------- 2. PM price history around decisions ----------
def fetch_clob(tok, d):
    """10-min fidelity from D-1 18:00Z to D 16:00Z."""
    t0 = int((DT.datetime(d.year, d.month, d.day, 18, 0, tzinfo=DT.timezone.utc)
              - DT.timedelta(days=1)).timestamp())
    t1 = int(DT.datetime(d.year, d.month, d.day, 16, 0, tzinfo=DT.timezone.utc).timestamp())
    r = get(f"{CLOB}/prices-history?market={tok}&startTs={t0}&endTs={t1}&fidelity=10")
    return r.get("history", [])


# ---------- 3. Deribit option trades around decisions ----------
def fetch_deribit_window(cur, dec):
    """All option trades (any expiry) in [dec-90min, dec+90min]; pages if 1000-capped."""
    t0 = int((dec - DT.timedelta(minutes=90)).timestamp() * 1000)
    t1 = int((dec + DT.timedelta(minutes=90)).timestamp() * 1000)
    out, start = [], t0
    for _ in range(8):
        r = get(f"{DHIST}/public/get_last_trades_by_currency_and_time?currency={cur}"
                f"&kind=option&start_timestamp={start}&end_timestamp={t1}&count=1000"
                f"&sorting=asc")
        tr = r["result"]["trades"]
        out += tr
        if len(tr) < 1000:
            break
        start = tr[-1]["timestamp"] + 1
    keep = [{"i": t["instrument_name"], "ts": t["timestamp"], "iv": t.get("iv"),
             "S": t.get("index_price"), "amt": t.get("amount")}
            for t in out if t.get("iv")]
    return keep


# ---------- 4. Binance spot at decision (the resolution index) ----------
def fetch_spot(sym, dec):
    ms = int(dec.timestamp() * 1000)
    r = get(f"{BINANCE}/klines?symbol={sym}&interval=1m&startTime={ms}&limit=1")
    return float(r[0][4]) if r else None


def main():
    for cur, (coin, sym) in CURS.items():
        print(f"=== {cur} ===")
        evs = cached(f"events_{cur}.json", lambda c=cur: fetch_events(c))
        n_mkts = sum(len(e["markets"]) for e in evs)
        print(f"  {len(evs)} events, {n_mkts} strike-markets")

        for e in evs:
            d = DT.date.fromisoformat(e["date"])
            for m in e["markets"]:
                cached(f"clob_{m['tok'][:24]}.json", lambda t=m["tok"], dd=d: fetch_clob(t, dd))
            for label, dec, _res in decision_times(d):
                cached(f"deribit_{cur}_{e['date']}_{label}.json",
                       lambda c=cur, dc=dec: fetch_deribit_window(c, dc))
                cached(f"spot_{sym}_{int(dec.timestamp())}.json",
                       lambda s=sym, dc=dec: fetch_spot(s, dc))
            print(f"  cached {e['date']} ({len(e['markets'])} markets)")
    print("\nAll cached under", CACHE)


if __name__ == "__main__":
    main()
