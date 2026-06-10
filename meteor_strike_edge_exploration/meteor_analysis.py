"""
meteor_analysis.py — is Polymarket's 2026 meteor-strike ladder mispriced?

Compares, at four impact-energy thresholds (5 / 10 / 100 / 1000 kt), three estimates
of the annual airburst rate:
  1. MARKET   — implied by Polymarket's live YES price (CLOB prices-history), backed
                out as a constant Poisson rate via lambda = -ln(1-p) * 365/days_left.
  2. EMPIRICAL— NASA/CNEOS fireball record (1988-2025), the market's own resolution
                source, with exact Poisson 95% CIs (data-starved at the tail).
  3. MODEL    — Brown et al. (2002) bolide impact-flux POWER LAW  N(>E) = 3.7 * E^-0.9
                (E in kt, N per year, whole Earth). Calibrated on the full size-frequency
                distribution, so it constrains the tail far better than 1-2 direct hits.
                A Brown (2013) post-Chelyabinsk tail-enhancement (~x4 above 100 kt) is
                drawn as a sensitivity.

Outputs two figures + a monthly comparison CSV used by RESULTS.md.

Run:  python3 "meteor_analysis.py"   (from inside this folder; ~30s of HTTP)
"""
import csv
import json
import math
import os
import urllib.request
import datetime as DT

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import chi2

GAMMA = "https://gamma-api.polymarket.com"
CNEOS = "https://ssd-api.jpl.nasa.gov/fireball.api?req-loc=false"
HERE = os.path.dirname(os.path.abspath(__file__))

# threshold (kt) -> (label, polymarket event slug)
LADDER = {
    5:    ("5 kt",   "5kt-meteor-strike-in-2026"),
    10:   ("10 kt",  "major-meteor-strike-10kt-in-2026"),
    100:  ("100 kt", "100kt-meteor-strike-in-2026"),
    1000: ("1 Mt",   "1-megaton-meteor-strike-in-2026"),
}
YEAR = 2026
START = DT.datetime(YEAR, 1, 1, tzinfo=DT.timezone.utc)
END = DT.datetime(YEAR, 12, 31, 23, 59, tzinfo=DT.timezone.utc)
TODAY = DT.datetime(2026, 6, 10, tzinfo=DT.timezone.utc)


def get(url, timeout=90):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ----- Brown power-law model -----------------------------------------------------
def brown2002_rate(E_kt):
    """Cumulative airbursts/yr with impact energy >= E_kt (Brown et al. 2002)."""
    return 3.7 * E_kt ** (-0.90)


def brown2013_rate(E_kt):
    """Same, with a coarse post-Chelyabinsk tail enhancement above ~100 kt."""
    base = brown2002_rate(E_kt)
    return base * np.where(np.asarray(E_kt) >= 100, 4.0, 1.0)


def p_within(lam, ts_from, ts_to=END.timestamp()):
    """P(>=1 event) in the window [ts_from, ts_to] for Poisson rate lam (per yr)."""
    days = max(ts_to - ts_from, 0) / 86400.0
    return 1.0 - math.exp(-lam * days / 365.0)


def pois_ci(k, n_years, conf=0.95):
    """Exact (Garwood) Poisson rate CI for k events over n_years."""
    a = 1 - conf
    lo = chi2.ppf(a / 2, 2 * k) / 2 / n_years if k > 0 else 0.0
    hi = chi2.ppf(1 - a / 2, 2 * (k + 1)) / 2 / n_years
    return lo, hi


# ----- data pulls ----------------------------------------------------------------
def empirical_rates():
    d = get(CNEOS)
    rows = [(int(r[0][:4]), float(r[2])) for r in d["data"] if r[2] is not None]
    n_full = 2025 - 1988 + 1
    out = {}
    for thr in LADDER:
        k = sum(1 for yr, ie in rows if ie >= thr and 1988 <= yr <= 2025)
        lam = k / n_full
        out[thr] = {"k": k, "n": n_full, "lam": lam, "ci": pois_ci(k, n_full)}
    # 2026 YTD max, to confirm nothing has resolved yet
    ytd = max((ie for yr, ie in rows if yr == 2026), default=0.0)
    return out, ytd


def market_history():
    """Daily YES price history per threshold + time-avg implied Poisson rate."""
    out = {}
    for thr, (lab, slug) in LADDER.items():
        e = get(f"{GAMMA}/events/slug/{slug}")
        e = e[0] if isinstance(e, list) else e
        m = e["markets"][0]
        cl = m.get("clobTokenIds")
        cl = json.loads(cl) if isinstance(cl, str) else cl
        h = get(f"https://clob.polymarket.com/prices-history?market={cl[0]}"
                f"&interval=max&fidelity=1440")["history"]
        series = sorted((p["t"], p["p"]) for p in h)
        # back out implied annual rate at each point: lam = -ln(1-p)*365/days_left
        lams = []
        for t, p in series:
            days_left = (END.timestamp() - t) / 86400.0
            if 0 < p < 1 and days_left > 5:
                lams.append(-math.log(1 - p) * 365.0 / days_left)
        out[thr] = {
            "label": lab, "series": series,
            "lam_med": float(np.median(lams)), "lam_std": float(np.std(lams)),
            "last_price": series[-1][1],
        }
    return out


