"""
overlap_quality.py — for the highest-overlap Kalshi series vs Polymarket, tabulate the
two things that decide whether cross-venue arb (A2) is real:
  (1) resolution-source match  (semantic fungibility — the #1 killer)
  (2) genuine uncertainty + real depth on BOTH sides (the #2 killer)
Also cross-references the cached PM snapshot for matching liquid markets.
"""
import json, os, urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2"
HERE = os.path.dirname(os.path.abspath(__file__))
PM_SNAP = os.path.join(HERE, "..", "strategy_research", "markets_snapshot.json")

# curated highest-overlap series (Kalshi) -> what PM market it would map to
CURATED = {
    "KXBTCD": "PM bitcoin-above daily", "KXBTC": "PM bitcoin price range",
    "KXETHD": "PM ethereum-above daily", "KXFEDDECISION": "PM Fed Decision in MONTH",
    "KXFED": "PM Fed rate level", "KXCPIYOY": "PM CPI/inflation above X",
    "KXECONSTATCPICORE": "PM core CPI", "KXJOBLESS": "PM jobless claims",
    "INX": "PM S&P 500 level", "KXNToDAQ": "PM Nasdaq", "GOLD": "PM gold price",
    "KXRECSSYR": "PM recession this year", "KXU3": "PM unemployment rate",
}


def get(u, t=30):
    req = urllib.request.Request(u, headers={"Accept": "application/json",
                                             "User-Agent": "research/1.0"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.load(r)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def series_meta(st):
    try:
        d = get(f"{BASE}/series/{st}")
        s = d.get("series", d)
        srcs = [x.get("name", "") for x in (s.get("settlement_sources") or [])]
        return s.get("fee_type", "?"), "; ".join(srcs)[:60]
    except Exception:
        return "?", "?"


def main():
    print(f"{'series':16} {'#open':>5} {'maxOI':>8} {'#uncertain':>10} {'fee':>9}  settlement / map")
    print("-" * 100)
    for st, pmmap in CURATED.items():
        try:
            d = get(f"{BASE}/markets?series_ticker={st}&status=open&limit=200")
            ms = d.get("markets", [])
        except Exception as e:
            print(f"{st:16}  ERR {str(e)[:40]}")
            continue
        if not ms:
            print(f"{st:16} {'0':>5}   (no open markets)   -> {pmmap}")
            continue
        maxoi = max(f(m.get("open_interest_fp")) for m in ms)
        uncertain = sum(1 for m in ms if 0.10 <= f(m.get("yes_bid_dollars")) <= 0.90)
        fee, srcs = series_meta(st)
        print(f"{st:16} {len(ms):5d} {maxoi:8,.0f} {uncertain:10d} {fee:>9}  {srcs}")
        print(f"{'':16} -> maps to {pmmap}")

    # PM side: what liquid non-sports markets exist in these domains?
    if os.path.exists(PM_SNAP):
        snap = json.load(open(PM_SNAP, encoding="utf-8"))
        import re
        pat = re.compile(r"\b(cpi|inflation|fed|interest rate|bitcoin|ethereum|s&p|sp 500|"
                         r"nasdaq|gold|recession|unemployment|jobless|gdp)\b", re.I)
        print("\nPM liquid (>$100k) markets in overlap domains:")
        hits = []
        for e in snap:
            if e.get("sports"):
                continue
            if pat.search(e["title"]) and e["liq"] > 100000:
                hits.append((e["liq"], e["title"], e.get("tags", [])[:2]))
        for liq, title, tags in sorted(hits, reverse=True)[:15]:
            print(f"  ${liq:12,.0f}  {title[:50]}  {tags}")
    else:
        print("\n(PM snapshot not found — run strategy_research/scan_markets.py first)")


if __name__ == "__main__":
    main()
