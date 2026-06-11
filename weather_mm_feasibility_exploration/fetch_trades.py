"""
fetch_trades.py — full trade history for Kalshi high-temp markets (for MM feasibility).

For each settled market in the last N days, per city: pull every trade
(count_fp, yes_price_dollars, taker_side, created_time) and the realized result.
This lets us compute the EXACT realized PnL of the passive (maker) side held to
resolution:  maker_pnl = (P - outcome) if taker bought YES else (outcome - P).

Caches one compact file per market in cache_trades/.
"""
import json, os, time, datetime as DT
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache_trades")
os.makedirs(CACHE, exist_ok=True)
K = "https://api.elections.kalshi.com/trade-api/v2"

CITIES = {"NYC": "KXHIGHNY", "CHI": "KXHIGHCHI", "MIA": "KXHIGHMIA",
          "LAX": "KXHIGHLAX", "AUS": "KXHIGHAUS"}
N_DAYS = 30
MAX_PAGES = 60          # 60*1000 = 60k trades/market cap (ATM buckets are the big ones)


def fetch(url):
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research/1"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1.5 + i)
    raise RuntimeError("fail " + url)


def settled_markets(series):
    out, cursor = [], ""
    for _ in range(20):
        url = f"{K}/markets?series_ticker={series}&status=settled&limit=200"
        if cursor:
            url += f"&cursor={cursor}"
        d = fetch(url)
        out += d.get("markets", [])
        cursor = d.get("cursor", "")
        if not cursor:
            break
        time.sleep(0.1)
    return out


def market_trades(ticker):
    trades, cursor = [], ""
    for _ in range(MAX_PAGES):
        url = f"{K}/markets/trades?ticker={ticker}&limit=1000"
        if cursor:
            url += f"&cursor={cursor}"
        d = fetch(url)
        tr = d.get("trades", [])
        for t in tr:
            trades.append([
                t.get("created_time", ""),
                float(t.get("yes_price_dollars") or 0),
                float(t.get("count_fp") or 0),
                1 if t.get("taker_side") == "yes" else 0,   # 1 = taker bought YES
            ])
        cursor = d.get("cursor", "")
        if not cursor or not tr:
            break
        time.sleep(0.02)
    return trades


def main():
    import sys
    cities = sys.argv[1:] if len(sys.argv) > 1 else ["NYC"]
    for city in cities:
        series = CITIES[city]
        markets = settled_markets(series)
        # recent N_DAYS by close date
        def cdate(m):
            return m.get("close_time", "")[:10]
        dates = sorted({cdate(m) for m in markets if cdate(m)})[-N_DAYS:]
        keep = [m for m in markets if cdate(m) in dates]
        print(f"{city}: {len(keep)} markets over {len(dates)} days "
              f"({dates[0]}..{dates[-1]})")
        for i, m in enumerate(keep):
            tk = m["ticker"]
            out = os.path.join(CACHE, f"{tk}.json")
            if os.path.exists(out):
                continue
            tr = market_trades(tk)
            rec = {"ticker": tk, "city": city, "result": m.get("result"),
                   "floor": m.get("floor_strike"), "cap": m.get("cap_strike"),
                   "close": m.get("close_time"), "trades": tr}
            with open(out, "w") as f:
                json.dump(rec, f)
            if (i + 1) % 12 == 0:
                print(f"  {city}: {i+1}/{len(keep)} markets, last {tk} ({len(tr)} trades)")
        print(f"{city}: done")


if __name__ == "__main__":
    main()
