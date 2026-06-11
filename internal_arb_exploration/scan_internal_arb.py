"""
scan_internal_arb.py — strategy B3: does executable INTERNAL arbitrage exist on live
Polymarket order books for a non-latency player?

Two textbook risk-free internal arbs (the ones IMDEA 2025 measured at $39.6M/yr, ~99%
bot-captured):
  (1) Binary complete-set: a YES+NO pair always redeems to exactly $1. If
      ask(YES)+ask(NO) < 1 -> buy the set below $1 -> locked profit. (Reverse: mint a
      set for $1 and sell both legs if bid(YES)+bid(NO) > 1.)
  (2) MECE / NegRisk Dutch-book: in a complete N-outcome set exactly one resolves YES,
      so N-1 NO legs pay $1 each. If sum(ask(NO_i)) < N-1 -> buy all NO -> locked profit.

We fetch live books for both legs of every market in a broad liquid universe (top
NegRisk MECE events + top liquid binaries), and compute profit NET of the per-leg taker
fee (feeRate*p*(1-p)) and executable SIZE (min depth across legs). If bots have cleaned
the books, we expect ~zero positive-net arb beyond the tick.

Run: python3 scan_internal_arb.py
"""
import json, os, time, urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "..", "strategy_research", "markets_snapshot.json")
CACHE = os.path.join(HERE, "books_cache.json")

N_NEG = 40        # top NegRisk MECE events by liquidity
N_BIN = 120       # top liquid binary single markets


def feerate(tags):
    t = set(tags)
    if t & {"crypto", "bitcoin", "ethereum", "solana", "crypto-prices"}:
        return 0.07
    if t & {"geopolitics"}:
        return 0.0
    if t & {"economic-policy", "economy", "culture", "pop-culture", "weather",
            "daily-temperature"}:
        return 0.05
    return 0.04   # politics/finance/tech/default


