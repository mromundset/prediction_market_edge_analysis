"""
scan.py — D10: crypto ladder monotonicity + RND shape scan.

Strategy D10 hypothesis: violations of the no-arbitrage conditions within
Polymarket's daily "BTC/ETH above $K" ladders are exploitable.

Correctness note on the "butterfly" condition
----------------------------------------------
The original D10 brainstorm claimed "butterfly violations are model-free arb."
This is TRUE for vanilla calls (d²C/dK² ≥ 0 is required by no-arb) but FALSE
for binary/digital options. For a digital call D(K) = P(S > K):

  dD/dK  = -f(K) ≤ 0              (density ≥ 0 → D is monotone decreasing)
  d²D/dK² = -f'(K)                 (can be + or − with no arb implication)

The discrete butterfly on digitals:
  P(K-Δ) - 2P(K) + P(K+Δ) ≈ Δ² · d²D/dK² = -Δ² · f'(K)

This is ≤ 0 near the mode (density still rising) and ≥ 0 in the upper tail
(density falling). BOTH signs are normal for a unimodal distribution; NEITHER
is an arbitrage violation. The ONLY model-free no-arb condition for digital
options is MONOTONICITY: ask(K1) ≥ bid(K2) for all K1 < K2.

Three tests in this script
--------------------------
  Part 1  Historical mid-price monotonicity using the A1 CLOB cache.
          (10-min mid prices, not ask/bid; gives frequency + persistence of
          violations but cannot confirm executability.)
  Part 2  Live order-book monotonicity for currently active ladders.
          (Checks the actual executable condition: ask(K1) < bid(K2).)
  Part 3  PM-implied RND shape vs Deribit at the D-1_20Z decision time.
          (Even if LEVEL is ~same, does shape differ systematically?)

Run from inside this folder:
  python3 scan.py
"""

import json, os, re, sys, time, math, datetime as DT
sys.stdout.reconfigure(encoding="utf-8")
from collections import defaultdict
import urllib.request

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import norm

HERE  = os.path.dirname(os.path.abspath(__file__))
A1    = os.path.join(HERE, "..", "crypto_deribit_edge_exploration", "data_cache")
GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"
FEE   = 0.07          # crypto taker feeRate: fee/share = rate · p · (1−p)
MULTI_STRIKES_TAG = 102516   # Gamma tag id for "multi-strikes" ladder events


# ──────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────

