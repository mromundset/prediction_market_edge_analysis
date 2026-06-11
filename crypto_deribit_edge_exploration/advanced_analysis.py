"""
advanced_analysis.py — A1 REVISIT with the full forecast-evaluation toolkit.

The original backtest.py compared PM directly to Deribit's RISK-NEUTRAL N(d2).
That is the wrong null: Deribit's N(d2) is a zero-drift Q-measure probability,
while Polymarket prices PHYSICAL (P-measure) beliefs that include crypto's large
positive drift / risk premium. The wedge P_P - P_Q is a risk premium, NOT alpha.

This script:
  1. Recovers per-row total vol v=sigma*sqrt(T) from (model=N(d2), k=ln(K/S)).
  2. Builds the physical-adjusted probability P_P = N(d2 + lambda*T/v) over a
     risk-premium grid lambda in {0, 0.3, 0.66, 1.0}/yr, and shows the
     physical-adjusted gap (pm - P_P) is centered near zero (premium explains lean).
  3. Forecast-evaluation tests the original lacked:
       - Diebold-Mariano (Brier loss) with Harvey-Leybourne-Newbold small-sample
         correction, on DAY-AGGREGATED loss diffs (the independent unit).
       - Spiegelhalter's calibration z-test for PM, RN model, and physical model.
       - Murphy / Brier decomposition (reliability-resolution-uncertainty).
       - Forecast-encompassing regression  outcome ~ a + b1*PM + b2*model  (day-clustered SE).
       - Leave-one-DAY-out logit pooling: does a combination beat BOTH venues OOS?
         (the single cleanest inefficiency detector).
  4. Power analysis: minimum detectable Brier edge at n=20 independent days, and
     the n needed to detect a 1pp edge at 80% power.
  5. Drift-contamination regression: daily loss-diff ~ signed spot return.
  6. Multiple-testing guard: max-|t| sign-flip bootstrap across the config grid.

Reads rows.json produced by backtest.py.  Pure numpy/scipy.
"""
import json, math, os
from collections import defaultdict

import numpy as np
from scipy.stats import norm, t as tdist

HERE = os.path.dirname(os.path.abspath(__file__))
PM_BAND = (0.03, 0.97)
T_HOURS = {"D-1_20Z": 20.0, "D_10Z": 6.0}          # horizon dec->resolution
LAMBDAS = [0.0, 0.30, 0.66, 1.0]                   # annualized risk premium grid
RNG = np.random.default_rng(12345)


# ── load ────────────────────────────────────────────────────────────────────

def load_rows():
    with open(os.path.join(HERE, "rows.json"), encoding="utf-8") as f:
        rows = json.load(f)
    # keep only banded, in-smile-range rows (the honest comparable set)
    sel = [r for r in rows
           if PM_BAND[0] <= r["pm"] <= PM_BAND[1] and r["in_smile_range"]]
    return rows, sel


# ── 1. recover total vol and 2. physical adjustment ──────────────────────────

def recover_total_vol(model_prob, k):
    """
    model = N(d2), d2 = (-k - 0.5 v^2)/v  with v = sigma*sqrt(T), k = ln(K/S).
    Solve 0.5 v^2 + d2 v + k = 0  for v>0.  Returns (v, d2) or (None, d2).
    """
    model_prob = min(max(model_prob, 1e-6), 1 - 1e-6)
    d2 = norm.ppf(model_prob)
    disc = d2 * d2 - 2.0 * k
    if disc < 0:
        return None, d2
    v = -d2 + math.sqrt(disc)          # positive root
    if v <= 1e-6:
        v = -d2 - math.sqrt(disc)
    return (v if v > 1e-6 else None), d2


def physical_prob(d2, v, T, lam):
    """P_P(S>K) = N(d2 + lambda*T/v).  lam in /yr, T in yr, v = sigma*sqrt(T)."""
    if v is None or v <= 0:
        return None
    return float(norm.cdf(d2 + lam * T / v))


def attach_physical(sel):
    out = []
    for r in sel:
        T = T_HOURS[r["dec"]] / 8760.0
        v, d2 = recover_total_vol(r["model"], r["k"])
        rr = dict(r)
        rr["v"] = v
        rr["d2"] = d2
        rr["T"] = T
        for lam in LAMBDAS:
            rr[f"phys_{lam}"] = physical_prob(d2, v, T, lam)
        out.append(rr)
    return out


