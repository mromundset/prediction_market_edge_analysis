"""
backtest.py — strategy A1 backtest: Polymarket daily "BTC/ETH above $K at noon ET"
digitals vs Deribit options-implied probability, over the daily product's full history
(2026-05-22 .. 2026-06-10).

Per (event-date, decision-time):
  spot   = Binance 1m close at decision (the index PM resolves on)
  smile  = per-expiry IV(k), k = ln(K/S), fitted to Deribit trades within ±90 min
  model  = N(d2), with total-variance interpolation between the two Deribit expiries
           bracketing PM's 16:00Z resolution (20h horizon), or flat extrapolation of the
           next expiry (6h horizon — flagged 'extrap_T')
  pm     = CLOB price nearest decision (±35 min)

Rule: |pm − model| > threshold → buy the cheap side at mid + half-spread + taker fee
      fee = 0.07 · c · (1−c) per share (crypto feeRate, current schedule)
Outputs: trade table CSV, summary stats by config, calibration (Brier), figures.
"""
import json, math, os, datetime as DT
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_cache")
CURS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
FEE_RATE = 0.07            # crypto taker feeRate: fee/share = rate · c · (1−c)
PM_BAND = (0.03, 0.97)     # only trade quotes inside this band
DEC_LABELS = ["D-1_20Z", "D_10Z"]