def get(u, t=40, retries=3):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(
                u, headers={"Accept": "application/json",
                            "User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=t) as r:
                return json.load(r)
        except Exception as e:
            last = e; time.sleep(1.0)
    raise last


def post_json(u, body, t=40, retries=3):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(
                u, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=t) as r:
                return json.load(r)
        except Exception as e:
            last = e; time.sleep(1.0)
    raise last


def a1_load(name):
    p = os.path.join(A1, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def best_quote(book, side):
    """(price, size) at the top of the book. asks: lowest; bids: highest."""
    lv = book.get(side) or []
    if not lv:
        return None, 0.0
    b = (min if side == "asks" else max)(lv, key=lambda x: float(x["price"]))
    return float(b["price"]), float(b["size"])


def parse_strike(question):
    # Capture integer or decimal: "$1.25", "$62,000", "$2.00"
    m = re.search(r"\$([0-9,]+(?:\.[0-9]+)?)", question)
    return float(m.group(1).replace(",", "")) if m else None


# ──────────────────────────────────────────────────────────────
# Part 1 — Historical mid-price monotonicity (A1 cache)
# ──────────────────────────────────────────────────────────────

def part1_historical():
    print("\n=== PART 1: Historical mid-price monotonicity ===")
    print("    Source: A1 CLOB cache (10-min mid prices, D-1 18Z to D 16Z)")

    pair_checks = 0
    violations  = []   # list of dicts
    snap_count  = 0

    for cur in ["BTC", "ETH"]:
        events = a1_load(f"events_{cur}.json") or []
        if not events:
            print(f"  No events_{cur}.json found, skipping.")
            continue

        for e in events:
            markets = sorted(e["markets"], key=lambda m: m["strike"])
            if len(markets) < 2:
                continue

            # Load CLOB mid-price history for each strike
            hists = {}
            for m in markets:
                h = a1_load(f"clob_{m['tok'][:24]}.json")
                if h:
                    hists[m["strike"]] = {entry["t"]: entry["p"] for entry in h}

            strikes = sorted(hists)
            if len(strikes) < 2:
                continue

            # Union of all timestamps across strikes
            all_ts = sorted(set(ts for h in hists.values() for ts in h))

            for ts in all_ts:
                snap = {K: hists[K][ts] for K in strikes if ts in hists[K]}
                if len(snap) < 2:
                    continue
                snap_count += 1
                ks = sorted(snap)
                for i in range(len(ks) - 1):
                    K1, K2 = ks[i], ks[i + 1]
                    p1, p2 = snap[K1], snap[K2]
                    pair_checks += 1
                    if p1 < p2:   # lower strike priced BELOW higher strike
                        violations.append({
                            "cur": cur, "date": e["date"], "ts": ts,
                            "K1": K1, "K2": K2, "p1": p1, "p2": p2,
                            "gap": p2 - p1,
                        })

    vio_rate = len(violations) / pair_checks if pair_checks else 0
    print(f"  Events processed: {sum(1 for cur in ['BTC','ETH'] for _ in (a1_load(f'events_{cur}.json') or []))}")
    print(f"  Multi-strike snapshots: {snap_count}   Strike-pair checks: {pair_checks}")
    print(f"  Mid-price violations: {len(violations)}  ({vio_rate:.3%} of pair-snapshots)")

    if violations:
        gaps = [v["gap"] for v in violations]
        print(f"  Gap dist: min={min(gaps):.4f}  p50={np.median(gaps):.4f}"
              f"  p90={np.percentile(gaps,90):.4f}  max={max(gaps):.4f}")

        # Persistence: how many (event,K1,K2) pairs violated at ≥2 consecutive snapshots?
        by_pair = defaultdict(list)
        for v in violations:
            by_pair[(v["cur"], v["date"], v["K1"], v["K2"])].append(v["ts"])

        # Sort timestamps and look for consecutive gaps ≤ 700 s (the 10-min fidelity)
        multi = 0
        for ts_list in by_pair.values():
            ts_list.sort()
            for i in range(len(ts_list) - 1):
                if ts_list[i + 1] - ts_list[i] <= 700:   # consecutive 10-min snapshots
                    multi += 1
                    break

        print(f"  Distinct (event,K1,K2) pairs ever violated: {len(by_pair)}")
        print(f"  Violated at ≥2 consecutive snapshots (>10 min, actionable at slow speed): {multi}")

        print(f"\n  Top 5 largest violations:")
        for v in sorted(violations, key=lambda x: -x["gap"])[:5]:
            dt = DT.datetime.fromtimestamp(v["ts"], tz=DT.timezone.utc)
            print(f"    {v['cur']} {v['date']}  K={v['K1']:.0f}→{v['K2']:.0f}"
                  f"  p={v['p1']:.4f} < {v['p2']:.4f}  gap={v['gap']:.4f}  @{dt.strftime('%H:%MZ')}")

    return violations, pair_checks, snap_count


# ──────────────────────────────────────────────────────────────
# Part 2 — Live order-book monotonicity
# ──────────────────────────────────────────────────────────────

def part2_live():
    print("\n=== PART 2: Live order-book monotonicity ===")
    print("    Source: Gamma events API + CLOB /books (live)")

    # Fetch active multi-strikes events
    events = []
    try:
        offset = 0
        while True:
            r = get(f"{GAMMA}/events?active=true&closed=false"
                    f"&tag_id={MULTI_STRIKES_TAG}&limit=100&offset={offset}")
            if not r:
                break
            events.extend(r)
            if len(r) < 100:
                break
            offset += 100
            time.sleep(0.15)
    except Exception as ex:
        print(f"  Could not fetch events: {ex}")
        return []

    # Filter to crypto price ladders
    crypto = [e for e in events if any(
        c in (e.get("title", "") + e.get("slug", "")).lower()
        for c in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp"]
    )]
    print(f"  Total multi-strikes events found: {len(events)},  crypto: {len(crypto)}")

    total_pair_checks = 0
    book_violations   = 0   # executable: ask(K1) < bid(K2) for K1 < K2
    mid_violations    = 0
    events_scanned    = 0
    live_ladders      = []

    for e in crypto[:60]:
        markets = e.get("markets", [])
        legs = []
        for m in markets:
            s = parse_strike(m.get("question", ""))
            if s is None:
                continue
            cl = m.get("clobTokenIds")
            cl = json.loads(cl) if isinstance(cl, str) else cl
            if not cl:
                continue
            pr = m.get("outcomePrices")
            pr = json.loads(pr) if isinstance(pr, str) else (pr or [])
            mid = float(pr[0]) if pr else None
            legs.append({"K": s, "tok": cl[0], "mid": mid})

        if len(legs) < 3:
            continue

        legs.sort(key=lambda x: x["K"])
        toks = [lg["tok"] for lg in legs]

        try:
            books = post_json(f"{CLOB}/books", [{"token_id": t} for t in toks])
        except Exception:
            continue

        bk = {b.get("asset_id"): b for b in books}
        for lg in legs:
            bke = bk.get(lg["tok"], {})
            lg["ask"], lg["ask_sz"] = best_quote(bke, "asks")
            lg["bid"], lg["bid_sz"] = best_quote(bke, "bids")

        event_vios = []
        for i in range(len(legs) - 1):
            l1, l2 = legs[i], legs[i + 1]
            if l1["K"] >= l2["K"]:   # duplicate strike — skip
                continue
            total_pair_checks += 1

            # ── The actual no-arb condition ──────────────────────────────────
            # Ask(K1) < bid(K2) for K1 < K2 means: buy YES@K1 (costs ask(K1)),
            # sell YES@K2 (receive bid(K2)). Payoffs in all outcomes ≥ 0:
            #   S < K1:        long K1 = 0,  short K2 = 0.   Net initial: bid-ask > 0
            #   K1 ≤ S < K2:   long K1 = 1,  short K2 = 0.   Even better
            #   S ≥ K2:        long K1 = 1,  short K2 = -1.  Net: bid-ask > 0
            if l1["ask"] is not None and l2["bid"] is not None:
                gross = l2["bid"] - l1["ask"]
                if gross > 0:
                    book_violations += 1
                    fee1 = FEE * l1["ask"] * (1 - l1["ask"])
                    fee2 = FEE * l2["bid"] * (1 - l2["bid"])
                    net  = gross - fee1 - fee2
                    event_vios.append({
                        "K1": l1["K"], "K2": l2["K"],
                        "ask_K1": l1["ask"], "bid_K2": l2["bid"],
                        "gross": gross, "net": net,
                    })

            # Mid-price check (informational — not executable)
            if l1["mid"] is not None and l2["mid"] is not None:
                if l1["mid"] < l2["mid"]:
                    mid_violations += 1

        live_ladders.append({
            "title": e.get("title", "")[:60],
            "slug":  e.get("slug", ""),
            "legs":  legs,
            "vios":  event_vios,
        })
        events_scanned += 1
        time.sleep(0.08)

    print(f"  Events scanned: {events_scanned}")
    print(f"  Strike-pair checks: {total_pair_checks}")
    print(f"  Executable arb violations ask(K1)<bid(K2): {book_violations}")
    print(f"  Mid-price violations (informational): {mid_violations}")

    if book_violations:
        for ev in live_ladders:
            for v in ev["vios"]:
                print(f"  ARB: {ev['title'][:40]}  K={v['K1']}→{v['K2']}"
                      f"  ask={v['ask_K1']:.3f}  bid={v['bid_K2']:.3f}"
                      f"  gross={v['gross']:.4f}  net={v['net']:.4f}")

    return live_ladders


# ──────────────────────────────────────────────────────────────
# Part 3 — PM-implied RND shape vs Deribit
# ──────────────────────────────────────────────────────────────

def parse_expiry(tok):
    return DT.datetime.strptime(tok, "%d%b%y").replace(
        hour=8, tzinfo=DT.timezone.utc)


def fit_smile(trades, dec_ms, spot):
    """Quadratic polynomial smile fit (same as A1 backtest.py)."""
    best_iv = {}
    for t in trades:
        K   = float(t["i"].split("-")[2])
        dt  = abs(t["ts"] - dec_ms)
        if K not in best_iv or dt < best_iv[K][0]:
            best_iv[K] = (dt, t["iv"] / 100.0)
    if not best_iv:
        return None, None
    ks  = np.array([math.log(K / spot) for K in best_iv])
    ivs = np.array([v[1] for v in best_iv.values()])
    order = np.argsort(ks)
    ks, ivs = ks[order], ivs[order]
    deg  = min(2, len(ks) - 1)
    coef = np.polyfit(ks, ivs, deg)

    def iv_at(K):
        k  = math.log(K / spot)
        kc = min(max(k, ks[0] - 0.01), ks[-1] + 0.01)
        return float(np.polyval(coef, kc))

    return iv_at, (float(ks[0]), float(ks[-1]))


def model_prob(iv_fn, K, S, T_dec_to_res, T_dec_to_expA, T_dec_to_expB,
               iv_fnA, iv_fnB):
    """
    Total-variance interpolation between two Deribit expiries (same as A1).
    Returns N(d2) probability = P(S > K at PM resolution time).
    """
    va = iv_fnA(K) ** 2 * T_dec_to_expA
    vb = iv_fnB(K) ** 2 * T_dec_to_expB
    w  = (T_dec_to_res - T_dec_to_expA) / (T_dec_to_expB - T_dec_to_expA)
    var_pm = va + w * (vb - va)
    if var_pm <= 0:
        return None
    sig = math.sqrt(var_pm / T_dec_to_res)
    d2  = (math.log(S / K) - 0.5 * sig ** 2 * T_dec_to_res) / (sig * math.sqrt(T_dec_to_res))
    return float(norm.cdf(d2))


def part3_rnd_shape():
    print("\n=== PART 3: RND shape comparison (PM vs Deribit) ===")
    print("    Decision time: D-1_20Z  (20h before PM resolution)")

    sym_map    = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
    rnd_rows   = []   # per-strike-bucket
    events_ok  = 0

    for cur, sym in sym_map.items():
        events = a1_load(f"events_{cur}.json") or []
        for e in events:
            d   = DT.date.fromisoformat(e["date"])
            res = DT.datetime(d.year, d.month, d.day, 16, 0, tzinfo=DT.timezone.utc)
            dec = (DT.datetime(d.year, d.month, d.day, 20, 0, tzinfo=DT.timezone.utc)
                   - DT.timedelta(days=1))
            dec_ms = int(dec.timestamp() * 1000)
            T_pm   = (res - dec).total_seconds() / (365 * 86400)

            spot   = a1_load(f"spot_{sym}_{int(dec.timestamp())}.json")
            trades = a1_load(f"deribit_{cur}_{e['date']}_D-1_20Z.json")
            if not (spot and trades):
                continue

            # Group Deribit trades by expiry; find the two bracketing PM resolution
            byexp = defaultdict(list)
            for t in trades:
                byexp[t["i"].split("-")[1]].append(t)

            smiles = {}
            for exp_tok, tl in byexp.items():
                try:
                    exp_dt = parse_expiry(exp_tok)
                except ValueError:
                    continue
                h_away = (exp_dt - dec).total_seconds() / 3600
                if 0 < h_away < 60:
                    iv_fn, krange = fit_smile(tl, dec_ms, spot)
                    if iv_fn:
                        smiles[exp_tok] = (exp_dt, iv_fn, krange, len(tl))

            if not smiles:
                continue

            pre  = sorted([(et, f, kr) for _, (et, f, kr, _) in smiles.items()
                           if et < res], key=lambda x: x[0])
            post = sorted([(et, f, kr) for _, (et, f, kr, _) in smiles.items()
                           if et >= res], key=lambda x: x[0])
            if not post:
                continue   # need at least one post-resolution expiry

            # Choose interpolation pair
            if pre and post:
                t_expA, iv_fnA, _ = pre[-1]
                t_expB, iv_fnB, _ = post[0]
                TA = (t_expA - dec).total_seconds() / (365 * 86400)
                TB = (t_expB - dec).total_seconds() / (365 * 86400)
                use_extrap = False
            else:
                t_expB, iv_fnB, _ = post[0]
                TB = (t_expB - dec).total_seconds() / (365 * 86400)
                # Flat-vol extrapolation: var_pm = iv_fnB(K)^2 * T_pm
                iv_fnA  = iv_fnB   # will use same function, TA=0 trick
                TA      = 0.0
                use_extrap = True

            def get_deribit_p(K):
                if use_extrap:
                    var_pm = iv_fnB(K) ** 2 * T_pm
                else:
                    va = iv_fnA(K) ** 2 * TA
                    vb = iv_fnB(K) ** 2 * TB
                    w  = (T_pm - TA) / (TB - TA) if (TB - TA) > 0 else 1.0
                    var_pm = va + w * (vb - va)
                if var_pm <= 0:
                    return None
                sig = math.sqrt(var_pm / T_pm)
                d2  = (math.log(spot / K) - 0.5 * sig ** 2 * T_pm) / (
                    sig * math.sqrt(T_pm))
                return float(norm.cdf(d2))

            # Get PM mid-prices at decision time for each strike
            strikes_pm = []
            for m in sorted(e["markets"], key=lambda m: m["strike"]):
                hist = a1_load(f"clob_{m['tok'][:24]}.json")
                if not hist:
                    continue
                cands = [(abs(h["t"] - dec.timestamp()), h["p"]) for h in hist
                         if abs(h["t"] - dec.timestamp()) <= 2100]
                if not cands:
                    continue
                strikes_pm.append({"K": m["strike"], "pm": min(cands)[1],
                                   "outcome": m["outcome"]})

            if len(strikes_pm) < 3:
                continue

            strikes_pm.sort(key=lambda x: x["K"])
            events_ok += 1

            # Per-bucket probability mass: rho(i) = P(>K_{i-1}) - P(>K_i)
            for i in range(1, len(strikes_pm)):
                K_lo = strikes_pm[i - 1]["K"]
                K_hi = strikes_pm[i]["K"]
                p_lo_pm = strikes_pm[i - 1]["pm"]
                p_hi_pm = strikes_pm[i]["pm"]
                pm_mass = p_lo_pm - p_hi_pm   # probability mass PM assigns to [K_lo, K_hi]

                p_lo_d  = get_deribit_p(K_lo)
                p_hi_d  = get_deribit_p(K_hi)
                if p_lo_d is None or p_hi_d is None:
                    continue
                d_mass = p_lo_d - p_hi_d

                # log-moneyness of bucket midpoint
                k_mid = math.log(0.5 * (K_lo + K_hi) / spot) if spot > 0 else 0.0

                rnd_rows.append({
                    "cur": cur, "date": e["date"],
                    "K_lo": K_lo, "K_hi": K_hi,
                    "pm_mass": pm_mass, "d_mass": d_mass,
                    "diff": pm_mass - d_mass,  # +  = PM puts more mass here
                    "k_mid": k_mid, "S": spot,
                    "extrap": use_extrap,
                })

    if not rnd_rows:
        print("  No RND comparison data (check A1 cache).")
        return []

    diffs = [r["diff"] for r in rnd_rows]
    print(f"  Events with full data: {events_ok}")
    print(f"  Strike buckets analyzed: {len(rnd_rows)}")
    print(f"  PM mass − Deribit mass per bucket:")
    print(f"    mean  = {np.mean(diffs):+.4f}  (+ = PM heavier)")
    print(f"    std   = {np.std(diffs):.4f}")
    print(f"    > +1pp (PM much richer): {sum(1 for d in diffs if d >  0.01)}")
    print(f"    < −1pp (PM much lighter): {sum(1 for d in diffs if d < -0.01)}")

    # By log-moneyness band
    print(f"\n  Mean diff by log-moneyness band:")
    bands = [(-2, -0.20), (-0.20, -0.10), (-0.10, 0.0), (0.0, 0.10),
             (0.10, 0.20), (0.20, 2)]
    for lo, hi in bands:
        b = [r["diff"] for r in rnd_rows if lo <= r["k_mid"] < hi]
        if b:
            print(f"    k ∈ [{lo:+.2f},{hi:+.2f}): n={len(b):4d}  "
                  f"mean diff={np.mean(b):+.4f}  std={np.std(b):.4f}")

    return rnd_rows


# ──────────────────────────────────────────────────────────────
# Figures
# ──────────────────────────────────────────────────────────────

def make_figures(violations, live_ladders, rnd_rows):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # ── Figure 1: Historical violation gap distribution ───────────────────
    ax = axes[0]
    if violations:
        gaps = [v["gap"] for v in violations]
        ax.hist(gaps, bins=40, color="#d62728", alpha=0.75, edgecolor="white", lw=0.3)
        ax.axvline(0, color="k", ls="--", lw=1.2, label="0 (arb boundary at mid)")
        ax.set_xlabel("Mid-price violation size p(K2) − p(K1)  [K1 < K2]")
        ax.set_ylabel("Number of snapshots")
        ax.set_title(f"Historical mid-price monotonicity violations\n"
                     f"n={len(violations)} violations "
                     f"(of {sum(1 for _ in violations)}/{max(1,len(violations))} pair-snaps)")
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "No violations found", ha="center", va="center",
                transform=ax.transAxes, fontsize=13)
        ax.set_title("Historical mid-price monotonicity violations")
    ax.grid(alpha=0.2)

    # ── Figure 2: Live ladder price curves ───────────────────────────────
    ax = axes[1]
    plotted = 0
    if live_ladders:
        for ev in live_ladders:
            legs = [lg for lg in ev["legs"]
                    if lg.get("mid") is not None and lg.get("K") is not None]
            if len(legs) < 3:
                continue
            legs.sort(key=lambda x: x["K"])
            ks   = [lg["K"] for lg in legs]
            mids = [lg["mid"] for lg in legs]
            # highlight any event with mid violations in red, others grey
            has_mid_vio = any(m1 < m2 for m1, m2 in zip(mids[:-1], mids[1:]))
            color = "#d62728" if has_mid_vio else "#aaaaaa"
            ax.plot(ks, mids, "o-", color=color, alpha=0.5, ms=3, lw=1)
            plotted += 1
            if plotted >= 15:
                break
        ax.set_xlabel("Strike K ($)")
        ax.set_ylabel("Mid price = PM P(S > K)")
        ax.set_title(f"Live ladder price curves (up to 15 events)\n"
                     f"red = has mid-price monotonicity issue")
    else:
        ax.text(0.5, 0.5, "No live data", ha="center", va="center",
                transform=ax.transAxes, fontsize=12)
        ax.set_title("Live ladder prices")
    ax.grid(alpha=0.2)

    # ── Figure 3: RND shape PM vs Deribit ────────────────────────────────
    ax = axes[2]
    if rnd_rows:
        k_mids = np.array([r["k_mid"] for r in rnd_rows])
        diffs  = np.array([r["diff"]  for r in rnd_rows])
        # Scatter with transparency
        ax.scatter(k_mids, diffs, s=12, alpha=0.35, color="#1f77b4")

        # Running mean (bin average)
        bin_edges = np.linspace(k_mids.min() - 0.01, k_mids.max() + 0.01, 20)
        bin_c, bin_m = [], []
        for i in range(len(bin_edges) - 1):
            mask = (k_mids >= bin_edges[i]) & (k_mids < bin_edges[i + 1])
            if mask.sum() >= 2:
                bin_c.append(0.5 * (bin_edges[i] + bin_edges[i + 1]))
                bin_m.append(diffs[mask].mean())
        if bin_c:
            ax.plot(bin_c, bin_m, "o-", color="#d62728", lw=2, ms=5, label="bin mean")

        ax.axhline(0, color="k", lw=1.0, ls="--", label="0 (no shape diff)")
        ax.set_xlabel("Log-moneyness  ln(K / S)")
        ax.set_ylabel("PM mass − Deribit mass per bucket")
        ax.set_title("RND shape: PM vs Deribit at D−1 20Z\n"
                     "(+ = PM allocates more probability mass here)")
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "No RND data", ha="center", va="center",
                transform=ax.transAxes, fontsize=12)
        ax.set_title("RND shape comparison")
    ax.grid(alpha=0.2)

    fig.suptitle("D10: Crypto Ladder Monotonicity & RND Shape", fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(HERE, "fig_d10.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"\nWrote {out}")


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("D10: Crypto Ladder Monotonicity + RND Shape Scan")
    print("=" * 60)

    violations, pair_checks, snap_count = part1_historical()
    live_ladders                          = part2_live()
    rnd_rows                              = part3_rnd_shape()

    make_figures(violations, live_ladders, rnd_rows)

    # ── Final summary ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_vio   = len(violations)
    vio_rate    = total_vio / pair_checks if pair_checks else 0

    book_vio_count = sum(len(ev["vios"]) for ev in live_ladders)
    mid_vio_live   = sum(
        1 for ev in live_ladders for i in range(len(ev["legs"]) - 1)
        if (ev["legs"][i]["mid"] or 0) < (ev["legs"][i+1]["mid"] or 0)
    )

    print(f"  Historical mid violations:  {total_vio}  ({vio_rate:.3%} of pair-snaps)")
    print(f"  Live book violations:        {book_vio_count}  (executable no-arb arb)")
    print(f"  Live mid violations:         {mid_vio_live}  (informational)")
    if rnd_rows:
        diffs = [r["diff"] for r in rnd_rows]
        print(f"  RND shape mean diff:        {np.mean(diffs):+.4f}  (PM mass − Deribit mass)")
        print(f"  RND shape std:              {np.std(diffs):.4f}")


if __name__ == "__main__":
    main()
