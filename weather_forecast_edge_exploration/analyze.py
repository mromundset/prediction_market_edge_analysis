"""
analyze.py — Is Kalshi's daily NYC high-temp market beatable by a forecast?

Data (from fetch_data.py, 60 NYC days):
  - decision-time market YES bid/ask per MECE bucket (D-1 22:00 UTC)
  - realized bucket (Kalshi `result`, = official NWS Central Park high)
  - Open-Meteo deterministic historical forecast + gridded archive (all days)
  - 31-member GFS ensemble (only last ~4 days; ensemble API has no deep archive)

Tests:
  0. Data quality: do devigged bucket mids sum ~1?  grid-vs-station bias.
  1. MARKET skill: is the decision-time market well-calibrated & sharp vs realized?
     (Brier + ranked probability score RPS + calibration; needs no forecast.)
  2. FORECAST vs MARKET: bias-corrected deterministic forecast -> bucket probs via a
     climatological day-ahead error spread; does it beat the market on RPS?
     (leave-one-out bias/sigma to avoid fitting to the same data.)
  3. Ensemble spot-check on the 4 days with full members.
  4. Trade sim: forecast-vs-market divergence, net of Kalshi fee 0.07*p*(1-p)+spread,
     annualized vs the bar.
Pure numpy/scipy.
"""
import json, os, math, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = json.load(open(os.path.join(HERE, "rows.json"), encoding="utf-8"))
KFEE = lambda p: 0.07 * p * (1 - p)        # Kalshi quadratic taker fee


# ── bucket geometry ───────────────────────────────────────────────────────────

def bucket_bounds(b):
    """Return (lo, hi) numeric F bounds; below -> (-inf,hi), above -> (lo,inf)."""
    if b["kind"] == "between":
        return b["lo"], b["hi"] + 0.999          # 'between 78 and 79' = [78,80)
    if b["kind"] == "below":
        return -1e9, b["hi"]                       # < hi  ('77 or below' => hi=78)
    if b["kind"] == "above":
        return b["lo"] + 1.0, 1e9                  # > lo  ('86 or above' => lo=85)
    return None, None


def bucket_mid_F(b):
    if b["kind"] == "between":
        return (b["lo"] + b["hi"]) / 2.0
    if b["kind"] == "below":
        return b["hi"] - 1.5
    if b["kind"] == "above":
        return b["lo"] + 1.5
    return None


def market_mid(b):
    p = b.get("price") or {}
    yb, ya, last = p.get("yes_bid"), p.get("yes_ask"), p.get("price")
    if yb is not None and ya is not None:
        return (yb + ya) / 2.0, ya - yb
    if last is not None:
        return last, 0.04
    if ya is not None:
        return ya, 0.04
    if yb is not None:
        return yb, 0.04
    return None, None


def ordered_buckets(row):
    """Return buckets sorted by temperature, with bounds + realized flag + mid."""
    bs = []
    for b in row["buckets"]:
        lo, hi = bucket_bounds(b)
        mid, spread = market_mid(b)
        bs.append(dict(lo=lo, hi=hi, key=(lo if lo > -1e8 else -999),
                       realized=(b["result"] == "yes"), mid=mid, spread=spread,
                       midF=bucket_mid_F(b)))
    bs.sort(key=lambda x: x["key"])
    return bs


def devig(bs):
    """Normalize market mids across the MECE ladder to sum to 1."""
    mids = [b["mid"] for b in bs if b["mid"] is not None]
    s = sum(mids)
    if s <= 0:
        return None
    for b in bs:
        b["q"] = (b["mid"] / s) if b["mid"] is not None else 0.0
    return s


def forecast_bucket_probs(bs, mu, sigma):
    """P(bucket) = Phi((hi-mu)/sig) - Phi((lo-mu)/sig) for a Normal(mu,sigma)."""
    out = []
    for b in bs:
        lo = b["lo"]; hi = b["hi"]
        plo = 0.0 if lo <= -1e8 else norm.cdf((lo - mu) / sigma)
        phi = 1.0 if hi >= 1e8 else norm.cdf((hi - mu) / sigma)
        out.append(max(phi - plo, 1e-9))
    s = sum(out)
    return [x / s for x in out]


