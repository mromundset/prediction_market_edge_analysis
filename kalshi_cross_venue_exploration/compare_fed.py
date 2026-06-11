"""
compare_fed.py — the one genuine, deep, semantically-matched PM<->Kalshi overlap:
the FOMC rate decision. Both venues resolve on the actual Fed announcement (identical
semantics) and both are liquid. We align the 5 buckets, measure the cross-venue price
gap, and compute the EXECUTABLE arbitrage net of both venues' fees + capital lockup.

Cross-venue lock for a bucket: buy YES on the cheap venue + buy NO (=sell YES) on the
dear venue. Cost = YES_ask_cheap + (1 - YES_bid_dear). If < $1 after fees, locked profit.
Fees: PM taker = 0.04*p*(1-p) (politics); Kalshi taker = 0.07*p*(1-p). Maker=0 both,
but a lock crosses both books (taker x2).
"""
import json, os, urllib.request, datetime as DT
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
KBASE = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
PM_FEE, K_FEE = 0.04, 0.07
TODAY = DT.date(2026, 6, 11)

# bucket alignment: canonical -> (Kalshi yes_sub_title contains, PM question contains)
BUCKETS = [
    ("no change",  "maintains",  "no change"),
    ("cut 25",     "Cut 25bps",  "decrease interest rates by 25 bps"),
    ("cut 50+",    "Cut >25bps", "decrease interest rates by 50+"),
    ("hike 25",    "Hike 25bps", "increase interest rates by 25 bps"),
    ("hike 50+",   "Hike >25bps","increase interest rates by 50+"),
]
# (PM slug, Kalshi event, approx meeting date)
MEETINGS = [
    ("fed-decision-in-july-181",      "KXFEDDECISION-26JUL", DT.date(2026, 7, 29)),
    ("fed-decision-in-september-762", "KXFEDDECISION-26SEP", DT.date(2026, 9, 17)),
]


def get(u, t=30):
    req = urllib.request.Request(u, headers={"Accept": "application/json",
                                             "User-Agent": "research/1.0"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.load(r)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pm_event(slug):
    e = get(f"{GAMMA}/events/slug/{slug}")
    e = e[0] if isinstance(e, list) else e
    out = []
    for m in e["markets"]:
        pr = json.loads(m["outcomePrices"]) if isinstance(m["outcomePrices"], str) else m["outcomePrices"]
        out.append({"q": m["question"], "yes": float(pr[0]),
                    "bid": f(m.get("bestBid")), "ask": f(m.get("bestAsk"))})
    return out


def k_event(ev):
    d = get(f"{KBASE}/markets?series_ticker=KXFEDDECISION&status=open&limit=200")
    return [m for m in d["markets"] if m["event_ticker"] == ev]


def fee(rate, p):
    return rate * p * (1 - p)


def main():
    rows = []
    print(f"{'meeting':8} {'bucket':9} | {'PM mid':>7} {'PM b/a':>11} | {'Kal mid':>7} {'Kal b/a':>11} | "
          f"{'gap':>6} | {'lock cost':>9} {'net arb':>8}")
    scatter = []
    for slug, kev, mdate in MEETINGS:
        pm, km = pm_event(slug), k_event(kev)
        days = (mdate - TODAY).days
        for canon, ksub, pq in BUCKETS:
            pmm = next((m for m in pm if pq.lower() in m["q"].lower()), None)
            kmm = next((m for m in km if ksub.lower() in (m.get("yes_sub_title", "") or "").lower()), None)
            if not pmm or not kmm:
                continue
            pm_mid = pmm["yes"]
            kb, ka = f(kmm.get("yes_bid_dollars")), f(kmm.get("yes_ask_dollars"))
            k_mid = (kb + ka) / 2 if kb is not None and ka is not None else None
            if k_mid is None:
                continue
            scatter.append((pm_mid, k_mid, canon))
            gap = pm_mid - k_mid
            # executable lock: buy YES cheap venue, buy NO dear venue
            # direction A: YES on PM (ask), NO on Kalshi (1 - k_bid)
            costA = (pmm["ask"] or 1) + (1 - kb) if pmm["ask"] else 9
            feeA = fee(PM_FEE, pmm["ask"] or 0.5) + fee(K_FEE, 1 - kb)
            # direction B: YES on Kalshi (ask), NO on PM (1 - pm_bid)
            costB = ka + (1 - (pmm["bid"] or 0)) if pmm["bid"] else 9
            feeB = fee(K_FEE, ka) + fee(PM_FEE, 1 - (pmm["bid"] or 0.5))
            netA = 1 - costA - feeA
            netB = 1 - costB - feeB
            net = max(netA, netB)
            rows.append({"meeting": kev[-5:], "bucket": canon, "gap": gap,
                         "net_arb": net, "days": days})
            print(f"{kev[-5:]:8} {canon:9} | {pm_mid:7.3f} {str(pmm['bid'])+'/'+str(pmm['ask']):>11} | "
                  f"{k_mid:7.3f} {str(kb)+'/'+str(ka):>11} | {gap:+6.3f} | "
                  f"{min(costA,costB):9.3f} {net:+8.3f}")

    best = max(rows, key=lambda r: r["net_arb"])
    print(f"\nBest executable net arb across all matched Fed buckets: {best['net_arb']:+.4f} "
          f"({best['meeting']} {best['bucket']}), capital locked {best['days']} days")
    if best["net_arb"] > 0:
        ann = (1 + best["net_arb"]) ** (365 / best["days"]) - 1
        print(f"  annualized (if real): {ann:.1%}")
    else:
        print("  -> NO positive-net cross-venue arb exists; fees+spreads exceed every gap.")

    # figure
    fig, ax = plt.subplots(figsize=(7, 7))
    for pm_mid, k_mid, canon in scatter:
        ax.scatter(k_mid, pm_mid, s=60)
        ax.annotate(canon, (k_mid, pm_mid), fontsize=7, xytext=(4, 3),
                    textcoords="offset points")
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlabel("Kalshi mid probability"); ax.set_ylabel("Polymarket mid probability")
    ax.set_title("PM vs Kalshi — FOMC decision buckets (Jul + Sep 2026)\n"
                 "the one genuine deep matched overlap; points hug the diagonal")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_fed_overlap.png"), dpi=130)
    print(f"\nWrote fig_fed_overlap.png")


if __name__ == "__main__":
    main()
