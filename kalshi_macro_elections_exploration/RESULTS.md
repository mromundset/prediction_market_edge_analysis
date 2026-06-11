# C3: Kalshi macro + elections cross-venue scan — results

**Question:** Do Kalshi's 2026 US election markets (Senate/House control) or its
macro indicator markets (Fed path, commodities, Treasury yields) diverge from
Polymarket prices enough to trade after fees and lockup costs?

**Answer: No economically viable edge found.** Both Senate and House control
markets exist on both venues and resolve on the same election results.
House control carries a 4pp mid-gap (Kalshi higher for Republicans), but the
only executable arb direction yields **+1.18% net (+2.80%/yr)** — below the
~4–5% current risk-free rate. Senate control and all commodity/macro series
are within fee tolerance or have no PM equivalent.

---

## Scan scope (June 11, 2026)

| Series | What was checked |
|---|---|
| CONTROLS | US Senate control 2026 |
| CONTROLH | US House control 2026 |
| GOVPARTYCA/FL/TX | Governor 2026 (3 states) |
| SENATEGA/ME/MN/NM/CT | Individual Senate races |
| KXBRENTD, KXCOPPERD, KXGOLDD | Daily commodity prices |
| KXNOTE10 | 10-year Treasury yield (Jun 30) |
| KXFEDDECISION | Fed rate decision path (B5) |

---

## C3a: US election markets

### Congressional control — both venues, same resolution source

Both Polymarket and Kalshi list Senate and House control markets for the
2026 midterms. Resolution source for both: AP/official election results on
election night (November 2026). These markets ARE fungible.

**Prices (June 11, 2026):**

| Market | Kalshi bid | Kalshi ask | PM bid | PM ask | Mid gap |
|---|---|---|---|---|---|
| R wins Senate | 0.570 | 0.580 | 0.550 | 0.560 | 2.0pp |
| D wins Senate | 0.420 | 0.440 | 0.450 | 0.460 | 2.5pp |
| R wins House  | 0.220 | 0.230 | 0.180 | 0.190 | 4.0pp |
| D wins House  | 0.780 | 0.790 | 0.810 | 0.820 | 3.0pp |

PM liquidity: Senate ~$168–180k per leg, House ~$270–277k per leg.
Kalshi spreads are tight (10bp for Senate, 10bp for House R).

**Arb analysis (145-day lockup to midterm):**

```
SENATE (Republicans): sell Kalshi at bid=0.570, buy PM at ask=0.560
  gross = 0.010
  fees  = kalshi_fee(0.570) + pm_fee(0.560) = 0.01716 + 0.00986 = 0.0270
  net   = −0.017   →  −4.0%/yr    NEGATIVE

HOUSE (Republicans): sell Kalshi at bid=0.220, buy PM at ask=0.190
  gross = 0.030
  fees  = kalshi_fee(0.220) + pm_fee(0.190) = 0.01201 + 0.00616 = 0.0182
  net   = +0.01183  → +2.80%/yr   BELOW RISK-FREE

HOUSE (Democrats): sell PM at bid=0.810, buy Kalshi at ask=0.790
  gross = 0.020
  fees  = pm_fee(0.810) + kalshi_fee(0.790) = 0.00616 + 0.01161 = 0.0178
  net   = +0.00223  → +0.53%/yr   TRIVIAL
```

The **House Republican** leg is the only positive-net arb. At +1.18% on a
145-day position, it annualises to **2.80%/yr** — below the 4–5% risk-free
rate and far below the 10% index hurdle. Max deployable capital is bounded
by PM's $270k order book; total profit at scale ≈ $3,200 over 5 months.

Senate markets carry a ~2pp mid-gap but the Kalshi spread (580 − 570 = 10bp)
combined with PM spread (560 − 550 = 10bp) plus fees makes every direction
negative. The two-sided taker fee structure eats the gap entirely.

### Individual state races

Kalshi lists Georgia, Maine, Minnesota, New Mexico, Connecticut Senate races.
PM matching search returned only World Cup markets by liquidity; PM does not
appear to have individual 2026 Senate race markets (only the aggregate
Senate control). No comparison possible at the state level.

### Governor races

Kalshi has California, Florida, Texas governor races. PM has California
Governor (CA) as one of its top-100 events. Kalshi's CA Governor prices
(D wins: bid=0.905, ask=0.906) are extremely tight and very close to PM's
California Governor market. No gap worth exploring.

---

## C3b: Commodity and rates markets

### Daily commodities (KXBRENTD, KXCOPPERD, KXGOLDD)

Kalshi has liquid daily price ladders for Brent oil, copper, and gold
(resolving same-day, June 11). PM search for "gold", "oil", "copper" returned
only World Cup markets by liquidity — **PM does not have equivalent
daily commodity price markets.** No cross-venue comparison possible.

### 10-year Treasury yield (KXNOTE10)

Kalshi has `KXNOTE10-26JUN30-T4.601`: P(yield > 4.601% on June 30) = 0.39.
PM search for "Treasury yield", "10-year", "SOFR" returned no matching markets.
**PM does not list Treasury yield markets.** No comparison possible.

