"""
fetch_kalshi.py — pull Kalshi's *genuinely active* non-sports markets and assess the
real overlap with Polymarket for cross-venue arbitrage (strategy A2).

Kalshi is swamped by ~60k auto-generated sports/parlay markets (KXMVE*, sports series)
with zero liquidity. We paginate /markets (open) and keep only markets with real
activity (open interest or 24h volume above a floor), dropping the junk. Saves
kalshi_active.json and prints the active universe bucketed by series, plus the typical
notional scale (the capacity question).
"""
import json, os, re, urllib.request, collections

BASE = "https://api.elections.kalshi.com/trade-api/v2"
HERE = os.path.dirname(os.path.abspath(__file__))
OI_FLOOR = 500.0          # contracts (~$ notional); keep markets with real open interest
V24_FLOOR = 500.0
SPORTS_PREFIX = re.compile(r"^(KXMVE|KX.*(MLB|NBA|NFL|NHL|NCAA|UFC|ATP|WTA|ITF|LALIGA|"
                           r"EPL|SOCCER|TENNIS|GOLF|F1|GAME|MATCH|SERIESWIN|ESPORTS))")


def get(u, t=40):
    req = urllib.request.Request(u, headers={"Accept": "application/json",
                                             "User-Agent": "research/1.0"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.load(r)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def main():
    active, cur, pages = [], "", 0
    while pages < 80:
        d = get(f"{BASE}/markets?limit=1000&status=open" + (f"&cursor={cur}" if cur else ""))
        ms = d.get("markets", [])
        for m in ms:
            tk = m["ticker"]
            if SPORTS_PREFIX.match(tk):
                continue
            oi, v24 = f(m.get("open_interest_fp")), f(m.get("volume_24h_fp"))
            if oi < OI_FLOOR and v24 < V24_FLOOR:
                continue
            active.append({
                "ticker": tk, "event": m.get("event_ticker"),
                "series": re.split(r"-", tk)[0],
                "title": m.get("title", ""), "sub": m.get("yes_sub_title", ""),
                "yes_bid": f(m.get("yes_bid_dollars")), "yes_ask": f(m.get("yes_ask_dollars")),
                "no_bid": f(m.get("no_bid_dollars")), "no_ask": f(m.get("no_ask_dollars")),
                "oi": oi, "v24": v24,
                "bidsz": f(m.get("yes_bid_size_fp")), "asksz": f(m.get("yes_ask_size_fp")),
                "close": m.get("close_time"),
                "rules": (m.get("rules_primary", "") or "")[:300],
            })
        cur = d.get("cursor"); pages += 1
        print(f"  page {pages}: scanned, kept {len(active)} active so far", end="\r")
        if not cur or not ms:
            break
    print()
    json.dump(active, open(os.path.join(HERE, "kalshi_active.json"), "w"))
    print(f"Active non-sports Kalshi markets (OI>={OI_FLOOR} or v24>={V24_FLOOR}): {len(active)}")

    byser = collections.defaultdict(lambda: [0, 0.0])
    for m in active:
        byser[m["series"]][0] += 1
        byser[m["series"]][1] += m["oi"]
    print("\nTOP 30 active series by total open interest (contracts ~= $ notional):")
    for s in sorted(byser, key=lambda x: -byser[x][1])[:30]:
        n, oi = byser[s]
        print(f"  {s:30} n={n:4d}  OI={oi:14,.0f}")

    # uncertainty: how many active markets are genuinely live (price in [0.10,0.90])?
    live = [m for m in active if 0.10 <= m["yes_bid"] <= 0.90]
    print(f"\nactive AND genuinely uncertain (yes_bid in [0.10,0.90]): {len(live)}")
    print("median OI of those:", sorted(m["oi"] for m in live)[len(live)//2] if live else "n/a")


if __name__ == "__main__":
    main()