# ── forecast-evaluation primitives ───────────────────────────────────────────

def brier(p, y):
    return (np.asarray(p) - np.asarray(y)) ** 2


def daily_mean_lossdiff(rows, fa, fb):
    """Per-day mean Brier loss differential d = L(a) - L(b)."""
    byday = defaultdict(list)
    for r in rows:
        if r.get(fa) is None or r.get(fb) is None:
            continue
        la = (r[fa] - r["outcome"]) ** 2
        lb = (r[fb] - r["outcome"]) ** 2
        byday[r["date"]].append(la - lb)
    days = sorted(byday)
    d = np.array([np.mean(byday[dd]) for dd in days])
    return days, d


def dm_hln(d):
    """
    Diebold-Mariano on day-aggregated loss diffs d (assumed ~iid across days,
    h=1 so no HAC term), with Harvey-Leybourne-Newbold small-sample correction
    and t_{n-1} reference.  d>0 means forecaster A worse than B (higher loss).
    """
    n = len(d)
    if n < 3:
        return None
    dbar = d.mean()
    var = d.var(ddof=1) / n
    if var <= 0:
        return None
    dm = dbar / math.sqrt(var)
    h = 1
    corr = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_c = dm * corr
    p = 2 * (1 - tdist.cdf(abs(dm_c), df=n - 1))
    return dict(n=n, dbar=float(dbar), dm=float(dm), dm_hln=float(dm_c), p=float(p))


def spiegelhalter_z(p, y):
    """Calibration test.  Z = sum (y-p)(1-2p) / sqrt(sum (1-2p)^2 p(1-p)) ~ N(0,1)."""
    p = np.asarray(p, float); y = np.asarray(y, float)
    num = np.sum((y - p) * (1 - 2 * p))
    den = math.sqrt(np.sum((1 - 2 * p) ** 2 * p * (1 - p)))
    if den == 0:
        return None
    z = num / den
    return dict(z=float(z), p=float(2 * (1 - norm.cdf(abs(z)))))