def rps(probs, realized_idx):
    """Ranked Probability Score for ordered categories (lower=better)."""
    cum = 0.0; cp = 0.0; co = 0.0
    for i, p in enumerate(probs):
        cp += p
        co += (1.0 if i == realized_idx else 0.0)
        cum += (cp - co) ** 2
    return cum / (len(probs) - 1)


def brier_multi(probs, realized_idx):
    return sum((p - (1.0 if i == realized_idx else 0.0)) ** 2
               for i, p in enumerate(probs))


# ── assemble clean per-day records ────────────────────────────────────────────

def realized_mid_F(row):
    for b in row["buckets"]:
        if b["result"] == "yes":
            return bucket_mid_F(b)
    return None


recs = []
for row in ROWS:
    bs = ordered_buckets(row)
    if not any(b["realized"] for b in bs):
        continue
    s = devig(bs)
    if s is None:
        continue
    ridx = next(i for i, b in enumerate(bs) if b["realized"])
    recs.append(dict(date=row["date"], bs=bs, ridx=ridx, vigsum=s,
                     realizedF=realized_mid_F(row),
                     hf=row.get("hist_forecast"),
                     arch=row.get("archive_tmax"),
                     ens=row.get("ens_members") or []))

print(f"Clean day-records: {len(recs)}")


# ── 0. data quality ───────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("0.  DATA QUALITY")
print("=" * 70)
vigs = np.array([r["vigsum"] for r in recs])
print(f"  market bucket-mid sum (pre-devig): mean={vigs.mean():.3f} "
      f"min={vigs.min():.3f} max={vigs.max():.3f}  (1.0=coherent; >1 = overround)")
spreads = [b["spread"] for r in recs for b in r["bs"]
           if b["spread"] is not None and 0.05 <= (b["mid"] or 0) <= 0.95]
print(f"  median bucket spread (mid 0.05-0.95): {np.median(spreads)*100:.1f}c "
      f"(n={len(spreads)})")
# grid-vs-station bias
ab = [r["arch"] - r["realizedF"] for r in recs if r["arch"] is not None]
hb = [r["hf"] - r["realizedF"] for r in recs if r["hf"] is not None]
print(f"  Open-Meteo ARCHIVE  - NWS bucket mid: mean={np.mean(ab):+.2f}F std={np.std(ab):.2f} (n={len(ab)})")
print(f"  Open-Meteo HIST-FC  - NWS bucket mid: mean={np.mean(hb):+.2f}F std={np.std(hb):.2f} (n={len(hb)})")


# ── 1. market skill ───────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("1.  MARKET SKILL  (decision-time devigged price vs realized bucket)")
print("=" * 70)
mkt_rps = np.array([rps([b["q"] for b in r["bs"]], r["ridx"]) for r in recs])
mkt_brier = np.array([brier_multi([b["q"] for b in r["bs"]], r["ridx"]) for r in recs])
# climatology baseline: each day, use the empirical bucket frequencies over all days
nb = len(recs[0]["bs"])
clim = np.zeros(nb)
for r in recs:
    clim[r["ridx"]] += 1
clim = clim / clim.sum()
clim_rps = np.array([rps(list(clim), r["ridx"]) for r in recs])
print(f"  MARKET   mean RPS={mkt_rps.mean():.4f}   mean Brier={mkt_brier.mean():.4f}")
print(f"  CLIMATOLOGY mean RPS={clim_rps.mean():.4f}  (market should beat this)")
skill = 1 - mkt_rps.mean() / clim_rps.mean()
print(f"  Market RPS skill score vs climatology = {skill:.3f}  "
      f"({'sharp' if skill>0.3 else 'weak'})")
# calibration: bucket-level reliability
print("\n  Calibration (market prob bucket -> realized freq):")
allq = np.array([b["q"] for r in recs for b in r["bs"]])
ally = np.array([1.0 if i == r["ridx"] else 0.0 for r in recs for i, b in enumerate(r["bs"])])
for lo, hi in [(0, .1), (.1, .25), (.25, .5), (.5, .75), (.75, 1.01)]:
    m = (allq >= lo) & (allq < hi)
    if m.sum():
        print(f"    q in [{lo:.2f},{hi:.2f}): n={m.sum():3d}  mean q={allq[m].mean():.3f}  "
              f"realized freq={ally[m].mean():.3f}")


# ── 2. forecast vs market (leave-one-out deterministic) ──────────────────────

