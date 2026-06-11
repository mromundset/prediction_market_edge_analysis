"""Offline analyses on markets_snapshot.json for the strategy doc."""
import json, os, re, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
snap = json.load(open(os.path.join(HERE, "markets_snapshot.json"), encoding="utf-8"))


def is_binary(m):
    return [str(o).lower() for o in m["outs"]] == ["yes", "no"]


def yes(m):
    return m["pr"][0] if m["pr"] and m["pr"][0] is not None else None


nonsport = [e for e in snap if not e["sports"]]
print(f"events: {len(snap)} total, {len(nonsport)} non-sports\n")

# 1) Top non-sports events by order-book liquidity
print("=== TOP 20 NON-SPORTS EVENTS BY ORDER-BOOK LIQUIDITY ===")
for e in sorted(nonsport, key=lambda e: -e["liq"])[:20]:
    print(f"  ${e['liq']:13,.0f}  vol ${e['vol']:14,.0f}  n={e['n_markets']:3d}  "
          f"negRisk={int(e['negRisk'])}  {e['title'][:46]}  [{','.join(e['tags'][:2])}]")

# 2) Internal coherence: multi-outcome sum(YES), negRisk vs not
print("\n=== MULTI-OUTCOME COHERENCE: sum(YES) vs 1.0 ===")
def sumyes(e):
    ys = [yes(m) for m in e["markets"] if is_binary(m) and yes(m) is not None]
    return (sum(ys), len(ys)) if len(ys) >= 3 else (None, 0)
rows = []
for e in nonsport:
    s, n = sumyes(e)
    if s is not None:
        rows.append((e, s, n))
for label, sub in [("negRisk", [r for r in rows if r[0]["negRisk"]]),
                   ("non-negRisk", [r for r in rows if not r[0]["negRisk"]])]:
    devs = [abs(s - 1.0) for _, s, _ in sub]
    if devs:
        print(f"  {label:12} n={len(sub):4d}  mean|sum-1|={statistics.mean(devs):.3f}  "
              f"median={statistics.median(devs):.3f}  max={max(devs):.3f}  "
              f">0.05: {sum(d>0.05 for d in devs)}  >0.10: {sum(d>0.10 for d in devs)}")
print("  largest deviations (liq-weighted candidates):")
for e, s, n in sorted(rows, key=lambda r: -abs(r[1]-1.0))[:12]:
    if e["liq"] > 5000:
        print(f"   sum={s:5.2f} n={n:2d} negRisk={int(e['negRisk'])} liq=${e['liq']:11,.0f}  {e['title'][:46]}")

# 3) Crypto price-market inventory (maps to Deribit)
print("\n=== CRYPTO PRICE-MARKET INVENTORY (Deribit-comparable) ===")
pricepat = re.compile(r"\$[\d,]+|\bprice\b|reach|above|below|between|hit|dip", re.I)
cryptotags = {"crypto", "bitcoin", "ethereum", "solana"}
cmk = []
for e in nonsport:
    if cryptotags & set(e["tags"]):
        for m in e["markets"]:
            if is_binary(m) and pricepat.search(m["q"]):
                cmk.append((e, m))
liqc = sum(e["liq"] for e in {id(x[0]): x[0] for x in cmk}.values())
print(f"  {len(cmk)} crypto price binaries across {len({id(x[0]) for x in cmk})} events; "
      f"event liq total ${liqc:,.0f}")
seen = set()
for e, m in sorted(cmk, key=lambda x: -x[0]["liq"]):
    if e["slug"] in seen: continue
    seen.add(e["slug"])
    print(f"   liq ${e['liq']:11,.0f}  {e['title'][:50]}  ({e['n_markets']} mkts)")
    if len(seen) >= 12: break

# 4) Fed / rates inventory (maps to ZQ/FedWatch)
print("\n=== FED / RATES INVENTORY (FedWatch-comparable) ===")
fedpat = re.compile(r"\bfed\b|interest rate|rate (cut|hike)|bps|fomc|powell|basis point", re.I)
seen = set()
for e in sorted(nonsport, key=lambda e: -e["liq"]):
    if fedpat.search(e["title"]) or any(fedpat.search(m["q"]) for m in e["markets"]):
        if e["slug"] in seen: continue
        seen.add(e["slug"])
        print(f"   liq ${e['liq']:11,.0f}  vol ${e['vol']:12,.0f}  n={e['n_markets']:2d}  {e['title'][:52]}")
    if len(seen) >= 12: break

# 5) Spread/liquidity reality: distribution of best spread on non-sports binaries w/ vol>50k
print("\n=== SPREAD REALITY (non-sports binaries, vol>$50k) ===")
spr = [m["spread"] for e in nonsport for m in e["markets"]
       if is_binary(m) and m["spread"] is not None and m["vol"] > 50000]
spr.sort()
if spr:
    q = lambda p: spr[int(p*len(spr))]
    print(f"  n={len(spr)}  spread pctiles: p10={q(.10):.3f} p25={q(.25):.3f} "
          f"median={q(.50):.3f} p75={q(.75):.3f} p90={q(.90):.3f}")
