"""
scan.py — B6: cross-market probability consistency scan.

For any pair of markets A (subset) and B (superset) where B must occur for A
to occur, probability theory requires: P(A) <= P(B). Violation is a risk-free
arbitrage: buy B (cheaper), sell A (more expensive), collect the price spread,
and all payoffs are non-negative.

Example: "England wins World Cup" <= "England reaches World Cup Final".
If P(win) = 0.20 but P(reach final) = 0.15, buy "reach final" at ask 0.16,
sell "win" at bid 0.19, receive net $0.03:
  - England reaches final but loses: long pays $1, short pays $0  -> net +$1.03
  - England wins:                    long pays $1, short pays -$1 -> net +$0.03
  - England doesn't reach final:     long pays $0, short pays $0  -> net +$0.03
All outcomes >= 0: genuine risk-free arb.

This is unlike B3 (YES+NO = $1) — there is no mechanical arbitrage mechanism
here. Bots that maintain complete-set coherence are not watching cross-event
semantic hierarchies. Violations, if any, close slowly (via directional
correctors, not mint/merge bots).

Three classes of hierarchy we scan
-----------------------------------
  H1  Tournament stages: win < reach_final < reach_semi < reach_qf < qualify
      (single-elimination: must pass each stage to win)
  H2  Nomination -> election:  P(win presidency) <= P(win nomination)
      P(X wins 2028 election) <= P(X wins 2028 primary/nomination)
  H3  Fed "at-least" chains: P(cuts >= 50bp) <= P(cuts >= 25bp)
      These encode nested intervals in the FOMC outcome ladder.

Method
------
  1. Fetch all active non-sports events from Gamma (up to 10k events).
  2. Within each event, group markets and classify into hierarchy classes by
     keyword heuristics on the question text.
  3. Check price monotonicity using CLOB ask/bid (via /books endpoint for the
     top candidates by liquidity).
  4. Report executable violations: gross = bid(superset) - ask(subset) > 0;
     net = gross - fee(ask) - fee(bid).

Run: python3 scan.py
"""

import json, os, re, sys, time, urllib.request
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

GAMMA   = "https://gamma-api.polymarket.com"
CLOB    = "https://clob.polymarket.com"
HERE    = os.path.dirname(os.path.abspath(__file__))
SNAP    = os.path.join(HERE, "..", "strategy_research", "markets_snapshot.json")

FEE_RATE = 0.04    # politics/sports default; 0.03 sports, 0.04 politics/tech
N_EVENTS = 300     # cap on live events to fetch for book-check


# ─────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────

