"""
analyze_multicity.py — the rigorous revisit.

Addresses two fair criticisms of the first C4 pass:
  (1) live order book was parsed with the wrong key -> use orderbook_fp (done in fetch
      for historical via candlesticks; this script uses the cached decision prices).
  (2) the market was tested against a DETERMINISTIC forecast + constant spread. Here we
      use the genuine point-in-time ~1-day-ahead forecast (prev_day1) WITH PER-CITY
      bias correction and per-city error spread (both leave-one-out), across 5 cities.

For each city we ask: after honest per-city bias correction, does the forecast beat the
market (RPS + trade sim net of Kalshi fee)?  The live divergences (CHI/MIA) are almost
certainly grid-vs-station bias; this quantifies whether ANY edge survives correction.
"""
import json, os, math, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = json.load(open(os.path.join(HERE, "rows.json"), encoding="utf-8"))
KFEE = lambda p: 0.07 * p * (1 - p)


def bb(b):
    if b["kind"] == "between": return b["lo"], b["hi"] + 0.999
    if b["kind"] == "below":   return -1e9, b["hi"]
    if b["kind"] == "above":   return b["lo"] + 1.0, 1e9
    return None, None

def midF(b):
    if b["kind"] == "between": return (b["lo"] + b["hi"]) / 2.0
    if b["kind"] == "below":   return b["hi"] - 1.5
    if b["kind"] == "above":   return b["lo"] + 1.5

def mm(b):
    p = b.get("price") or {}
    yb, ya, last = p.get("yes_bid"), p.get("yes_ask"), p.get("price")
    if yb is not None and ya is not None: return (yb + ya) / 2.0
    return last if last is not None else (ya if ya is not None else yb)

def fcprobs(bs, mu, sig):
    o = []
    for b in bs:
        lo, hi = b["lo"], b["hi"]
        pl = 0.0 if lo <= -1e8 else norm.cdf((lo - mu) / sig)
        ph = 1.0 if hi >= 1e8 else norm.cdf((hi - mu) / sig)
        o.append(max(ph - pl, 1e-9))
    s = sum(o); return [x / s for x in o]

def rps(p, ri):
    c = cp = co = 0.0
    for i, x in enumerate(p):
        cp += x; co += (1 if i == ri else 0); c += (cp - co) ** 2
    return c / (len(p) - 1)


# build per-city records
def build(city_rows):
    recs = []
    for row in city_rows:
        bs = []
        for b in row["buckets"]:
            lo, hi = bb(b)
            bs.append(dict(lo=lo, hi=hi, key=lo if lo > -1e8 else -999,
                           realized=b["result"] == "yes", mid=mm(b), midF=midF(b),
                           price=b.get("price")))
        if not any(b["realized"] for b in bs):
            continue
        mids = [b["mid"] for b in bs if b["mid"] is not None]
        s = sum(mids)
        if s <= 0:
            continue
        for b in bs:
            b["q"] = (b["mid"] / s) if b["mid"] is not None else 0.0
        bs.sort(key=lambda x: x["key"])
        ri = next(i for i, b in enumerate(bs) if b["realized"])
        rf = next((b["midF"] for b in bs if b["realized"]), None)
        recs.append(dict(date=row["date"], bs=bs, ri=ri, rf=rf))
    return recs


cities = sorted({r["city"] for r in ROWS})
print(f"Cities: {cities}   total rows: {len(ROWS)}")
print("\nPer-city: honest prev_day1 forecast, PER-CITY bias-corrected (LOO), vs market")
print("=" * 78)
print(f"{'city':5} {'n':>3} {'bias':>6} {'sig':>5} | {'mkt_RPS':>8} {'fc_RPS':>8} "
      f"{'diff':>7} {'t':>6} | {'trade_n':>7} {'ret/t':>7} {'t':>5} {'edge?':>6}")

pooled_d = []
for city in cities:
    crows = [r for r in ROWS if r["city"] == city]
    recs = build(crows)
    leads = json.load(open(os.path.join(HERE, "cache", f"leads_{city}.json"), encoding="utf-8"))
    P1 = leads["prev1"]
    have = [r for r in recs if r["date"] in P1 and r["rf"] is not None]
    if len(have) < 10:
        print(f"{city:5} too few ({len(have)})")
        continue
    err = np.array([P1[r["date"]] - r["rf"] for r in have])
    fc_rps, mk_rps, pnl = [], [], []
    for i, r in enumerate(have):
        oth = [P1[have[j]["date"]] - have[j]["rf"] for j in range(len(have)) if j != i]
        bias = np.mean(oth); sig = max(np.std(oth), 1.0)
        fp = fcprobs(r["bs"], P1[r["date"]] - bias, sig)
        fc_rps.append(rps(fp, r["ri"]))
        mk_rps.append(rps([b["q"] for b in r["bs"]], r["ri"]))
        for j, b in enumerate(r["bs"]):
            q = b["q"]
            if b["mid"] is None or not (0.03 <= q <= 0.97):
                continue
            edge = fp[j] - q
            if abs(edge) <= 0.10:
                continue
            win = (j == r["ri"])
            pr = b.get("price") or {}
            if edge > 0:
                c = pr.get("yes_ask") or (q + 0.02)
            else:
                c = (1 - (pr.get("yes_bid") or (q - 0.02))); win = not win
            if not (0 < c < 1):
                continue
            cost = c + KFEE(c)
            pnl.append(((1.0 if win else 0.0) - cost) / cost)
    fc_rps = np.array(fc_rps); mk_rps = np.array(mk_rps)
    d = mk_rps - fc_rps                      # >0 => forecast better
    pooled_d += list(d)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std(ddof=1) > 0 else 0
    if pnl:
        pa = np.array(pnl)
        pt = pa.mean() / (pa.std(ddof=1) / math.sqrt(len(pa))) if len(pa) > 2 and pa.std(ddof=1) > 0 else 0
        edge = "YES" if (d.mean() > 0 and t > 2 and pa.mean() > 0 and pt > 2) else "no"
        print(f"{city:5} {len(have):3d} {err.mean():+6.2f} {err.std():5.2f} | "
              f"{mk_rps.mean():8.4f} {fc_rps.mean():8.4f} {d.mean():+7.4f} {t:+6.2f} | "
              f"{len(pa):7d} {pa.mean():+7.1%} {pt:+5.1f} {edge:>6}")
    else:
        print(f"{city:5} {len(have):3d} {err.mean():+6.2f} {err.std():5.2f} | "
              f"{mk_rps.mean():8.4f} {fc_rps.mean():8.4f} {d.mean():+7.4f} {t:+6.2f} | "
              f"{'0':>7} {'-':>7} {'-':>5} {'no':>6}")

pd = np.array(pooled_d)
pt = pd.mean() / (pd.std(ddof=1) / math.sqrt(len(pd))) if len(pd) > 2 else 0
print("=" * 78)
print(f"POOLED (all cities): mean RPS diff (mkt-fc) = {pd.mean():+.4f}  t={pt:+.2f}  "
      f"n={len(pd)}   {'FORECAST EDGE' if pd.mean()>0 and pt>2 else 'no forecast edge'}")
print("\n(bias = mean(prev1_forecast - realized) per city; large |bias| = grid-vs-station offset)")