# ----- figures -------------------------------------------------------------------
def fig_timeseries(emp, mkt):
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    grid = np.linspace(START.timestamp(), END.timestamp(), 365)
    gdates = [DT.datetime.fromtimestamp(t, DT.timezone.utc) for t in grid]
    for ax, thr in zip(axes.flat, LADDER):
        lab = mkt[thr]["label"]
        # fair-value decay curves (full year, no event)
        fair_model = [p_within(brown2002_rate(thr), t) * 100 for t in grid]
        fair_emp = [p_within(emp[thr]["lam"], t) * 100 for t in grid]
        ax.plot(gdates, fair_model, "--", color="#1f77b4", lw=2,
                label="Brown 2002 model (fair)")
        ax.plot(gdates, fair_emp, ":", color="#2ca02c", lw=2,
                label="CNEOS empirical (fair)")
        # market price
        s = mkt[thr]["series"]
        mdates = [DT.datetime.fromtimestamp(t, DT.timezone.utc) for t, _ in s]
        mvals = [p * 100 for _, p in s]
        ax.plot(mdates, mvals, "-", color="#d62728", lw=2.2, label="Polymarket YES")
        ax.axvline(TODAY, color="grey", ls="-", lw=0.8, alpha=0.6)
        ax.set_title(f"{lab} threshold", fontsize=11, weight="bold")
        ax.set_ylabel("implied P(strike) %")
        ax.grid(alpha=0.25)
        ax.set_ylim(bottom=0)
    axes.flat[0].legend(fontsize=8, loc="upper right")
    fig.suptitle("2026 meteor markets: Polymarket price vs base-rate fair value "
                 "(the time factor)\nfair value decays as the year passes with no "
                 "qualifying event; grey line = today (Jun 10)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = os.path.join(HERE, "fig_timeseries.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def fig_flux_ladder(emp, mkt):
    fig, ax = plt.subplots(figsize=(10, 7))
    E = np.logspace(0, 3.5, 200)
    ax.plot(E, brown2002_rate(E), "-", color="#1f77b4", lw=2.2,
            label="Brown 2002 power law  N=3.7·E$^{-0.9}$")
    Et = E[E >= 100]
    ax.plot(Et, brown2013_rate(Et), "--", color="#9467bd", lw=1.8,
            label="Brown 2013 tail (~×4, post-Chelyabinsk)")
    thrs = sorted(LADDER)
    # empirical with asymmetric Poisson CI
    le = [emp[t]["lam"] for t in thrs]
    lo = [max(emp[t]["lam"] - emp[t]["ci"][0], 1e-4) for t in thrs]
    hi = [emp[t]["ci"][1] - emp[t]["lam"] for t in thrs]
    ax.errorbar(thrs, [max(x, 8e-4) for x in le], yerr=[lo, hi], fmt="o",
                color="#2ca02c", ms=8, capsize=5, label="CNEOS empirical (95% CI)")
    # market-implied
    lm = [mkt[t]["lam_med"] for t in thrs]
    ax.scatter(thrs, lm, marker="D", s=90, color="#d62728", zorder=5,
               label="Polymarket-implied rate")
    for t in thrs:
        ax.annotate(mkt[t]["label"], (t, mkt[t]["lam_med"]),
                    textcoords="offset points", xytext=(8, 6), fontsize=9)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("impact energy threshold E (kt TNT)")
    ax.set_ylabel("annual rate of airbursts ≥ E  (per year)")
    ax.set_title("Flux ladder: market-implied rate vs physics vs the resolution data\n"
                 "market BELOW the line = YES underpriced; ABOVE = overpriced")
    ax.grid(alpha=0.25, which="both")
    ax.legend(fontsize=9)
    fig.tight_layout()
    path = os.path.join(HERE, "fig_flux_ladder.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def write_csv(emp, mkt):
    path = os.path.join(HERE, "comparison.csv")
    days_left = (END.timestamp() - TODAY.timestamp()) / 86400.0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["threshold", "market_YES_now", "market_rate/yr",
                    "empirical_rate/yr", "emp_CI_lo", "emp_CI_hi",
                    "model_brown2002_rate/yr", "model_fair_YES_now",
                    "verdict"])
        for thr in sorted(LADDER):
            mr, er = mkt[thr]["lam_med"], emp[thr]["lam"]
            lo, hi = emp[thr]["ci"]
            mdl = brown2002_rate(thr)
            model_fair = p_within(mdl, TODAY.timestamp())
            # verdict: compare market price to model fair value now
            diff = mkt[thr]["last_price"] - model_fair
            verdict = ("market OVERprices vs model" if diff > 0.02 else
                       "market UNDERprices vs model" if diff < -0.02 else
                       "~fair vs model")
            w.writerow([mkt[thr]["label"], round(mkt[thr]["last_price"], 3),
                        round(mr, 4), round(er, 4), round(lo, 4), round(hi, 4),
                        round(mdl, 4), round(model_fair, 4), verdict])
    return path


def main():
    print("Fetching CNEOS empirical record...")
    emp, ytd = empirical_rates()
    print(f"  2026 YTD max airburst: {ytd} kt (nothing has resolved YES)")
    print("Fetching Polymarket price histories...")
    mkt = market_history()
    print("\n  thr |  mkt YES | mkt rate | emp rate (CI)          | Brown2002 | model fair now")
    for thr in sorted(LADDER):
        lo, hi = emp[thr]["ci"]
        print(f"  {mkt[thr]['label']:>5} | {mkt[thr]['last_price']:7.1%} | "
              f"{mkt[thr]['lam_med']:7.3f}  | {emp[thr]['lam']:.3f} "
              f"[{lo:.3f},{hi:.3f}] | {brown2002_rate(thr):8.4f}  | "
              f"{p_within(brown2002_rate(thr), TODAY.timestamp()):6.1%}")
    p1 = fig_timeseries(emp, mkt)
    p2 = fig_flux_ladder(emp, mkt)
    p3 = write_csv(emp, mkt)
    print(f"\nWrote:\n  {p1}\n  {p2}\n  {p3}")


if __name__ == "__main__":
    main()