def get(u, t=45, retries=3):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(
                u, headers={"Accept": "application/json",
                            "User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=t) as r:
                return json.load(r)
        except Exception as e:
            last = e; time.sleep(1.2)
    raise last


def post_json(u, body, t=45, retries=3):
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
            last = e; time.sleep(1.2)
    raise last


def best_quote(book, side):
    lv = book.get(side) or []
    if not lv:
        return None, 0.0
    b = (min if side == "asks" else max)(lv, key=lambda x: float(x["price"]))
    return float(b["price"]), float(b["size"])


def taker_fee(rate, p):
    return rate * p * (1 - p)


# ─────────────────────────────────────────────────────────────
# Stage-level classification heuristics
# ─────────────────────────────────────────────────────────────

# Ordered from most to least restrictive (higher index = easier to achieve)
# Any market matching a pattern gets that "level" index.
# A pair (i, j) with i < j and price[i] > price[j] is a violation.

STAGE_PATTERNS = [
    # Level 0 — highest bar (win the whole thing)
    (0, re.compile(
        r"\b(win|champion|title|winner)\b",
        re.I)),
    # Level 1 — reach the final / championship game
    (1, re.compile(
        r"\b(final|championship game|super bowl|world series|stanley cup finals|"
        r"nba finals|reach the final|make the final|go to the final)\b",
        re.I)),
    # Level 2 — reach the semifinal / conference finals / final four
    (2, re.compile(
        r"\b(semi.?final|final four|conference final|last four)\b",
        re.I)),
    # Level 3 — reach the quarterfinal / conference semi / elite eight
    (3, re.compile(
        r"\b(quarter.?final|elite eight|conference semi|round of 8|last eight)\b",
        re.I)),
    # Level 4 — reach round of 16 / sweet sixteen / last 16
    (4, re.compile(
        r"\b(round of 16|last 16|sweet sixteen|r16)\b",
        re.I)),
    # Level 5 — qualify / advance / make playoffs / make it
    (5, re.compile(
        r"\b(qualif|advance|make (it|the) playoff|make postseason|"
        r"clinch|progress)\b",
        re.I)),
]


def classify_stage(question):
    """Return the lowest (most restrictive) stage index that matches, or None."""
    q = question.lower()
    for lvl, pat in STAGE_PATTERNS:
        if pat.search(q):
            return lvl
    return None


# ─────────────────────────────────────────────────────────────
# Nomination → election hierarchy
# ─────────────────────────────────────────────────────────────

NOM_PATTERNS = re.compile(
    r"\b(nominat|primary|win (the )?(republican|democrat|gop|dem)\b|"
    r"(republican|democrat|gop|dem) nominee)\b", re.I)

ELECTION_PATTERNS = re.compile(
    r"\b(win (the )?(presidential|general|midterm|senate|governor)|"
    r"elected (president|senator|governor)|win (presidency|election))\b", re.I)


# ─────────────────────────────────────────────────────────────
# Fed "at-least" chains
# ─────────────────────────────────────────────────────────────

def parse_fed_cut_bp(question):
    """
    Returns (direction, basis_points) if a Fed cut/hike market; else None.
    'cut 25bp' -> ('cut', 25)   'cut >=50bp' -> ('cut_atleast', 50)
    """
    q = question.lower()
    m = re.search(
        r"(cut|hike|reduce|lower|raise|increase).{0,30}"
        r"(>=?\s*)?(\d+)\s*(basis points?|bps?|bp)",
        q)
    if not m:
        return None
    direction = "cut" if re.search(r"\b(cut|reduce|lower)\b", m.group(0)) else "hike"
    at_least   = bool(m.group(2))
    bp         = int(m.group(3))
    return (direction + ("_atleast" if at_least else ""), bp)


# ─────────────────────────────────────────────────────────────
# Fetch active events (with embedded markets)
# ─────────────────────────────────────────────────────────────

SPORTS_TAGS = {
    "sports", "soccer", "nfl", "nba", "mlb", "nhl", "ufc", "tennis",
    "golf", "cricket", "formula-1", "boxing", "esports", "rugby",
    "ncaa", "college-football", "mma",
}


def fetch_events(max_events=8000):
    events, offset = [], 0
    while len(events) < max_events:
        try:
            batch = get(
                f"{GAMMA}/events?active=true&closed=false"
                f"&limit=100&offset={offset}"
                f"&order=volume24hr&ascending=false")
        except Exception as ex:
            print(f"  fetch error at offset {offset}: {ex}")
            break
        if not batch:
            break
        events.extend(batch)
        if len(batch) < 100:
            break
        offset += 100
        time.sleep(0.12)
    return events


def parse_event(e):
    """Return dict with parsed market data for one event."""
    tags = set()
    for t in (e.get("tags") or []):
        s = t.get("slug") or t.get("label") or ""
        tags.add(s.lower())
    markets = []
    for m in (e.get("markets") or []):
        q = m.get("question", "")
        pr = m.get("outcomePrices")
        pr = json.loads(pr) if isinstance(pr, str) else (pr or [])
        mid = float(pr[0]) if pr else None
        cl = m.get("clobTokenIds")
        cl = json.loads(cl) if isinstance(cl, str) else cl
        yes_tok = cl[0] if cl else None
        liq = float(m.get("liquidityNum") or 0)
        markets.append({
            "q": q, "mid": mid, "tok": yes_tok,
            "liq": liq, "closed": bool(m.get("closed")),
        })
    return {
        "slug": e.get("slug", ""),
        "title": e.get("title", ""),
        "tags": tags,
        "sports": bool(tags & SPORTS_TAGS),
        "liq": float(e.get("liquidityNum") or 0),
        "markets": [m for m in markets if not m["closed"] and m["mid"] is not None],
    }


# ─────────────────────────────────────────────────────────────
# Find hierarchy violations at mid-price
# ─────────────────────────────────────────────────────────────

def find_tournament_violations(events):
    """
    Within each event, find pairs (A, B) where A is more restrictive than B
    (stage[A] < stage[B]) but mid(A) > mid(B) — a monotonicity violation.
    Returns list of candidate dicts.
    """
    candidates = []
    for ev in events:
        if ev["sports"]:
            continue   # sports are separate category; focus on non-sports first
        staged = []
        for m in ev["markets"]:
            lvl = classify_stage(m["q"])
            if lvl is not None:
                staged.append((lvl, m))
        if len(staged) < 2:
            continue
        staged.sort(key=lambda x: x[0])   # ascending: level 0 = hardest
        # Check every pair (i,j) with lvl[i] < lvl[j]
        for i in range(len(staged)):
            for j in range(i + 1, len(staged)):
                lvl_i, mi = staged[i]
                lvl_j, mj = staged[j]
                if lvl_i == lvl_j:
                    continue
                # i is more restrictive (harder) => P(i) should be <= P(j)
                if mi["mid"] is None or mj["mid"] is None:
                    continue
                if mi["mid"] > mj["mid"]:   # VIOLATION: harder outcome priced higher
                    candidates.append({
                        "type": "tournament",
                        "event": ev["slug"][:50],
                        "title": ev["title"][:50],
                        "total_liq": ev["liq"],
                        "q_hard": mi["q"][:80],   # should be cheaper
                        "q_easy": mj["q"][:80],   # should be more expensive
                        "lvl_hard": lvl_i,
                        "lvl_easy": lvl_j,
                        "mid_hard": mi["mid"],     # HIGHER (wrong)
                        "mid_easy": mj["mid"],     # LOWER (wrong)
                        "gap_mid": mi["mid"] - mj["mid"],  # positive = violation size
                        "tok_hard": mi["tok"],
                        "tok_easy": mj["tok"],
                        "liq_hard": mi["liq"],
                        "liq_easy": mj["liq"],
                    })
    return candidates


def find_sports_tournament_violations(events):
    """Same as above but for sports events."""
    candidates = []
    for ev in events:
        if not ev["sports"]:
            continue
        staged = []
        for m in ev["markets"]:
            lvl = classify_stage(m["q"])
            if lvl is not None:
                staged.append((lvl, m))
        if len(staged) < 2:
            continue
        staged.sort(key=lambda x: x[0])
        for i in range(len(staged)):
            for j in range(i + 1, len(staged)):
                lvl_i, mi = staged[i]
                lvl_j, mj = staged[j]
                if lvl_i == lvl_j:
                    continue
                if mi["mid"] is None or mj["mid"] is None:
                    continue
                if mi["mid"] > mj["mid"]:
                    candidates.append({
                        "type": "sports_tournament",
                        "event": ev["slug"][:50],
                        "title": ev["title"][:50],
                        "total_liq": ev["liq"],
                        "q_hard": mi["q"][:80],
                        "q_easy": mj["q"][:80],
                        "lvl_hard": lvl_i, "lvl_easy": lvl_j,
                        "mid_hard": mi["mid"], "mid_easy": mj["mid"],
                        "gap_mid": mi["mid"] - mj["mid"],
                        "tok_hard": mi["tok"], "tok_easy": mj["tok"],
                        "liq_hard": mi["liq"], "liq_easy": mj["liq"],
                    })
    return candidates


# ─────────────────────────────────────────────────────────────
# Verify candidates at order-book level
# ─────────────────────────────────────────────────────────────

def verify_at_book(candidates, fee_rate=FEE_RATE, max_cands=200):
    """
    For each candidate, fetch both books and compute the executable arb:
      buy B (easy/superset) at ask, sell A (hard/subset) at bid.
    For the actual trade: we want to BUY the underpriced one (easy) and
    SELL the overpriced one (hard):
      - pay ask(easy), receive bid(hard)
      - gross = bid(hard) - ask(easy)   [positive if hard is bid-priced above easy ask]
    Wait, re-read the arb:
      We buy B (superset/easy) and sell A (subset/hard).
      P(A) is too high (overpriced), P(B) is too low (underpriced).
      So: sell A at bid (receive bid_hard), buy B at ask (pay ask_easy).
      gross = bid_hard - ask_easy   (if > 0: executable arb).
    """
    # Sort by mid gap desc; check top N
    top = sorted(candidates, key=lambda x: -x["gap_mid"])[:max_cands]
    verified = []
    toks = list({c["tok_hard"] for c in top} | {c["tok_easy"] for c in top}
                if all(c.get("tok_hard") and c.get("tok_easy") for c in top)
                else set())

    # Fetch books in batches of 50
    books = {}
    for i in range(0, len(toks), 50):
        batch = toks[i:i+50]
        try:
            resp = post_json(f"{CLOB}/books", [{"token_id": t} for t in batch])
            for b in resp:
                aid = b.get("asset_id")
                if aid:
                    books[aid] = b
        except Exception as ex:
            print(f"  book fetch error: {ex}")
        time.sleep(0.15)

    for c in top:
        th, te = c.get("tok_hard"), c.get("tok_easy")
        if not th or not te:
            continue
        bh = books.get(th, {})
        be = books.get(te, {})
        bid_hard, bid_hard_sz = best_quote(bh, "bids")
        ask_easy, ask_easy_sz = best_quote(be, "asks")
        if bid_hard is None or ask_easy is None:
            continue

        # Executable arb: sell hard (at bid), buy easy (at ask)
        # Why this direction? We SELL A (overpriced hard subset), BUY B (underpriced easy superset).
        # Payoffs:
        #   A and B both YES:   +1 (from long B) - 1 (from short A) = 0, net = initial credit
        #   B YES, A NO:        +1 - 0 = +1,  net = 1 + initial credit
        #   B NO (=> A NO too): 0 - 0 = 0,    net = initial credit
        # So the initial credit (bid_hard - ask_easy) is locked in, always >= 0.
        gross = bid_hard - ask_easy
        fee_h = taker_fee(fee_rate, bid_hard)
        fee_e = taker_fee(fee_rate, ask_easy)
        net   = gross - fee_h - fee_e
        size  = min(bid_hard_sz, ask_easy_sz)

        c2 = dict(c)
        c2.update({
            "bid_hard": bid_hard, "ask_easy": ask_easy,
            "gross": gross, "net": net,
            "fee_h": fee_h, "fee_e": fee_e,
            "size": size,
        })
        verified.append(c2)

    return verified


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("B6: Cross-Market Probability Consistency Scan")
    print("=" * 65)

    print("\nFetching active events from Gamma API...")
    raw_events = fetch_events(max_events=8000)
    print(f"  Fetched: {len(raw_events)} events")

    events = [parse_event(e) for e in raw_events]
    non_sports = [e for e in events if not e["sports"]]
    sports = [e for e in events if e["sports"]]
    print(f"  Non-sports: {len(non_sports)},  Sports: {len(sports)}")

    # ── H1: Tournament hierarchy violations (non-sports) ──────────
    print("\n--- H1: Tournament hierarchy — non-sports ---")
    ns_vios = find_tournament_violations(non_sports)
    print(f"  Mid-price violations found: {len(ns_vios)}")
    if ns_vios:
        for v in sorted(ns_vios, key=lambda x: -x["gap_mid"])[:10]:
            print(f"  [{v['lvl_hard']}->{v['lvl_easy']}] gap={v['gap_mid']:+.3f}"
                  f"  liq=${v['total_liq']:,.0f}"
                  f"  HARD: {v['q_hard'][:55]}")
            print(f"         EASY: {v['q_easy'][:55]}")

    # ── H1: Tournament hierarchy violations (sports) ──────────────
    print("\n--- H1: Tournament hierarchy — sports ---")
    sp_vios = find_sports_tournament_violations(sports)
    print(f"  Mid-price violations found: {len(sp_vios)}")
    if sp_vios:
        top_sp = sorted(sp_vios, key=lambda x: -x["gap_mid"])[:10]
        for v in top_sp:
            print(f"  [{v['lvl_hard']}->{v['lvl_easy']}] gap={v['gap_mid']:+.3f}"
                  f"  liq=${v['total_liq']:,.0f}"
                  f"  HARD: {v['q_hard'][:55]}")
            print(f"         EASY: {v['q_easy'][:55]}")

    # ── Combine + verify at order book ─────────────────────────────
    all_vios = ns_vios + sp_vios
    print(f"\n  Total mid-price violations (both sports/non-sports): {len(all_vios)}")

    if all_vios:
        print(f"\nVerifying top {min(len(all_vios), 200)} at order book (ask/bid)...")
        verified = verify_at_book(all_vios, fee_rate=FEE_RATE, max_cands=200)
        print(f"  Verified (have both sides quoted): {len(verified)}")

        pos_gross = [v for v in verified if v["gross"] > 0]
        pos_net   = [v for v in verified if v["net"] > 0.001]
        print(f"  Gross > 0 (buy easy + sell hard profitable before fees): {len(pos_gross)}")
        print(f"  Net > 0.1c after fees: {len(pos_net)}")

        if pos_gross:
            print("\n  Gross-positive at book level:")
            for v in sorted(pos_gross, key=lambda x: -x["gross"])[:15]:
                print(f"    net={v['net']:+.4f}  gross={v['gross']:+.4f}"
                      f"  size={v['size']:.1f}  liq=${v['liq_hard']:,.0f}/${v['liq_easy']:,.0f}")
                print(f"      SELL(hard): {v['q_hard'][:60]}")
                print(f"       BUY(easy): {v['q_easy'][:60]}")
                print(f"      bid(hard)={v['bid_hard']:.4f}  ask(easy)={v['ask_easy']:.4f}")

        if not pos_gross:
            print("\n  No gross-positive executable arb found.")
            print("  Distribution of (bid_hard - ask_easy) across verified pairs:")
            spreads = sorted(v["gross"] for v in verified)
            if spreads:
                import statistics as st
                pct = lambda p: spreads[int(p * (len(spreads)-1))]
                print(f"    min={spreads[0]:+.4f}  p25={pct(.25):+.4f}"
                      f"  median={st.median(spreads):+.4f}"
                      f"  p75={pct(.75):+.4f}  max={spreads[-1]:+.4f}")
    else:
        print("  No mid-price violations detected — no book verification needed.")

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("SUMMARY")
    print("=" * 65)
    print(f"  Events scanned:             {len(events)}")
    print(f"  Non-sports:                 {len(non_sports)}")
    print(f"  Sports:                     {len(sports)}")
    print(f"  Mid-price violations (H1):  {len(all_vios)}")
    if all_vios:
        pos_g = sum(1 for v in verified if v["gross"] > 0)
        pos_n = sum(1 for v in verified if v["net"] > 0.001)
        print(f"  Executable gross > 0:       {pos_g}")
        print(f"  Executable net > 0.1c:      {pos_n}")

    # Save violation details
    out = os.path.join(HERE, "violations.json")
    with open(out, "w", encoding="utf-8") as f:
        save_vios = all_vios[:500] if all_vios else []
        json.dump(save_vios, f, indent=2)
    print(f"\nWrote {out} ({len(all_vios[:500])} violations)")


if __name__ == "__main__":
    main()