def murphy(p, y, nbins=8):
    """Brier = Reliability - Resolution + Uncertainty (binned)."""
    p = np.asarray(p, float); y = np.asarray(y, float)
    ybar = y.mean()
    unc = ybar * (1 - ybar)
    edges = np.linspace(0, 1, nbins + 1)
    rel = res = 0.0
    for i in range(nbins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & (p < hi) if i < nbins - 1 else (p >= lo) & (p <= hi)
        nk = m.sum()
        if nk == 0:
            continue
        pk = p[m].mean(); ok = y[m].mean()
        rel += nk * (pk - ok) ** 2
        res += nk * (ok - ybar) ** 2
    n = len(y)
    return dict(brier=float(np.mean(brier(p, y))), reliability=float(rel / n),
                resolution=float(res / n), uncertainty=float(unc))


def encompassing(rows, fa="pm", fb="model"):
    """OLS  y = a + b1*fa + b2*fb  with day-clustered robust SE (Liang-Zeger)."""
    X, Y, groups = [], [], []
    for r in rows:
        if r.get(fa) is None or r.get(fb) is None:
            continue
        X.append([1.0, r[fa], r[fb]]); Y.append(r["outcome"]); groups.append(r["date"])
    X = np.asarray(X); Y = np.asarray(Y)
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ Y
    resid = Y - X @ beta
    # cluster by day
    meat = np.zeros((3, 3))
    for g in set(groups):
        idx = [i for i, gg in enumerate(groups) if gg == g]
        Xg = X[idx]; ug = resid[idx]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    G = len(set(groups))
    cov = XtX_inv @ meat @ XtX_inv * (G / (G - 1))
    se = np.sqrt(np.diag(cov))
    return dict(beta=beta.tolist(), se=se.tolist(),
                t=(beta / se).tolist(), names=["const", fa, fb], G=G, n=len(Y))


def loo_day_logit_pool(rows, fa="pm", fb="model"):
    """
    Leave-one-DAY-out: fit logit pool  logit(p) = a*logit(fa)+b*logit(fb)+c
    on all other days, predict held-out day, compare OOS Brier to each venue.
    Returns OOS Brier of {fa, fb, pool}.  Pool beating both => inefficiency.
    """
    def logit(x):
        x = min(max(x, 1e-4), 1 - 1e-4)
        return math.log(x / (1 - x))

    data = [r for r in rows if r.get(fa) is not None and r.get(fb) is not None]
    days = sorted({r["date"] for r in data})
    oos = {fa: [], fb: [], "pool": []}
    for hd in days:
        train = [r for r in data if r["date"] != hd]
        test = [r for r in data if r["date"] == hd]
        if len(train) < 20 or not test:
            continue
        Xtr = np.array([[1.0, logit(r[fa]), logit(r[fb])] for r in train])
        ytr = np.array([r["outcome"] for r in train], float)
        # simple Newton logistic regression
        beta = np.zeros(3)
        for _ in range(50):
            eta = Xtr @ beta
            mu = 1 / (1 + np.exp(-eta))
            W = mu * (1 - mu) + 1e-9
            grad = Xtr.T @ (ytr - mu)
            H = (Xtr * W[:, None]).T @ Xtr + 1e-6 * np.eye(3)
            step = np.linalg.solve(H, grad)
            beta += step
            if np.max(np.abs(step)) < 1e-8:
                break
        for r in test:
            eta = beta @ np.array([1.0, logit(r[fa]), logit(r[fb])])
            pp = 1 / (1 + math.exp(-eta))
            oos[fa].append((r[fa] - r["outcome"]) ** 2)
            oos[fb].append((r[fb] - r["outcome"]) ** 2)
            oos["pool"].append((pp - r["outcome"]) ** 2)
    return {k: (float(np.mean(v)), len(v)) for k, v in oos.items() if v}


# ── 4. power analysis ────────────────────────────────────────────────────────

def power_analysis(d):
    """Given day-level Brier loss-diff sample d, report MDE and n for 1pp edge."""
    n = len(d)
    sd = d.std(ddof=1)
    # MDE at 80% power, two-sided alpha 0.05: ~ 2.8 * sd / sqrt(n)
    mde = 2.8 * sd / math.sqrt(n)
    # n to detect a target mean diff at 80% power
    def n_for(target):
        if target <= 0:
            return float("inf")
        return (2.8 * sd / target) ** 2
    return dict(n_days=n, sd_daily=float(sd), mde_brier=float(mde),
                n_for_0p01_brier=n_for(0.01), n_for_0p005_brier=n_for(0.005))


# ── 5. drift contamination ───────────────────────────────────────────────────

def drift_check(rows):
    """
    Per day: mean loss-diff (PM - model in Brier) vs signed spot move that day.
    We proxy the day's directional surprise by mean(outcome) - mean(pm): if PM
    leaned a direction and the market moved that way, 'skill' is luck.
    Regress daily (Brier_model - Brier_pm) on daily (realized - pm_mean).
    """
    byday = defaultdict(list)
    for r in rows:
        byday[r["date"]].append(r)
    X, Yld = [], []
    for dd, rs in byday.items():
        realized = np.mean([r["outcome"] for r in rs])
        pm_mean = np.mean([r["pm"] for r in rs])
        bp = np.mean([(r["pm"] - r["outcome"]) ** 2 for r in rs])
        bm = np.mean([(r["model"] - r["outcome"]) ** 2 for r in rs])
        X.append(realized - pm_mean)         # directional surprise
        Yld.append(bm - bp)                  # >0 => PM better that day
    X = np.array(X); Yld = np.array(Yld)
    if len(X) < 3:
        return None
    b1, b0 = np.polyfit(X, Yld, 1)
    r = np.corrcoef(X, Yld)[0, 1]
    return dict(slope=float(b1), intercept=float(b0), corr=float(r), n=len(X))


# ── 6. multiple-testing guard (max-|t| sign-flip bootstrap) ──────────────────

def config_grid_maxt(rows, B=2000):
    """
    For a grid of (dec, strike-moneyness bucket), compute the t-stat that PM beats
    model (paired Brier diff, day-clustered via day means), then a sign-flip
    bootstrap of the max |t| to get an FWER-controlled p-value (Romano-Wolf-lite).
    """
    buckets = [("ITM", -10, -0.02), ("ATM", -0.02, 0.02), ("OTM", 0.02, 10)]
    configs = []
    for dec in T_HOURS:
        for name, lo, hi in buckets:
            sub = [r for r in rows if r["dec"] == dec and lo <= r["k"] < hi]
            byday = defaultdict(list)
            for r in sub:
                byday[r["date"]].append((r["pm"] - r["outcome"]) ** 2
                                        - (r["model"] - r["outcome"]) ** 2)
            dd = np.array([np.mean(v) for v in byday.values()]) if byday else np.array([])
            if len(dd) >= 3 and dd.std(ddof=1) > 0:
                tstat = dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))
                configs.append((f"{dec}/{name}", dd, float(tstat)))
    if not configs:
        return []
    # observed max |t|
    obs_max = max(abs(c[2]) for c in configs)
    # sign-flip bootstrap: flip the sign of each day's diff per config
    cnt = 0
    for _ in range(B):
        mx = 0.0
        for _, dd, _ in configs:
            signs = RNG.choice([-1, 1], size=len(dd))
            x = dd * signs
            tb = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if x.std(ddof=1) > 0 else 0
            mx = max(mx, abs(tb))
        if mx >= obs_max:
            cnt += 1
    fwer_p = (cnt + 1) / (B + 1)
    return configs, obs_max, fwer_p


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    rows_all, sel = load_rows()
    sel = attach_physical(sel)
    print(f"Comparable rows (banded, in-smile-range): {len(sel)}")
    days = sorted({r["date"] for r in sel})
    print(f"Independent days: {len(days)}  ({days[0]} .. {days[-1]})\n")

    # ===== 1-2. Risk-neutral vs physical: does the premium explain the lean? =====
    print("=" * 72)
    print("1-2.  RISK-NEUTRAL  vs  PHYSICAL  (does the crypto risk premium explain")
    print("      the 'PM above Deribit' lean, leaving no alpha?)")
    print("=" * 72)
    for dec in T_HOURS:
        s = [r for r in sel if r["dec"] == dec and r["v"]]
        if not s:
            continue
        realized = np.mean([r["outcome"] for r in s])
        pm_m = np.mean([r["pm"] for r in s])
        rn_m = np.mean([r["model"] for r in s])
        print(f"\n  {dec}  (n={len(s)}, horizon {T_HOURS[dec]:.0f}h)")
        print(f"    mean PM={pm_m:.4f}  mean RN(Deribit)={rn_m:.4f}  realized={realized:.4f}")
        print(f"    raw gap  (PM - RN)             = {pm_m - rn_m:+.4f}")
        for lam in LAMBDAS:
            pa = np.mean([r[f"phys_{lam}"] for r in s if r[f"phys_{lam}"] is not None])
            print(f"    phys-adj gap (PM - P_P,lam={lam:.2f}) = {pm_m - pa:+.4f}   "
                  f"(mean P_P={pa:.4f})")

    # ===== 3. Calibration: Spiegelhalter z + Murphy + Brier =====
    print("\n" + "=" * 72)
    print("3.  CALIBRATION  (Spiegelhalter z: |z|>1.96 => miscalibrated)")
    print("=" * 72)
    for dec in T_HOURS:
        s = [r for r in sel if r["dec"] == dec and r["v"]]
        if not s:
            continue
        y = [r["outcome"] for r in s]
        print(f"\n  {dec}  (n={len(s)})")
        for name, key in [("PM", "pm"), ("RN model", "model"),
                          ("Phys lam=0.66", "phys_0.66")]:
            p = [r[key] for r in s if r.get(key) is not None]
            yy = [r["outcome"] for r in s if r.get(key) is not None]
            sp = spiegelhalter_z(p, yy)
            mu = murphy(p, yy)
            if sp:
                print(f"    {name:14s} Brier={mu['brier']:.4f} rel={mu['reliability']:.4f} "
                      f"res={mu['resolution']:.4f}  Spiegel z={sp['z']:+.2f} p={sp['p']:.3f}")

    # ===== DM test PM vs RN model (day-aggregated, HLN) =====
    print("\n" + "=" * 72)
    print("DIEBOLD-MARIANO  PM vs RN model  (Brier, day-aggregated, HLN-corrected)")
    print("  dbar>0 => PM has HIGHER loss (worse); p>0.05 => no skill difference")
    print("=" * 72)
    for dec in T_HOURS:
        s = [r for r in sel if r["dec"] == dec]
        _, d = daily_mean_lossdiff(s, "pm", "model")
        res = dm_hln(d)
        if res:
            print(f"  {dec}: n_days={res['n']}  dbar={res['dbar']:+.5f}  "
                  f"DM_HLN={res['dm_hln']:+.2f}  p={res['p']:.3f}")

    # ===== 4. Encompassing regression =====
    print("\n" + "=" * 72)
    print("4a.  ENCOMPASSING  outcome ~ a + b1*PM + b2*RNmodel  (day-clustered SE)")
    print("     if only one of b1,b2 is significant, that venue encompasses the other")
    print("=" * 72)
    enc = encompassing(sel, "pm", "model")
    for nm, b, se, t in zip(enc["names"], enc["beta"], enc["se"], enc["t"]):
        print(f"    {nm:8s} beta={b:+.3f}  se={se:.3f}  t={t:+.2f}")
    print(f"    (clusters={enc['G']} days, n={enc['n']})")

    # ===== 4b. LOO-day logit pool =====
    print("\n" + "=" * 72)
    print("4b.  LEAVE-ONE-DAY-OUT logit pool  (does a combination beat BOTH OOS?)")
    print("     pool Brier < both venue Briers => neither venue is efficient (alpha)")
    print("=" * 72)
    pool = loo_day_logit_pool(sel, "pm", "model")
    for k, (b, n) in pool.items():
        print(f"    {k:6s} OOS Brier={b:.4f}  (n={n})")
    if "pool" in pool:
        pb = pool["pool"][0]; pmb = pool["pm"][0]; mmb = pool["model"][0]
        verdict = ("POOL BEATS BOTH -> inefficiency" if pb < pmb and pb < mmb
                   else "pool does NOT beat both -> no exploitable inefficiency")
        print(f"    => {verdict}")

    # ===== 5. Power analysis =====
    print("\n" + "=" * 72)
    print("5.  POWER  (can we even detect a 1pp Brier edge with this sample?)")
    print("=" * 72)
    for dec in T_HOURS:
        s = [r for r in sel if r["dec"] == dec]
        _, d = daily_mean_lossdiff(s, "pm", "model")
        if len(d) >= 3:
            pw = power_analysis(d)
            print(f"\n  {dec}: n_days={pw['n_days']}  daily SD={pw['sd_daily']:.4f}")
            print(f"    min detectable Brier edge @80% power = {pw['mde_brier']:.4f}")
            print(f"    days needed to detect 0.01 Brier edge = {pw['n_for_0p01_brier']:.0f}")
            print(f"    days needed to detect 0.005 Brier edge= {pw['n_for_0p005_brier']:.0f}")

    # ===== 6. Drift contamination =====
    print("\n" + "=" * 72)
    print("6.  DRIFT CONTAMINATION  (is apparent skill just a directional move?)")
    print("    slope/corr>0 => PM looks better on days spot moved PM's way (=luck)")
    print("=" * 72)
    for dec in T_HOURS:
        s = [r for r in sel if r["dec"] == dec]
        dc = drift_check(s)
        if dc:
            print(f"  {dec}: corr(dir-surprise, PM-advantage)={dc['corr']:+.2f}  "
                  f"slope={dc['slope']:+.3f}  (n_days={dc['n']})")

    # ===== 7. Multiple-testing guard =====
    print("\n" + "=" * 72)
    print("7.  MULTIPLE-TESTING GUARD  (max-|t| sign-flip bootstrap over config grid)")
    print("    FWER p>0.05 => no config's PM-vs-model difference survives the search")
    print("=" * 72)
    out = config_grid_maxt(sel)
    if out:
        configs, obs_max, fwer_p = out
        for name, dd, tstat in sorted(configs, key=lambda c: -abs(c[2])):
            print(f"    {name:16s} t={tstat:+.2f}  (n_days={len(dd)})")
        print(f"    observed max|t|={obs_max:.2f}  FWER p={fwer_p:.3f}")

    print("\n" + "=" * 72)
    print("DONE.")
    print("=" * 72)


if __name__ == "__main__":
    main()