def load(name):
    p = os.path.join(CACHE, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def parse_expiry(tok):
    return DT.datetime.strptime(tok, "%d%b%y").replace(
        hour=8, tzinfo=DT.timezone.utc)


def fit_smile(trades, dec_ms, spot):
    """trades: [{'i','ts','iv','S','amt'}] one expiry -> callable iv(K), plus k-range."""
    best = {}                                    # strike -> (dt_ms, iv)
    for t in trades:
        K = float(t["i"].split("-")[2])
        dt = abs(t["ts"] - dec_ms)
        if K not in best or dt < best[K][0]:
            best[K] = (dt, t["iv"] / 100.0)
    if not best:
        return None, None
    ks = np.array([math.log(K / spot) for K in best])
    ivs = np.array([v[1] for v in best.values()])
    order = np.argsort(ks)
    ks, ivs = ks[order], ivs[order]
    if len(ks) >= 4:
        coef = np.polyfit(ks, ivs, 2)
    elif len(ks) >= 2:
        coef = np.polyfit(ks, ivs, 1)
    else:
        coef = np.array([ivs[0]])
    def iv_at(K):
        k = math.log(K / spot)
        kc = min(max(k, ks[0] - 0.01), ks[-1] + 0.01)   # clamp: no wild wing extrapolation
        return float(np.polyval(coef, kc))
    return iv_at, (float(ks[0]), float(ks[-1]))


def build_rows():
    rows = []
    for cur, sym in CURS.items():
        events = load(f"events_{cur}.json") or []
        for e in events:
            d = DT.date.fromisoformat(e["date"])
            res = DT.datetime(d.year, d.month, d.day, 16, 0, tzinfo=DT.timezone.utc)
            for label in DEC_LABELS:
                if label == "D-1_20Z":
                    dec = DT.datetime(d.year, d.month, d.day, 20, 0,
                                      tzinfo=DT.timezone.utc) - DT.timedelta(days=1)
                else:
                    dec = DT.datetime(d.year, d.month, d.day, 10, 0,
                                      tzinfo=DT.timezone.utc)
                spot = load(f"spot_{sym}_{int(dec.timestamp())}.json")
                trades = load(f"deribit_{cur}_{e['date']}_{label}.json")
                if not (spot and trades):
                    continue
                dec_ms = int(dec.timestamp() * 1000)
                # group trades by expiry; keep the two bracketing daily expiries
                byexp = defaultdict(list)
                for t in trades:
                    byexp[t["i"].split("-")[1]].append(t)
                smiles = {}
                for exp_tok, tl in byexp.items():
                    exp_dt = parse_expiry(exp_tok)
                    h_away = (exp_dt - dec).total_seconds() / 3600
                    if 0 < h_away < 60:                  # within 2.5 days
                        iv_fn, krange = fit_smile(tl, dec_ms, spot)
                        if iv_fn:
                            smiles[exp_tok] = (exp_dt, iv_fn, krange, len(tl))
                if not smiles:
                    continue
                # expiries strictly before/after PM resolution
                pre, post = [], []
                for k, (et_dt, f, kr, ntr) in smiles.items():
                    (pre if et_dt < res else post).append((et_dt, f, kr, ntr))
                pre.sort(key=lambda x: x[0]); post.sort(key=lambda x: x[0])
                T_pm = (res - dec).total_seconds() / (365 * 86400)

                for m in e["markets"]:
                    K = m["strike"]
                    hist = load(f"clob_{m['tok'][:24]}.json")
                    if not hist:
                        continue
                    # PM price nearest decision within ±35 min
                    cands = [(abs(h["t"] - dec.timestamp()), h["p"]) for h in hist
                             if abs(h["t"] - dec.timestamp()) <= 2100]
                    if not cands:
                        continue
                    pm = min(cands)[1]
                    # model probability
                    extrap_T = False
                    if pre and post:                     # interpolate total variance
                        (t1, f1, kr1, _), (t2, f2, kr2, _) = pre[-1], post[0]
                        Ta = (t1 - dec).total_seconds() / (365 * 86400)
                        Tb = (t2 - dec).total_seconds() / (365 * 86400)
                        va = f1(K) ** 2 * Ta
                        vb = f2(K) ** 2 * Tb
                        w = (T_pm - Ta) / (Tb - Ta)
                        var_pm = va + w * (vb - va)
                        krange = kr2
                    elif post:                           # flat-vol extrapolation
                        t2, f2, krange, _ = post[0]
                        var_pm = f2(K) ** 2 * T_pm
                        extrap_T = True
                    else:
                        continue
                    if var_pm <= 0:
                        continue
                    sig = math.sqrt(var_pm / T_pm)
                    d2 = (math.log(spot / K) - 0.5 * sig * sig * T_pm) / (sig * math.sqrt(T_pm))
                    p_model = float(norm.cdf(d2))
                    k = math.log(K / spot)
                    in_range = krange[0] - 0.005 <= k <= krange[1] + 0.005
                    rows.append({
                        "cur": cur, "date": e["date"], "dec": label,
                        "K": K, "S": spot, "k": k, "pm": pm, "model": p_model,
                        "outcome": m["outcome"], "extrap_T": extrap_T,
                        "in_smile_range": in_range,
                    })
    return rows


def run_config(rows, thr, hs, dec_label, require_range=True):
    trades = []
    for r in rows:
        if r["dec"] != dec_label:
            continue
        if not (PM_BAND[0] <= r["pm"] <= PM_BAND[1]):
            continue
        if require_range and not r["in_smile_range"]:
            continue
        gap = r["pm"] - r["model"]
        if abs(gap) <= thr:
            continue
        if gap > 0:        # PM too high -> buy NO
            c = (1 - r["pm"]) + hs
            win = r["outcome"] == 0
        else:              # PM too low -> buy YES
            c = r["pm"] + hs
            win = r["outcome"] == 1
        if not 0 < c < 1:
            continue
        cost = c + FEE_RATE * c * (1 - c)
        ret = ((1.0 if win else 0.0) - cost) / cost
        trades.append({**r, "side": "NO" if gap > 0 else "YES", "cost": cost,
                       "win": win, "ret": ret, "gap": gap})
    return trades


def summarize(trades, days_in_period):
    """Fixed-stake accounting: 1 unit per trade; bankroll = max concurrent daily
    deployment. Reports t-stat of per-trade returns and annualized return on the
    bankroll actually required."""
    if not trades:
        return dict(n=0)
    rets = np.array([t["ret"] for t in trades])
    bydate = defaultdict(list)
    for t in trades:
        bydate[t["date"]].append(t["ret"])
    daily_pnl = [float(np.sum(v)) for v in bydate.values()]   # units of stake
    bankroll = max(len(v) for v in bydate.values())           # max units at risk in a day
    total_pnl = float(np.sum(rets))
    period_ret = total_pnl / bankroll
    ann = (1 + period_ret) ** (365 / days_in_period) - 1 if period_ret > -1 else -1
    t_stat = float(rets.mean() / (rets.std(ddof=1) / math.sqrt(len(rets)))) if len(rets) > 2 else 0.0
    n_no = sum(1 for t in trades if t["side"] == "NO")
    hit_no = (float(np.mean([t["win"] for t in trades if t["side"] == "NO"]))
              if n_no else float("nan"))
    hit_yes = (float(np.mean([t["win"] for t in trades if t["side"] == "YES"]))
               if n_no < len(trades) else float("nan"))
    return dict(n=len(trades), hit=float(np.mean([t["win"] for t in trades])),
                mean_ret=float(rets.mean()), t=t_stat, bankroll=bankroll,
                period_ret=period_ret, ann=ann, n_no=n_no,
                hit_no=hit_no, hit_yes=hit_yes,
                worst_day=float(np.min(daily_pnl)), best_day=float(np.max(daily_pnl)))


def brier(rows, key, dec_label):
    sel = [r for r in rows if r["dec"] == dec_label and
           PM_BAND[0] <= r["pm"] <= PM_BAND[1] and r["in_smile_range"]]
    if not sel:
        return None, 0
    return float(np.mean([(r[key] - r["outcome"]) ** 2 for r in sel])), len(sel)


def main():
    rows = build_rows()
    print(f"comparable (PM, model) observations: {len(rows)}")
    with open(os.path.join(HERE, "rows.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f)

    dates = sorted({r["date"] for r in rows})
    days_in_period = (DT.date.fromisoformat(dates[-1]) -
                      DT.date.fromisoformat(dates[0])).days + 1
    print(f"period: {dates[0]} .. {dates[-1]} ({days_in_period} days)\n")

    # calibration first — is the model actually sharper than PM?
    print("=== CALIBRATION (Brier, lower=better) ===")
    for lab in DEC_LABELS:
        bp, n = brier(rows, "pm", lab)
        bm, _ = brier(rows, "model", lab)
        if bp is not None:
            print(f"  {lab:9} n={n:4d}  Brier(PM)={bp:.4f}  Brier(model)={bm:.4f}  "
                  f"{'MODEL sharper' if bm < bp else 'PM sharper'}")

    # filter-stage diagnostics
    for lab in DEC_LABELS:
        a = [r for r in rows if r["dec"] == lab]
        b = [r for r in a if PM_BAND[0] <= r["pm"] <= PM_BAND[1]]
        c = [r for r in b if r["in_smile_range"]]
        print(f"  {lab}: raw={len(a)}  in PM band={len(b)}  in smile range={len(c)}")

    print("\n=== BACKTEST GRID (net of fee; fixed stake/trade; bankroll = max daily units) ===")
    print(f"{'dec':9} {'thr':>5} {'hs':>5} | {'n':>4} {'hit':>6} {'hitNO':>6} {'mean/trade':>10} "
          f"{'t':>5} {'period':>8} {'annualized':>10}")
    results = {}
    for lab in DEC_LABELS:
        for thr in (0.02, 0.03, 0.05):
            for hs in (0.005, 0.01, 0.02):
                tr = run_config(rows, thr, hs, lab)
                s = summarize(tr, days_in_period)
                results[(lab, thr, hs)] = (tr, s)
                if s["n"]:
                    print(f"{lab:9} {thr:5.2f} {hs:5.3f} | {s['n']:4d} {s['hit']:6.1%} "
                          f"{s['hit_no']:6.1%} {s['mean_ret']:10.2%} {s['t']:5.2f} "
                          f"{s['period_ret']:8.1%} {s['ann']:10.1%}")

    # gap-bucket honesty table: when PM-model gap is g, who was right?
    print("\n=== GAP BUCKETS (D-1_20Z, in-range, banded): realized vs PM vs model ===")
    sel = [r for r in rows if r["dec"] == "D-1_20Z" and r["in_smile_range"]
           and PM_BAND[0] <= r["pm"] <= PM_BAND[1]]
    buckets = [(-1, -0.05), (-0.05, -0.02), (-0.02, 0.02), (0.02, 0.05), (0.05, 1)]
    for lo, hi in buckets:
        b = [r for r in sel if lo <= r["pm"] - r["model"] < hi]
        if b:
            print(f"  gap[{lo:+.2f},{hi:+.2f}): n={len(b):4d}  PM={np.mean([r['pm'] for r in b]):.3f}  "
                  f"model={np.mean([r['model'] for r in b]):.3f}  "
                  f"realized={np.mean([r['outcome'] for r in b]):.3f}")

    # drift contamination: over the window, what did spot do and who was "rich" ex post?
    print("\n=== DRIFT CHECK (all in-range, banded rows) ===")
    for lab in DEC_LABELS:
        sel2 = [r for r in rows if r["dec"] == lab and r["in_smile_range"]
                and PM_BAND[0] <= r["pm"] <= PM_BAND[1]]
        if sel2:
            print(f"  {lab}: mean PM={np.mean([r['pm'] for r in sel2]):.3f}  "
                  f"mean model={np.mean([r['model'] for r in sel2]):.3f}  "
                  f"realized={np.mean([r['outcome'] for r in sel2]):.3f}  (n={len(sel2)})")

    # ---- figures ----
    base = results[("D-1_20Z", 0.03, 0.01)][0]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    ax = axes[0]
    sel0 = [r for r in rows if r["dec"] == "D-1_20Z" and r["in_smile_range"]]
    won = [r for r in sel0 if r["outcome"] == 1]
    lost = [r for r in sel0 if r["outcome"] == 0]
    ax.scatter([r["model"] for r in won], [r["pm"] for r in won], s=18, c="#2ca02c",
               alpha=0.6, label="resolved YES")
    ax.scatter([r["model"] for r in lost], [r["pm"] for r in lost], s=18, c="#d62728",
               alpha=0.6, label="resolved NO")
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlabel("Deribit options-implied P(YES)"); ax.set_ylabel("Polymarket price")
    ax.set_title("PM vs options-implied, 20h before resolution\n(points above line = PM rich)")
    ax.legend(fontsize=8); ax.grid(alpha=0.25)

    ax = axes[1]
    for (lab, thr, hs), color, name in [(("D-1_20Z", 0.02, 0.01), "#1f77b4", "20h, thr 2pp"),
                                        (("D-1_20Z", 0.03, 0.01), "#ff7f0e", "20h, thr 3pp"),
                                        (("D_10Z", 0.03, 0.01), "#2ca02c", "6h, thr 3pp")]:
        tr, s = results[(lab, thr, hs)]
        if not tr:
            continue
        bydate = defaultdict(list)
        for t in tr:
            bydate[t["date"]].append(t["ret"])
        ds = sorted(bydate)
        eq = np.cumsum([float(np.sum(bydate[d])) for d in ds]) / s["bankroll"] * 100
        ax.plot([DT.date.fromisoformat(d) for d in ds], eq,
                marker="o", ms=3, color=color, label=f"{name} (hs 1c)")
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_ylabel("cumulative return on bankroll %")
    ax.set_title("Equity (fixed stake/trade, net of fee+spread)")
    ax.legend(fontsize=8); ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_backtest.png"), dpi=130)
    plt.close(fig)

    # trade table CSV
    import csv
    with open(os.path.join(HERE, "trades_base.csv"), "w", newline="", encoding="utf-8") as f:
        if base:
            w = csv.DictWriter(f, fieldnames=list(base[0].keys()))
            w.writeheader(); w.writerows(base)
    print(f"\nWrote rows.json, trades_base.csv, fig_backtest.png")


if __name__ == "__main__":
    main()