print("\n" + "=" * 70)
print("2.  FORECAST vs MARKET  (bias-corrected deterministic + climo spread, LOO)")
print("=" * 70)
have_hf = [r for r in recs if r["hf"] is not None and r["realizedF"] is not None]
# global stats for LOO
hf_err = np.array([r["hf"] - r["realizedF"] for r in have_hf])
print(f"  hist-forecast error: mean(bias)={hf_err.mean():+.2f}F  std={hf_err.std():.2f}F  (n={len(have_hf)})")
fc_rps, mk_rps2 = [], []
for i, r in enumerate(have_hf):
    others = [hf_err[j] for j in range(len(have_hf)) if j != i]
    bias = np.mean(others)
    sigma = max(np.std(others), 1.0)
    mu = r["hf"] - bias
    fp = forecast_bucket_probs(r["bs"], mu, sigma)
    fc_rps.append(rps(fp, r["ridx"]))
    mk_rps2.append(rps([b["q"] for b in r["bs"]], r["ridx"]))
fc_rps = np.array(fc_rps); mk_rps2 = np.array(mk_rps2)
print(f"  FORECAST mean RPS={fc_rps.mean():.4f}")
print(f"  MARKET   mean RPS={mk_rps2.mean():.4f}  (same days)")
d = mk_rps2 - fc_rps    # >0 => forecast better
n = len(d)
tstat = d.mean() / (d.std(ddof=1) / math.sqrt(n)) if d.std(ddof=1) > 0 else 0
print(f"  mean RPS diff (market - forecast) = {d.mean():+.4f}  t={tstat:+.2f}  "
      f"({'FORECAST beats market' if d.mean()>0 and tstat>2 else 'no significant forecast edge'})")


# ── 3. ensemble spot-check ────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("3.  ENSEMBLE SPOT-CHECK  (days with full 31-member GFS)")
print("=" * 70)
ens_days = [r for r in recs if len(r["ens"]) >= 10 and r["realizedF"] is not None]
print(f"  days with ensemble: {len(ens_days)}")
# use the SAME station bias as archive for a fair check
bias_arch = np.mean(ab)
for r in ens_days:
    mem = np.array(r["ens"]) - bias_arch        # bias-correct members to station
    # empirical bucket probs from members
    ep = []
    for b in r["bs"]:
        lo = b["lo"]; hi = b["hi"]
        ep.append(max(np.mean((mem >= lo) & (mem < hi)), 1e-9))
    ep = [x / sum(ep) for x in ep]
    er = rps(ep, r["ridx"]); mr = rps([b["q"] for b in r["bs"]], r["ridx"])
    print(f"  {r['date']}: ens_mean(corr)={mem.mean():.1f}F realized~{r['realizedF']:.0f}  "
          f"RPS ens={er:.3f} market={mr:.3f}  {'ens better' if er<mr else 'market better'}")


# ── 4. trade sim ──────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("4.  TRADE SIM  (forecast vs market divergence, net of Kalshi fee+spread)")
print("=" * 70)
for thr in (0.05, 0.10, 0.15):
    pnl = []; ntr = 0
    for i, r in enumerate(have_hf):
        others = [hf_err[j] for j in range(len(have_hf)) if j != i]
        bias = np.mean(others); sigma = max(np.std(others), 1.0)
        fp = forecast_bucket_probs(r["bs"], r["hf"] - bias, sigma)
        for j, b in enumerate(r["bs"]):
            q = b["q"]; f = fp[j]
            if b["mid"] is None or not (0.03 <= q <= 0.97):
                continue
            edge = f - q
            if abs(edge) <= thr:
                continue
            win = (j == r["ridx"])
            if edge > 0:        # forecast says cheap -> buy YES at ask
                ask = (b.get("price") or {}).get("yes_ask")
                c = ask if ask else q + b["spread"] / 2
                if not (0 < c < 1): continue
                cost = c + KFEE(c)
                pnl.append(((1.0 if win else 0.0) - cost) / cost); ntr += 1
            else:               # forecast says rich -> buy NO at (1-bid)
                bid = (b.get("price") or {}).get("yes_bid")
                c = (1 - bid) if bid else (1 - q) + b["spread"] / 2
                if not (0 < c < 1): continue
                cost = c + KFEE(c)
                pnl.append(((1.0 if not win else 0.0) - cost) / cost); ntr += 1
    if ntr:
        pnl = np.array(pnl)
        t = pnl.mean() / (pnl.std(ddof=1) / math.sqrt(len(pnl))) if len(pnl) > 2 else 0
        # annualize: ~1 day hold, trades spread over the period
        days_span = len(have_hf)
        ann = pnl.mean() * len(pnl) / days_span * 365  # rough: per-trade ret * trades/day * 365
        print(f"  thr={thr:.2f}: n={ntr:3d} mean_ret/trade={pnl.mean():+.2%} t={t:+.2f} "
              f"hit={np.mean(pnl>0):.0%}  rough ann≈{ann:+.0%}")
    else:
        print(f"  thr={thr:.2f}: no trades")