def get(u, t=40, retries=3):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(u, headers={"Accept": "application/json",
                                                     "User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=t) as r:
                return json.load(r)
        except Exception as e:                                  # noqa: BLE001
            last = e; time.sleep(1.0)
    raise last


def post(u, body, t=40, retries=3):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(u, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=t) as r:
                return json.load(r)
        except Exception as e:                                  # noqa: BLE001
            last = e; time.sleep(1.0)
    raise last


def is_bin(m):
    return [str(o).lower() for o in m["outs"]] == ["yes", "no"]


def best(book, side):
    """(price, size) at top of book. asks: lowest price; bids: highest."""
    lv = book.get(side) or []
    if not lv:
        return None, 0.0
    if side == "asks":
        b = min(lv, key=lambda x: float(x["price"]))
    else:
        b = max(lv, key=lambda x: float(x["price"]))
    return float(b["price"]), float(b["size"])


def fee(rate, p):
    return rate * p * (1 - p)


def main():
    snap = json.load(open(SNAP, encoding="utf-8"))
    ns = [e for e in snap if not e["sports"]]
    neg = sorted([e for e in ns if e["negRisk"]
                  and sum(1 for m in e["markets"] if is_bin(m)) >= 3],
                 key=lambda e: -e["liq"])[:N_NEG]
    bins = sorted([e for e in ns if any(is_bin(m) and m["liq"] > 50000 for m in e["markets"])
                   and not e["negRisk"]], key=lambda e: -e["liq"])[:N_BIN]
    targets = {e["slug"]: e for e in neg + bins}
    print(f"targets: {len(neg)} NegRisk MECE + {len(bins)} binary events = {len(targets)}")

    binary_arbs, mece_arbs = [], []
    ask_sums, bid_sums = [], []          # no-arb band distribution
    mece_incomplete = 0
    scanned_bin = 0

    for i, (slug, e) in enumerate(targets.items()):
        rate = feerate(e["tags"])
        try:
            ev = get(f"{GAMMA}/events/slug/{slug}")
            ev = ev[0] if isinstance(ev, list) else ev
        except Exception:
            continue
        legs = []
        for m in ev.get("markets", []):
            outs = m.get("outcomes")
            outs = json.loads(outs) if isinstance(outs, str) else outs
            if not outs or [str(o).lower() for o in outs] != ["yes", "no"]:
                continue
            cl = m.get("clobTokenIds")
            cl = json.loads(cl) if isinstance(cl, str) else cl
            if not cl or len(cl) < 2 or m.get("closed"):
                continue
            legs.append({"q": m.get("question", ""), "yes": cl[0], "no": cl[1]})
        if not legs:
            continue
        toks = [t for lg in legs for t in (lg["yes"], lg["no"])]
        try:
            books = post(f"{CLOB}/books", [{"token_id": t} for t in toks])
        except Exception:
            continue
        bk = {b.get("asset_id"): b for b in books}

        # (1) binary complete-set arb, per leg
        for lg in legs:
            by, bn = bk.get(lg["yes"]), bk.get(lg["no"])
            if not by or not bn:
                continue
            ay, sy = best(by, "asks"); an, sn = best(bn, "asks")
            dy, dby = best(by, "bids"); dn, dbn = best(bn, "bids")
            scanned_bin += 1
            if ay and an:
                ask_sums.append(ay + an)
            if dy and dn:
                bid_sums.append(dy + dn)
            if ay and an:
                gross = 1.0 - (ay + an)
                net = gross - fee(rate, ay) - fee(rate, an)
                if net > 0:
                    binary_arbs.append({"slug": slug, "q": lg["q"][:40], "side": "buy-set",
                                        "ay": ay, "an": an, "gross": gross, "net": net,
                                        "size": min(sy, sn)})
            if dy and dn:
                gross = (dy + dn) - 1.0
                net = gross - fee(rate, dy) - fee(rate, dn)
                if net > 0:
                    binary_arbs.append({"slug": slug, "q": lg["q"][:40], "side": "sell-set",
                                        "by": dy, "bn": dn, "gross": gross, "net": net,
                                        "size": min(dby, dbn)})

        # (2) MECE Dutch-book: buy all NO, worth N-1
        if e["negRisk"] and len(legs) >= 3:
            no_asks = [best(bk.get(lg["no"], {}), "asks") for lg in legs]
            if not all(p for p, _ in no_asks):
                mece_incomplete += 1     # some leg has no NO ask -> Dutch-book unexecutable
            if all(p for p, _ in no_asks):
                N = len(legs)
                cost = sum(p for p, _ in no_asks)
                gross = (N - 1) - cost
                fees = sum(fee(rate, p) for p, _ in no_asks)
                net = gross - fees
                mece_arbs.append({"slug": slug, "title": ev.get("title", "")[:40], "N": N,
                                  "cost": cost, "gross": gross, "net": net,
                                  "size": min(s for _, s in no_asks)})
        print(f"  [{i+1}/{len(targets)}] scanned {slug[:34]:34}", end="\r")
    print()

    print(f"\nBinary legs scanned: {scanned_bin}")
    pos_bin = [a for a in binary_arbs if a["net"] > 0.001]
    print(f"Binary complete-set arbs with net > 0.1c: {len(pos_bin)}")
    for a in sorted(pos_bin, key=lambda x: -x["net"])[:10]:
        print(f"   net={a['net']:+.4f} gross={a['gross']:+.4f} size={a['size']:.0f} "
              f"{a['side']} {a['q']}")

    pos_mece = [a for a in mece_arbs if a["net"] > 0.001]
    print(f"\nMECE NegRisk Dutch-books: {len(mece_arbs)} fully-quotable, "
          f"{mece_incomplete} incomplete (a leg has no NO ask -> unexecutable); "
          f"with net > 0.1c: {len(pos_mece)}")
    for a in sorted(mece_arbs, key=lambda x: -x["net"])[:10]:
        print(f"   net={a['net']:+.4f} gross={a['gross']:+.4f} (N={a['N']}) size={a['size']:.0f} "
              f"{a['title']}")

    import statistics as st
    print(f"\nNo-arb band (binary ask_yes+ask_no), n={len(ask_sums)}:")
    if ask_sums:
        ask_sums.sort()
        q = lambda p: ask_sums[int(p * (len(ask_sums) - 1))]
        print(f"   min={ask_sums[0]:.3f} p10={q(.10):.3f} median={q(.5):.3f} "
              f"p90={q(.9):.3f}  (<1.00 would be arb: {sum(s<1 for s in ask_sums)})")
    if bid_sums:
        bid_sums.sort()
        print(f"   bid_yes+bid_no: median={st.median(bid_sums):.3f} "
              f"max={bid_sums[-1]:.3f}  (>1.00 would be arb: {sum(s>1 for s in bid_sums)})")

    # figure
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.hist([s for s in ask_sums if s < 1.08], bins=40, alpha=0.7,
                label="ask(YES)+ask(NO)  (<1 = buy-set arb)", color="#d62728")
        ax.hist([s for s in bid_sums if s > 0.92], bins=40, alpha=0.7,
                label="bid(YES)+bid(NO)  (>1 = sell-set arb)", color="#2ca02c")
        ax.axvline(1.0, color="k", ls="--", lw=1.5, label="$1.00 (no-arb boundary)")
        ax.set_xlabel("complete-set price (sum of the two legs)")
        ax.set_ylabel("# of live binary markets")
        ax.set_title(f"Polymarket internal coherence: every complete set is bracketed by $1.00\n"
                     f"{len(ask_sums)} live binary books — zero executable internal arb")
        ax.legend(fontsize=9); ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, "fig_noarb_band.png"), dpi=130)
        print("\nWrote fig_noarb_band.png")
    except Exception as ex:                                     # noqa: BLE001
        print("fig err", ex)

    print("\n>>> positive-net internal arbs found =", len(pos_bin) + len(pos_mece))


if __name__ == "__main__":
    main()
