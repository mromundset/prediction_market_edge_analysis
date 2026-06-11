# B6: Cross-market probability consistency — results

**Question:** Do hierarchically related markets on Polymarket violate P(A) ≤ P(B)
when A ⊆ B, allowing a risk-free Dutch-book arb: sell A at bid, buy B at ask,
collect guaranteed net credit?

**Answer: No economically viable edge found.** Two scans across ~14,500 binary
markets (8,986 events, all non-sports) using five independent logical-dependency
detectors found zero executable arbs above the risk-free rate. The one genuine
executable violation (3.6% net, ~12-month lockup) had $10 depth at the critical
leg — a max profit of $0.36.

---

## Methodology — v2 (five detectors)

```
Payoff structure (sell HARD/subset at bid, buy EASY/superset at ask):
  HARD=YES (→ EASY=YES by logic):  -$1 + $1 = 0    → P&L = credit
  HARD=NO,  EASY=YES:               $0 + $1 = +$1   → P&L = credit + 1
  HARD=NO,  EASY=NO:                $0 + $0 = 0     → P&L = credit
Worst case = credit. Risk-free iff credit > fees.
```

**Detector T — Threshold chains.** Same variable, different price levels. "Will
SOL be above $110 on June 16?" ⊆ "Will SOL be above $90 on June 16?" since
SOL>110 implies SOL>90. Grouping key = question-as-template (replace the
threshold number with `__`). Each group must satisfy P(above K_lo) ≥ P(above K_hi)
for K_lo < K_hi. 14,470 binary markets parsed; 804 mid-price violations found.

**Detector H — Time-horizon chains.** "Will X happen by June 2027?" ⊆ "by
September 2027?" since happening by June is a stricter condition. Detects only
"by [date]" / "before [date]" constructions (not "in YYYY", which means that
specific year only). Extracts full YYYYMM to avoid same-year false comparisons.
Handles negated questions ("Will X NOT happen by T") separately — for negated
events the ordering is reversed: P(NOT X by T1) ≥ P(NOT X by T2) for T1 < T2.
357 → 212 violations after negation fix.

**Detector E — Election chains.** Win-nomination is a precondition for
win-election in standard two-party systems, so P(win election) ≤ P(win
nomination). Matches person name + nomination vs. election-win phrasing.

**Detector N — Count chains.** P(at least N+1 occurrences) ≤ P(at least N).
"At least 40% on benchmark" ⊆ "at least 25% on benchmark".

**Detector G — Geographic scope.** P(event in specific country) ≤ P(event
anywhere). Heuristic; intra-event only.

---

## Scan statistics (5,944 non-sports events, 14,470 binary markets, 944 geo)

| Detector | Mid-price violations | Cross-event | Geo/fee-free |
|---|---|---|---|
| T threshold chains | 804 | 17 | 2 |
| H time-horizon | 212 | 22 | 1 |
| E election chains | **0** | 0 | 0 |
| N count chains | 5 | 0 | 0 |
| G geo scope | 1 | 0 | 1 |
| **Total (deduped)** | **1,017** | **39** | **4** |

After book verification of top 601 candidates:

| Category | Count |
|---|---|
| Positive-net executable arbs | **2** |
| Positive gross (net lost to fees) | 0 |
| Close misses (net in −0.5% to 0) | 3 |

---

## The two "positive-net" arbs — both sub-economic

### Arb 1: Concrete token launch — Detector H [REAL, $10 depth]

```
SELL: "Will Concrete launch a token by June 30, 2027?"   bid=0.99  ($10 depth)
BUY:  "Will Concrete launch a token by September 30, 2027?" ask=0.95 ($20 depth)
gross=+4.0%  net=+3.6%  (fee_rate=0.07, crypto category)
```

**Genuine violation.** "By June 30" ⊆ "by September 30" — any launch by June
is definitely a launch by September. P(by June) = 0.80 > P(by September) = 0.65
at the mid; P(by June) = 0.99 > P(by September) = 0.95 at the book.

**Why it exists.** Polymarket creates token-launch markets in batches for many
projects, often with multiple deadline variants (Q2 2026, Q3 2026, Q4 2026, Q1
2027, etc.). When a project signals an imminent launch, the near-term deadline
market reprices to ~1.0, but the farther-out variant from a different batch is
not updated simultaneously. This creates a brief window where the ordering is
inverted. The same pattern appears in 212 time-horizon violations (see below).

