"""
analyze_mm.py — does the PASSIVE (maker) side make money on Kalshi weather ladders?

Kalshi weather maker fee = $0 (only takers pay 0.07*P*(1-P)). So the maker keeps the
full spread; the only enemy is adverse selection (informed takers picking off stale
quotes, esp. after the day's high is realized).

For every historical trade we know the taker side, the price P, the size, and the
resolution. The maker took the other side, so realized maker PnL held to resolution:
    taker bought YES  -> maker SOLD yes  -> pnl = (P - outcome) * size
    taker bought NO   -> maker BOUGHT yes-> pnl = (outcome - P) * size
Aggregate maker PnL = what ALL liquidity providers collectively earned. Sign/size of
the per-contract PnL is the unit economics of market-making here.

We decompose by time-to-resolution (adverse selection rises as the high is realized)
and by price (ATM vs wings), and estimate capacity + annualized return on collateral.
"""
import json, os, glob, math, sys, io, datetime as DT
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache_trades")
KFEE = lambda p: 0.07 * p * (1 - p)


def load():
    recs = []
    for f in glob.glob(os.path.join(CACHE, "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if d.get("result") not in ("yes", "no") or not d["trades"]:
            continue
        d["outcome"] = 1.0 if d["result"] == "yes" else 0.0
        try:
            d["close_ts"] = DT.datetime.fromisoformat(
                d["close"].replace("Z", "+00:00")).timestamp()
        except Exception:
            d["close_ts"] = None
        recs.append(d)
    return recs


def main():
    recs = load()
    cities = sorted({r["city"] for r in recs})
    print(f"Markets: {len(recs)}  cities={cities}")
    ntr = sum(len(r["trades"]) for r in recs)
    print(f"Total trades: {ntr:,}\n")

    # ── aggregate maker PnL ────────────────────────────────────────────────
    tot_pnl = tot_size = tot_notional = 0.0
    tot_taker_fee = 0.0
    # time-to-resolution bins (hours before close)
    bins = [(1e9, 24), (24, 12), (12, 6), (6, 3), (3, 1), (1, 0)]
    blab = [">24h", "12-24h", "6-12h", "3-6h", "1-3h", "<1h"]
    bpnl = [0.0] * len(bins); bsize = [0.0] * len(bins); bnot = [0.0] * len(bins)
    # price buckets
    pbk = {"wing(<.15)": [0.0, 0.0], "mid(.15-.40)": [0.0, 0.0],
           "atm(.40-.60)": [0.0, 0.0], "mid(.60-.85)": [0.0, 0.0], "wing(>.85)": [0.0, 0.0]}

    def pbucket(p):
        if p < .15: return "wing(<.15)"
        if p < .40: return "mid(.15-.40)"
        if p < .60: return "atm(.40-.60)"
        if p < .85: return "mid(.60-.85)"
        return "wing(>.85)"

    for r in recs:
        oc = r["outcome"]; cts = r["close_ts"]
        for ts_str, p, sz, took_yes in r["trades"]:
            if sz <= 0:
                continue
            mk = (p - oc) if took_yes == 1 else (oc - p)   # maker pnl per contract
            tot_pnl += mk * sz; tot_size += sz; tot_notional += p * sz
            tot_taker_fee += KFEE(p) * sz
            pb = pbucket(p); pbk[pb][0] += mk * sz; pbk[pb][1] += sz
            if cts is not None:
                try:
                    tts = DT.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                    h = (cts - tts) / 3600.0
                except Exception:
                    h = None
                if h is not None:
                    for i, (hi, lo) in enumerate(bins):
                        if lo <= h < hi:
                            bpnl[i] += mk * sz; bsize[i] += sz; bnot[i] += p * sz
                            break

    print("=" * 68)
    print("AGGREGATE PASSIVE (MAKER) PnL held to resolution  (maker fee = $0)")
    print("=" * 68)
    print(f"  total contracts traded : {tot_size:,.0f}")
    print(f"  total notional traded  : ${tot_notional:,.0f}")
    print(f"  total maker PnL        : ${tot_pnl:,.0f}")
    print(f"  maker PnL / contract   : {tot_pnl/tot_size*100:+.3f}c   "
          f"(= {tot_pnl/tot_notional*100:+.2f}% of notional)")
    print(f"  [taker side: PnL ${-tot_pnl:,.0f} gross, minus ${tot_taker_fee:,.0f} fees "
          f"= ${-tot_pnl - tot_taker_fee:,.0f} net]")

    print("\n  By time-to-resolution (adverse selection rises late):")
    print(f"  {'bin':8s} {'contracts':>12} {'maker_pnl$':>12} {'pnl/contract':>13}")
    for i, lab in enumerate(blab):
        if bsize[i] > 0:
            print(f"  {lab:8s} {bsize[i]:12,.0f} {bpnl[i]:12,.0f} "
                  f"{bpnl[i]/bsize[i]*100:+12.3f}c")

    print("\n  By price level:")
    print(f"  {'bucket':14s} {'contracts':>12} {'maker_pnl$':>12} {'pnl/contract':>13}")
    for k, (pn, sz) in pbk.items():
        if sz > 0:
            print(f"  {k:14s} {sz:12,.0f} {pn:12,.0f} {pn/sz*100:+12.3f}c")

    # ── 'smart maker' variant: only quote when >Xh to resolution ───────────
    print("\n" + "=" * 68)
    print("SMART-MAKER (stop quoting near resolution to dodge adverse selection)")
    print("=" * 68)
    for cutoff in (24, 12, 6, 3):
        pnl = size = notl = 0.0
        for r in recs:
            oc = r["outcome"]; cts = r["close_ts"]
            if cts is None:
                continue
            for ts_str, p, sz, took_yes in r["trades"]:
                if sz <= 0:
                    continue
                try:
                    h = (cts - DT.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()) / 3600.0
                except Exception:
                    continue
                if h < cutoff:
                    continue
                mk = (p - oc) if took_yes == 1 else (oc - p)
                pnl += mk * sz; size += sz; notl += p * sz
        if size > 0:
            # collateral per contract ~ avg(min(p,1-p)) proxied by notional share; use 0.5 cap
            print(f"  quote only >{cutoff}h before close: contracts={size:,.0f}  "
                  f"maker_pnl=${pnl:,.0f}  pnl/contract={pnl/size*100:+.3f}c  "
                  f"({pnl/notl*100:+.2f}% notional)")

    # ── capacity & rough annualized return ─────────────────────────────────
    print("\n" + "=" * 68)
    print("CAPACITY / RETURN (rough)")
    print("=" * 68)
    days = len({r["close"][:10] for r in recs})
    ndays_city = days
    daily_notional = tot_notional / max(days, 1)
    print(f"  span: {days} resolution-days, {len(cities)} city(s)")
    print(f"  avg daily notional traded (all makers+takers): ${daily_notional:,.0f}/day")
    # collateral: a maker posts ~min(p,1-p) per contract; approximate avg 0.35
    coll_per = 0.35
    if tot_pnl > 0:
        # if a single maker captured share s of volume, capital ~ s * size_per_day * coll_per,
        # daily return = pnl_per_day / capital = (pnl/contract)/coll_per ; annualize daily compounding-free
        ret_per_contract = tot_pnl / tot_size
        daily_ret = ret_per_contract / coll_per
        print(f"  maker return on collateral per cycle: {daily_ret*100:+.2f}% "
              f"(pnl/contract {ret_per_contract*100:+.3f}c / ~{coll_per*100:.0f}c collateral)")
        print(f"  if ~1 cycle/day -> rough annualized (×~250): {daily_ret*250*100:+.0f}% "
              f"(BEFORE competition share, LIP cap, Norway tax/frictions)")
    else:
        print("  passive side is NET NEGATIVE -> market-making loses to adverse selection")

    print("\nNote: aggregate = ALL makers. A real maker gets a share and competes with")
    print("bots already quoting 1c spreads; LIP rebate capped ~$7k/wk; Norway frictions apply.")


if __name__ == "__main__":
    main()
