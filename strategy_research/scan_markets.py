"""
scan_markets.py — one full sweep of active Polymarket markets, saved compactly for
offline strategy analysis (where is the liquidity? are MECE sets coherent? do date
ladders respect monotonicity? what does the fee schedule look like?).

Dumps strategy_research/markets_snapshot.json and prints headline analyses.
"""
import json
import os
import urllib.request
from collections import defaultdict

GAMMA = "https://gamma-api.polymarket.com"
HERE = os.path.dirname(os.path.abspath(__file__))
SPORTS = {"sports","soccer","nfl","nba","mlb","nhl","epl","ufc","mma","boxing","tennis",
          "golf","cricket","f1","formula-1","motorsports","esports","cfb","ncaa","rugby",
          "cycling","baseball","basketball","football","hockey","games","fifa-world-cup",
          "2026-fifa-world-cup","champions-league","la-liga","serie-a","tennis-atp"}


def get(url, t=60):
    req = urllib.request.Request(url, headers={"Accept":"application/json","User-Agent":"research/1.0"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.load(r)


def jloads(x):
    if x is None: return None
    try: return json.loads(x) if isinstance(x, str) else x
    except Exception: return None


def fnum(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def main():
    events, off = [], 0
    while off <= 12000:
        b = get(f"{GAMMA}/events?limit=100&offset={off}&active=true&closed=false")
        if not b: break
        events += b; off += 100
        print(f"  {len(events)} events...", end="\r")
    print(f"\nTotal events: {len(events)}")

    snap = []
    for ev in events:
        tags = {t.get("slug","").lower() for t in (ev.get("tags") or [])}
        mkts = []
        for m in ev.get("markets") or []:
            outs = jloads(m.get("outcomes"))
            pr = jloads(m.get("outcomePrices"))
            if not outs or not pr: continue
            cl = jloads(m.get("clobTokenIds")) or []
            mkts.append({
                "q": m.get("question",""),
                "outs": outs,
                "pr": [fnum(x) for x in pr],
                "bid": fnum(m.get("bestBid")), "ask": fnum(m.get("bestAsk")),
                "spread": fnum(m.get("spread")),
                "vol": fnum(m.get("volumeNum")) or 0.0,
                "liq": fnum(m.get("liquidityNum")) or 0.0,
                "end": m.get("endDateIso") or m.get("endDate"),
                "git": m.get("groupItemTitle",""),
                "tok": cl[0] if cl else None,
                "active": m.get("active"), "closed": m.get("closed"),
            })
        if not mkts: continue
        snap.append({
            "slug": ev.get("slug",""), "title": ev.get("title",""),
            "tags": sorted(tags - {"all"}),
            "sports": bool(tags & SPORTS),
            "negRisk": bool(ev.get("negRisk") or ev.get("enableNegRisk")),
            "vol": fnum(ev.get("volume")) or 0.0,
            "liq": fnum(ev.get("liquidity")) or 0.0,
            "oi": fnum(ev.get("openInterest")) or 0.0,
            "n_markets": len(mkts),
            "markets": mkts,
        })

    out = os.path.join(HERE, "markets_snapshot.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snap, f)
    print(f"Saved {len(snap)} events -> {out}")

    # ---- headline analyses ----
    # 1. liquidity by primary (first non-sports) tag
    by_tag_liq = defaultdict(float); by_tag_vol = defaultdict(float); by_tag_n = defaultdict(int)
    for e in snap:
        key = (e["tags"][0] if e["tags"] else "untagged")
        by_tag_liq[key] += e["liq"]; by_tag_vol[key] += e["vol"]; by_tag_n[key] += 1
    print("\nTOP CATEGORIES by total order-book liquidity (USD):")
    for k in sorted(by_tag_liq, key=lambda x:-by_tag_liq[x])[:18]:
        print(f"  {k:24} liq=${by_tag_liq[k]:14,.0f}  vol=${by_tag_vol[k]:16,.0f}  events={by_tag_n[k]}")

    # 2. fee schedule presence (sample from raw events fetch is gone; note current trading-fee reality separately)
    # 3. multi-outcome MECE candidates: events with >=3 binary Yes/No markets, sum of YES
    print("\nMULTI-OUTCOME events (>=3 Yes/No markets): sum(YES) deviation from 1.0")
    mece = []
    for e in snap:
        ys = [m["pr"][0] for m in e["markets"]
              if [str(o).lower() for o in m["outs"]] == ["yes","no"] and m["pr"] and m["pr"][0] is not None]
        if len(ys) >= 3:
            s = sum(ys)
            mece.append((abs(s-1.0), s, len(ys), e))
    print(f"  found {len(mece)} such events")
    mece.sort(reverse=True)
    print("  largest |sum(YES)-1| (raw mid; ignores spread/fees):")
    for dev, s, n, e in mece[:12]:
        print(f"   sum={s:5.2f} (n={n:2d}, dev={dev:4.2f}) negRisk={int(e['negRisk'])} liq=${e['liq']:11,.0f}  {e['title'][:48]}")


if __name__ == "__main__":
    main()