**Why it fails the bar.** The best bid on the hard leg is only $10 (bid_size=10).
Maximum profit = $10 × 3.6% = **$0.36**. Annualized over the 12-month lockup,
this is 3.6%/year on $10 of capital — **below the risk-free rate**. Ignoring
the lockup cost and Norwegian tax (28%), the entire edge is worth $0.36.

---

### Arb 2: GBP/USD hit 1.10 vs 1.00 (Low) — Detector T [FALSE POSITIVE]

```
SELL: "Will GBP/USD hit 1.10 (Low) in 2026?"  bid=0.99
BUY:  "Will GBP/USD hit 1.00 (Low) in 2026?"  ask=0.98
gross=+1.0%  net=+0.88%
```

**False positive — direction misclassification.** "Hit 1.10 (Low)" means
GBP/USD will trade at or below 1.10 at some point in 2026 (a downward barrier
touch). For downward-barrier markets, the HIGHER threshold is the **easier**
condition (GBP/USD currently ~1.27-1.30; it must fall 17% to reach 1.10 but
drop 23% to reach 1.00). The correct subset relationship is:

  {hits 1.00} ⊆ {hits 1.10}  (price reaching 1.00 necessarily passes through 1.10)

Detector T classified 1.10 as HARD (higher threshold) and 1.00 as EASY, which
is correct for *upward*-move markets ("above K") but backwards for *downward*-
barrier markets ("hit K Low"). The arb proposed (sell "hits 1.10", buy "hits
1.00") would be wrong-way: "hits 1.10" is the superset, not the subset.

The actual book prices (0.14 mid and 0.08 mid) are in the **correct** order:
P(hits 1.10) = 14% > P(hits 1.00) = 8% — consistent with the downward barrier
logic. No real violation exists.

---

## The most interesting finding: count-chain violations in thin markets

Detector N found 5 genuine mid-price violations in scoring/benchmark markets:

| Markets | Gap | Notes |
|---|---|---|
| "Robin Hood" ≥80 vs ≥70 (RT score) | 22.0 pp | P(≥80) > P(≥70) — impossible |
| Grok ≥40% vs ≥25% (FrontierMath) | 12.5 pp | P(≥40%) > P(≥25%) — impossible |
| Grok ≥30% vs ≥25% (FrontierMath) | 10.0 pp | same benchmark |
| "Supergirl" ≥60 vs ≥50 (RT score) | 8.5 pp | P(≥60) > P(≥50) — impossible |
| Grok ≥40% vs ≥30% (FrontierMath) | 2.5 pp | derived from above |

These are **logically impossible** at the mid level. P(score ≥ 80) cannot exceed
P(score ≥ 70) on the same scale — any reviewer that gives ≥80 necessarily also
gives ≥70. The 22pp gap on Robin Hood and 12.5pp on Grok suggest the markets for
different threshold levels on the same benchmark were created at different times
by different users with inconsistent priors, and nobody updated them consistently.

**Why they're not executable.** All five are within the same event (same-event=
true). Despite the large mid-price gaps, the book shows either (a) empty order
books (no bids or asks at all), or (b) extremely wide bid-ask spreads that
consume the apparent gross profit. A mid-price of 0.45 on one market and 0.23
on the other can coexist with bid=0.10/ask=0.80 on both — the bid-ask spread
is 70pp wide, making the executable gross deeply negative. These markets are
effectively illiquid opinion trackers, not tradeable instruments.

---

## Systematic pattern: crypto token-launch "by date" markets

The 212 Detector H violations are overwhelmingly from one market category:
"Will [DeFi project X] launch a token by [date]?" markets, where Polymarket
has multiple deadline variants for the same project. Examples with large gaps:

| Earlier deadline | Later deadline | Mid gap |
|---|---|---|
| Papertrade by Dec 31, 2026 | by Mar 31, 2027 | 46.5 pp |
| Ritual by Jun 30, 2026 | by Sep 30, 2026 | 46.0 pp |
| Arcium by Dec 31, 2026 | by Jun 30, 2027 | 43.5 pp |
| Cap by Dec 31, 2026 | by Sep 30, 2027 | 43.6 pp |

These are genuine mid-price inversions: the earlier deadline is priced higher
than the later one in all cases. The pattern confirms the "batch creation"
hypothesis: when a project is perceived as likely to launch soon, the nearest
deadline market reprices, but the farther-out ones lag.