# ── 5. DECISIVE: honest point-in-time forecast (prev_day1) vs market ──────────

print("\n" + "=" * 70)
print("5.  DECISIVE: HONEST point-in-time forecast (lead ~1 day) vs market")
print("    lead0 = Open-Meteo same-day run (PEEKS past the D-1 decision -> contaminated)")
print("    prev1 = forecast made ~1 day earlier (AVAILABLE at D-1 22:00 decision)")
print("=" * 70)
leads = json.load(open(os.path.join(HERE, "cache", "omforecast_leads.json"), encoding="utf-8"))
L0, P1 = leads["lead0"], leads["prev1"]

def lead_test(fdict, label):
    have = [r for r in recs if r["date"] in fdict and r["realizedF"] is not None]
    err = np.array([fdict[r["date"]] - r["realizedF"] for r in have])
    fc_rps, mk_rps = [], []
    pnls = {0.05: [], 0.10: []}
    for i, r in enumerate(have):
        others = [fdict[have[j]["date"]] - have[j]["realizedF"]
                  for j in range(len(have)) if j != i]
        bias = np.mean(others); sigma = max(np.std(others), 1.0)
        mu = fdict[r["date"]] - bias
        fp = forecast_bucket_probs(r["bs"], mu, sigma)
        fc_rps.append(rps(fp, r["ridx"]))
        mk_rps.append(rps([b["q"] for b in r["bs"]], r["ridx"]))
        for thr in pnls:
            for j, b in enumerate(r["bs"]):
                q = b["q"]
                if b["mid"] is None or not (0.03 <= q <= 0.97):
                    continue
                edge = fp[j] - q
                if abs(edge) <= thr:
                    continue
                win = (j == r["ridx"])
                if edge > 0:
                    ask = (b.get("price") or {}).get("yes_ask")
                    c = ask if ask else q + (b["spread"] or 0.04) / 2
                else:
                    bid = (b.get("price") or {}).get("yes_bid")
                    c = (1 - bid) if bid else (1 - q) + (b["spread"] or 0.04) / 2
                    win = not win
                if not (0 < c < 1):
                    continue
                cost = c + KFEE(c)
                pnls[thr].append(((1.0 if win else 0.0) - cost) / cost)
    fc_rps = np.array(fc_rps); mk_rps = np.array(mk_rps)
    d = mk_rps - fc_rps
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std(ddof=1) > 0 else 0
    print(f"\n  [{label}]  n={len(have)}  forecast err: bias={err.mean():+.2f}F std={err.std():.2f}F")
    print(f"    RPS  forecast={fc_rps.mean():.4f}  market={mk_rps.mean():.4f}  "
          f"diff(mkt-fc)={d.mean():+.4f}  t={t:+.2f}  "
          f"{'FC BEATS MKT' if d.mean()>0 and t>2 else 'no sig. edge'}")
    for thr, pl in pnls.items():
        if len(pl) > 2:
            pl = np.array(pl)
            tt = pl.mean() / (pl.std(ddof=1) / math.sqrt(len(pl)))
            ann = pl.mean() * len(pl) / len(have) * 365
            print(f"    trade thr={thr:.2f}: n={len(pl):3d} ret/trade={pl.mean():+.2%} "
                  f"t={tt:+.2f} hit={np.mean(pl>0):.0%} rough_ann={ann:+.0%}")

lead_test(L0, "lead0  CONTAMINATED (same-day run)")
lead_test(P1, "prev1  HONEST (~1-day-ahead, available at decision)")

print("\nDONE.")
