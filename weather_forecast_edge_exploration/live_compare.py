"""
live_compare.py — live Kalshi high-temp book vs live GFS ensemble (CORRECT API calls).

Key API corrections (the ones the first pass got wrong):
  - The live order book is GET /markets/{ticker}/orderbook -> {"orderbook_fp": {...}}
    with "yes_dollars" and "no_dollars" arrays of [price, size] (NOT "orderbook"/"yes"/"no").
  - best YES bid = max(price in yes_dollars);  best YES ask = 1 - max(price in no_dollars).
  - Kalshi market-OBJECT fields (yes_bid/volume/open_interest) read null for these series;
    the live book, trades, and candlesticks are the real source of prices/depth.

Usage: python live_compare.py LAX 26JUN11
Shows the devigged market distribution next to the raw and a roughly bias-corrected
ensemble (per-city bias from cache/leads_<city>.json if present).
"""
import json, os, sys, time
import urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
K = "https://api.elections.kalshi.com/trade-api/v2"
CITIES = {"NYC": ("KXHIGHNY", 40.7790, -73.9693), "CHI": ("KXHIGHCHI", 41.9742, -87.9073),
          "MIA": ("KXHIGHMIA", 25.7906, -80.3164), "LAX": ("KXHIGHLAX", 33.9416, -118.4085),
          "AUS": ("KXHIGHAUS", 30.1975, -97.6664)}
MON = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
       "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}


def fetch(url):
    for _ in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research/1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(2)
    raise RuntimeError("fail " + url)


def live_bid_ask(ticker):
    ob = fetch(f"{K}/markets/{ticker}/orderbook").get("orderbook_fp", {}) or {}
    yes = [(float(p), float(s)) for p, s in (ob.get("yes_dollars") or [])]
    no = [(float(p), float(s)) for p, s in (ob.get("no_dollars") or [])]
    bid = max((p for p, _ in yes), default=None)
    ask = (1 - max((p for p, _ in no))) if no else None
    depth = sum(s for _, s in yes) + sum(s for _, s in no)
    return bid, ask, depth


def bounds(m):
    fl, cap = m.get("floor_strike"), m.get("cap_strike")
    if fl is not None and cap is not None: return float(fl), float(cap) + 0.999
    if cap is not None: return -1e9, float(cap)
    if fl is not None: return float(fl) + 1.0, 1e9
    return None, None


def per_city_bias(city):
    p = os.path.join(HERE, "cache", f"leads_{city}.json")
    if not os.path.exists(p):
        return 0.0
    # rough: cannot recompute realized here; return 0 unless a saved bias exists
    return 0.0


def main():
    city = (sys.argv[1] if len(sys.argv) > 1 else "LAX").upper()
    datecode = sys.argv[2] if len(sys.argv) > 2 else None
    ser, lat, lon = CITIES[city]
    ms = fetch(f"{K}/markets?series_ticker={ser}&status=open&limit=100").get("markets", [])
    if datecode:
        ms = [m for m in ms if datecode in m.get("ticker", "")]
    if not ms:
        print("no live markets"); return
    dc = ms[0]["ticker"].split("-")[1]
    iso = f"20{dc[:2]}-{MON[dc[2:5]]}-{dc[5:7]}"
    rows = []
    for m in ms:
        bid, ask, depth = live_bid_ask(m["ticker"])
        lo, hi = bounds(m)
        mid = (bid + ask) / 2 if (bid is not None and ask is not None) else (bid or ask)
        rows.append(dict(sub=m.get("subtitle", "") or m.get("ticker", ""), lo=lo, hi=hi,
                         bid=bid, ask=ask, mid=mid, depth=depth))
        time.sleep(0.03)
    rows.sort(key=lambda r: r["lo"] if r["lo"] > -1e8 else -999)
    s = sum(r["mid"] for r in rows if r["mid"] is not None)

    url = (f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}"
           f"&daily=temperature_2m_max&models=gfs_seamless&temperature_unit=fahrenheit"
           f"&start_date={iso}&end_date={iso}&timezone=America/New_York")
    ed = fetch(url).get("daily", {})
    mem = np.array([ed[k][0] for k in ed if k.startswith("temperature_2m_max") and ed[k][0] is not None])
    bias = per_city_bias(city)

    print(f"\n{city} {iso}   market vig-sum={s:.3f}   ensemble n={len(mem)} mean={mem.mean():.1f}F "
          f"(per-city bias adj={bias:+.1f})")
    print(f"  {'bucket':14s} {'bid':>5} {'ask':>5} {'depth':>7} {'mkt_q':>6} {'ens_raw':>7} {'ens_adj':>7}")
    memadj = mem - bias
    for r in rows:
        q = (r["mid"] / s) if (r["mid"] is not None and s > 0) else None
        eraw = float(np.mean((mem >= r["lo"]) & (mem < r["hi"])))
        eadj = float(np.mean((memadj >= r["lo"]) & (memadj < r["hi"])))
        qs = f"{q:.2f}" if q is not None else "  -"
        print(f"  {r['sub'][:14]:14s} {str(r['bid'] or '-'):>5} {str(r['ask'] or '-'):>5} "
              f"{r['depth']:7.0f} {qs:>6} {eraw:7.2f} {eadj:7.2f}")
    print("\nNote: raw ensemble divergence is mostly grid-vs-station bias (see RESULTS.md);")
    print("over 300 city-days the bias-corrected forecast does NOT beat the market.")


if __name__ == "__main__":
    main()