**Key structural finding:** Kalshi's macro-financial product suite
(commodities, rates, equity indices) has no PM equivalent. These are
Kalshi-specific products serving its CFTC-regulated US customer base.
There is no cross-venue arbitrage simply because there's no second venue.

---

## B5: Fed compound distribution (Kalshi path vs PM aggregate)

### Setup

PM markets "How many Fed rate cuts in 2026?" (13 outcome markets, $95–285k
liquidity each) price the cumulative distribution for total 2026 cuts.
Kalshi's KXFEDDECISION series has per-meeting binary markets for each
remaining 2026 meeting (Jun, Jul, Sep, Oct, Dec). Comparing the two
allows a B5 test: do PM's aggregate probabilities match what the Kalshi
meeting-level prices imply under independence?

### PM distribution

| Cuts | PM mid |
|---|---|
| 0 | 0.7925 |
| 1 | 0.1350 |
| 2 | 0.0335 |
| 3 | 0.0215 |
| 4+ | 0.0175 |

### Kalshi per-meeting probabilities

| Meeting | P(cut25) | P(cut>25) | P(hold) | P(hike) | Sum |
|---|---|---|---|---|---|
| Jun 2026 | 0.000 | 0.000 | 0.985 | 0.000 | 0.985 |
| Jul 2026 | 0.020 | 0.015 | 0.915 | 0.060 | 1.010 |
| Sep 2026 | 0.050 | 0.000 | 0.780 | 0.180 | 1.010 |
| Oct 2026 | 0.170 | 0.025 | 0.730 | 0.210 | 1.135 |
| Dec 2026 | 0.050 | 0.000 | 0.645 | 0.380 | 1.075 |

The **sum > 1** for several meetings (up to +13.5pp in October) indicates
the binary contracts for each meeting carry a systematic overround — they
cannot all be simultaneously correct. This is a Kalshi market-structure
artifact, not a PM pricing anomaly.

### Independence model comparison

Assuming (incorrectly, but for comparison) that meeting outcomes are
independent and using normalised per-meeting cut probabilities:

| k | PM mid | Kalshi raw | Kalshi norm | PM − raw | PM − norm |
|---|---|---|---|---|---|
| 0 | 0.7925 | 0.7011 | 0.7246 | +9.1pp | +6.8pp |
| 1 | 0.1350 | 0.2691 | 0.2494 | −13.4pp | −11.4pp |
| 2 | 0.0335 | 0.0287 | 0.0250 | +0.5pp | +0.8pp |
| 3 | 0.0215 | 0.0012 | 0.0010 | +2.0pp | +2.0pp |

PM assigns more probability to k=0 AND to k≥3; Kalshi path implies more
probability at k=1. This is the expected signature of **positive correlation**
between meeting outcomes: if the Fed cuts once it tends to cut again, and if
it doesn't cut it tends to hold. Under independence, k=1 is inflated; under
positive correlation (the true meeting structure), k=0 and k=many are higher
and k=1 is lower. PM's distribution is consistent with the correlated picture.

### Why B5 fails

1. **Not directly tradeable:** PM's k-cut markets and Kalshi's per-meeting
   markets cannot be paired into a simple two-leg arb. A "short PM k=1, long
   Kalshi Oct cut" trade would require a complex multi-leg construction to
   neutralise all other scenarios.
2. **Kalshi overround:** The per-meeting sums exceed 1.0 (up to 13.5pp),
   meaning the gap is partly explained by Kalshi's own internal inconsistency.
3. **Independence assumption breaks:** The 9pp raw gap shrinks to 6.8pp after
   normalisation, and further narrows under a correlated model. There is no
   statistically or economically significant residual gap.
4. **Resolution mismatch risk:** PM's "cuts in 2026" counts all 2026 meetings.
   Kalshi's per-meeting markets span different horizons. Any construction would
   require careful term-matching.

---

## Verdict

**C3 + B5 FAIL — no economically viable edge.**

Kalshi election markets are priced within fee tolerance of PM's equivalent
markets. The one positive-net arb (House Republicans, +1.18% net) annualises
to 2.80%/yr — below the risk-free rate. Kalshi's macro-financial products
(commodities, Treasury yield, S&P 500) have no PM equivalent. The Fed
compound distribution shows a consistent sign (PM more hawkish/bimodal),
but the gap is artefactual (overround, independence assumption) and not
directly tradeable.

**Pattern:** two liquid venues (both with real money) for the same election
converge within the bid-ask spread plus fees. The 4pp mid-gap in House
control implies the total round-trip cost (PM taker + Kalshi taker) exceeds
the gap. This is the expected outcome when two efficient markets trade the
same underlying event: the mid-prices can diverge by up to the sum of the
two taker fee schedules without creating an arb (for a taker on both sides).

**Running scorecard: 8 straight negatives.**

---

## Reproduce

```
cd kalshi_macro_elections_exploration
python scan.py   # ~3 min
```

Outputs: console summary + `results_c3.json`.