**Why not executable.** The books for all these markets show $10–$100 depth on
the critical side (the over-priced earlier-deadline market). Total exploitable
capacity across all 22 cross-event H violations: estimated **< $1,000** — not
worth the transaction friction, the liquidity risk, or the resolution ambiguity
(what counts as "launching a token"?). The Concrete example with $10 best-bid
size is representative.

---

## False positive taxonomy

The 1,017 mid-price violations break down by type:

**Detector T false positives (~90% of 804):**
1. **Directional mismatch**: "hit K (Low/High)" markets and FX barrier markets where
   higher K is the easier condition for a downward move. Template matches correctly
   but direction assignment is backwards.
2. **Different-direction events on same template**: "How high will Trump approval go?"
   (asks if approval reaches K from below) vs "How low will Trump approval go?" (asks
   if approval reaches K from above) — same template "will trump approval hit __"
   but logically inverted. Grouped together by accident.
3. **Coin rank markets**: "Will coin X end top 5?" vs "top 50?" — lower rank N is
   harder, but detector treats higher N as harder. Direction reversed for rank markets.

**Detector H false positives (most of 212):**
1. ~~Negated questions~~ — **fixed**: "NOT X by T1" correctly has higher P than
   "NOT X by T2"; now handled with opposite violation condition.
2. ~~Same-year different-month~~ — **fixed**: now extracts YYYYMM, not just YYYY.
3. Residual: thin markets where pricing is stale/inconsistent by construction
   rather than exploitable gap.

---

## What was genuinely searched and not found

- **Inflation → interest rate chains**: PM has no direct "if CPI > X%, then
  Fed hikes" conditional markets. The causal relationship is not logical (high
  CPI doesn't logically force Fed hikes), so no Dutch book is possible from the
  causal direction. The closest testable version — "Will Fed raise rates in Q3
  2026?" ⊆ "Will Fed raise rates at all in 2026?" — would require finding the
  specific pair. The E detector (nomination chains) and N detector (count chains)
  cover this implicitly but found zero election violations and only thin-market
  count violations.
- **Geopolitical escalation chains**: PM has 944 geopolitics (fee-free) markets
  but no logical subset pairs were found (e.g., no "Russia uses tactical nukes in
  Ukraine" alongside "any nuclear weapon detonated in 2026" at inconsistent
  prices). The 4 geo mid-violations were all false positives or direction errors.
- **Nomination → election chains**: 0 violations. PM's election markets are priced
  consistently: no candidate has P(win general) > P(win primary).
- **Fed rate path chains** ("at least 1 cut" vs "at least 2 cuts"): Covered by
  Detector N. 0 violations found — these markets are explicitly bot-maintained
  since they often live on the same NegRisk event.

---

## Verdict

**B6 v2 FAILS — no economically viable edge.**

Five independent detectors, 14,470 binary markets, 1,017 mid-price violations.
After book verification: two positive-net arbs, both sub-economic:
- The only genuine one (Concrete token +3.6%) has $10 depth, yields $0.36, and
  is well below the risk-free rate.
- The other is a false positive from direction misclassification.

**Why PM is hard to beat from the consistency angle:**
1. **Same-event consistency** is enforced by NegRisk bots in milliseconds — the
   B3 finding. No room for human-speed REST snapshots.
2. **Cross-event consistency** is enforced implicitly by informed traders who
   monitor related markets, and explicitly by the fact that these token/launch
   markets are so thin that they represent opinions, not liquid books.
3. **Thin-market violations are real but not tradeable.** The count-chain
   violations (scoring benchmarks) and time-horizon violations (token launches)
   are genuine logical inconsistencies that a competent risk-neutral trader would
   not accept. But the markets are so illiquid that the bid-ask spread always
   exceeds the apparent gross profit.
4. **Geopolitics is fee-free but also well-priced.** Zero geo violations found.
   The fee advantage is irrelevant if there's no pricing gap to capture.

The recurring pattern: **mid-price anomalies exist in thin/niche markets, but
the order book is 1–2 orders of magnitude too thin for any meaningful position.**

---

## Reproduce

```
cd cross_market_consistency_exploration
python3 scan_v2.py      # ~15 min (8k event scan + book verification)
```

Outputs: console summary + `violations_v2.json` (positive/gross/close arbs).
Original v1 scan in `scan.py` (sports tournament misclassification documented).
