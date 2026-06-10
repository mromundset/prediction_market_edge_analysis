# CLAUDE.md — World Cup 2026 prediction-market model

Context brief for Claude Code. Read this first each session. Keep it updated:
when a correction is made, add a rule to the "Don't" section so it doesn't recur.

## What this project is

A quantitative model for finding mispricings in **2026 FIFA World Cup** markets on
**Polymarket**. Single-source design: pull the *match-level* odds (the efficient,
liquid layer), propagate them through the tournament structure, and compare the
resulting *aggregate* probabilities against Polymarket's directly-priced aggregate
markets (advance-to-knockout, group winner). Edges, if real, are expected in the
long-range / third-place corners, not the headline match markets.

**Working thesis:** prediction markets are sharp on singular match outcomes but may
be softer on long-range aggregates (favorite-longshot + sentiment bias). The model
tests whether the aggregate markets are internally consistent with the match markets.

## Files

- `wc2026_joint.py`  — **MAIN ARTIFACT.** Joint 12-group Monte Carlo. Fetches all 72
  group fixtures (1X2 + totals) from Polymarket, fits a bivariate Poisson per match,
  simulates every group jointly, selects the 8 best third-place teams, and compares
  model P(advance) vs the live advance market with an input-noise band. Imports
  low-level fetchers from `polymarket_wc.py`.
- `polymarket_wc.py` — Polymarket Gamma API client + single-group demo (Group I).
  Fetchers: `fetch_games`, `fetch_group_winner`, `fetch_advance_prices`, `devig`,
  `fit_lambdas` (1X2-only), `simulate_group_from_market`, `consistency_report`.
- `wc2026_model.py`  — Standalone simulator driven by hand-set team RATINGS
  (placeholders). Has the full knockout bracket (RANDOMISED, not the official R32
  map), the head-to-head-first tiebreak variant, and the sensitivity/noise machinery.
  Useful as the reference engine; its market comparison uses hand-entered prices.

## Environment

Python 3, `numpy`, `scipy`, internet access (Polymarket Gamma API). No API key.
Run: `python3 wc2026_joint.py`  (takes ~1–2 min: 144 HTTP fetches + sim + noise pass).

## Polymarket API map (hard-won — don't re-discover)

Base: `https://gamma-api.polymarket.com`  (events at `/events`, `/events/slug/<slug>`)
Tags: `fifa-world-cup`=102232, `games`=100639, `2026-fifa-world-cup`=102350,
`world-cup`=519, `soccer`=100350.

- **Match (game) events:** slug `fifwc-<home>-<away>-YYYY-MM-DD`, under tag 102232.
  Each event holds 3 binary markets: "Will <home> win on DATE?", "Will <match> end in
  a draw?", "Will <away> win on DATE?"  (outcomePrices = ["Yes","No"]; YES = the prob).
- **Totals & spreads:** in the sibling event `…-more-markets`. Totals are
  "<match>: O/U <line>" with outcomePrices = [P(over), P(under)]; lines 0.5–5.5.
  Use O/U 2.5 as the goal-total anchor. Spreads: "Spread: <team> (-1.5)". Also BTTS.
- **Group winner:** slug `world-cup-group-<a..l>-winner` (4 team binaries + "another").
- **Advance to knockout:** slug `world-cup-team-to-advance-to-knockout-stages`
  (48 team binaries; raw sum ≈ 31.7 → devig to 32 before comparing).
- **Reach final:** `world-cup-nation-to-reach-final`. **Outright:** `world-cup-winner`.

Name normalisation (Polymarket → canonical used in GROUPS): Korea Republic→South Korea,
United States→USA, Türkiye→Turkiye, Côte d'Ivoire→Ivory Coast, Curaçao→Curacao,
Cabo Verde→Cape Verde, IR Iran→Iran, Bosnia and Herzegovina→Bosnia-Herzegovina.
(Quirk: Curaçao once appeared with a "kor" code in a slug.)

## Method

1. Devig each match's 1X2 → P(home/draw/away).
2. Fit bivariate Poisson (lam1, lam2, lam3-shared) to P(home), P(away), and P(over 2.5).
   The 1X2 is the priority signal; totals only pin the goal level (the 3rd DOF).
3. Joint, vectorised Monte Carlo of all 12 groups; tiebreak = points → GD → goals →
   random (GD-first; the H2H-first variant lives in `wc2026_model.py`).
4. Rank the 12 third-place teams (points → GD → goals → random); best 8 advance.
5. model P(advance) = P(top2) + P(3rd ∧ best-8). Compare to devigged advance market.
6. Noise band: perturb fitted lambdas, re-sim; flag only if |edge|>4pp AND >2×noise.

## Current status (as of June 2026, pre-tournament)

- Pipeline runs end to end on live data; structural check passes (P(advance) sums to 32).
- Match 1X2 propagated → reproduces Polymarket's own group-winner market to ~1–2 pts.
  i.e. those markets are mutually coherent → no easy internal arbitrage there.
- Totals came in ≈ consistent with the 1X2 (correlation term ≈ 0 for most games), so
  adding them barely moved the model.
- v2 flags 5 teams (Saudi Arabia −6, Croatia +5, Canada +5, Qatar −5, Ivory Coast +4.5).
  They follow a **strength-ordered favorite-longshot pattern** (model > market for
  strong teams, < market for weak ones).
- **`sharp_compare.py` (external validation, done):** added DraftKings "to advance"
  odds (all 48 teams, ESPN-sourced, cross-checked vs FOX) as a 3rd price and ran a
  3-way: model vs Polymarket vs DraftKings, all devigged to 32. Then broke the
  PM-vs-DraftKings tie with **Pinnacle** prices (`--pinnacle`). Open problem CLOSED:
  Polymarket's advance market is sharp; there is NO edge (see below).

## The open problem — RESOLVED (flags are spec error; PM is sharp; no edge)

Three-way comparison gave a clean **extremeness ordering: MODEL > POLYMARKET > BOOK**
(model most favorite-longshot tilted, book most compressed). Two conclusions:

1. **The 5 flags are model-spec error, not edge.** |model − PM| ≈ a near-constant 5pp
   for all 5 flagged teams, always in the favorite-longshot direction. That constant
   offset tracking favorite/underdog status is the fingerprint of the independence
   assumption — the model just amplifies PM's view ~5pp, it doesn't discover anything.
   As an edge detector *vs Polymarket* the internal model is structurally useless.
2. **Model-free finding (PM vs DraftKings):** Polymarket priced underdogs LOWER
   (favorites HIGHER) than DraftKings — Saudi −12.8, Qatar −8.5, DR Congo −8.0,
   Ghana −6.4, NZ −5.8, Iraq −5.7 (PM − Book, pp). Open question was direction: PM soft
   (thesis) vs DraftKings biased (textbook favourite-longshot).
3. **TIE-BREAKER (Pinnacle, the true sharp) — resolves it: PM is fair, NO edge.**
   DIRECT market: Pinnacle "To Qualify From Group Stage" (= advance to R32, exact
   apples-to-apples) for the 5 underdogs, two-way devigged:
     Saudi 35.4 | Qatar 22.6 | DR Congo 44.3 | Ghana 49.6 | NZ 35.6 (%).
   vs Polymarket: Saudi 34.8 | Qatar 21.2 | DRC 43.4 | Ghana 51.4 | NZ 32.3.
   vs DraftKings: Saudi 47.6 | Qatar 30.7 | DRC 51.9 | Ghana 57.8 | NZ 38.0.
   **mean |Pinnacle − PM| = 1.6pp; mean |Pinnacle − DraftKings| = 7.7pp.** Pinnacle sits
   essentially ON TOP of Polymarket (Saudi differs 0.6pp). A proxy via the "Reach Last
   16" market (invert P(reach R16)/P(advance) → implied P(win R32|adv): 29.5%±2.9% under
   PM vs an implausible 23.7%±4.2% under DraftKings) gave the same answer independently.
   So **Pinnacle agrees with Polymarket**: Polymarket's advance prices are sharp, the
   PM-vs-DraftKings gap is DraftKings' recreational favourite-longshot bias (over-pricing
   underdogs), and the project thesis ("PM soft on long-range aggregates") is NOT
   supported for the advance market. Reproduce: `python3 sharp_compare.py --pinnacle`.

## Bottom line / where to go next

The advance market is a dead end for edge — Polymarket is at sharp (Pinnacle) prices
there, and the internal model can't beat PM (it's PM + amplification). Options if the
project continues: (a) accept the negative result and stop; (b) test a DIFFERENT
long-range aggregate where PM might still be soft and a sharp comparison is gettable
(outright winner, reach-final, top-scorer) — but expect the same "PM ≈ sharp" outcome;
(c) shift from cross-venue arb to in-tournament live mispricings. Don't re-litigate the
advance market without a NEW, direct sharp "to qualify" table.

**SCRAPING WALL (Jun 2026, don't re-discover):** true-sharp to-qualify prices are NOT
freely web-scrapable. Betfair / oddschecker / oddsportal all return 403/404 to a plain
fetch. Readable aggregators (ESPN, FOX) only republish the recreational DraftKings
table; covers.com is outright-only; thestatsapi is signup-walled; sportinglife group
previews are prose. The Pinnacle numbers used for the tie-breaker were read MANUALLY
off a Pinnacle account (reach-R16 two-way prices, hardcoded in `sharp_compare.py`).

## Don't

- Don't treat a flag as a signal while it rides the strength-ordered tilt — resolve the
  confound first.
- Don't read the internal model as an independent edge detector vs Polymarket: verified
  Jun 2026 against DraftKings that it is just PM + a ~5pp favorite-longshot amplification
  (the independence assumption). Edge work must be cross-venue (real price vs real price).
- Don't over-read DraftKings gaps for the super-favorites: the book floors at −10000, so
  Spain/Brazil/England/etc. all collapse to the same ~94% after devig — a granularity
  artifact, not disagreement. The signal is in the mid/underdog teams.
- Don't weight the totals residual equally with the 1X2 in the fit; it corrupts the
  result probabilities. The 1X2 is sacrosanct; totals only set the goal level.
- Don't calibrate team strength from the same aggregate market you then benchmark
  against — that's circular and will always show "no edge."
- Don't read the knockout / win-cup numbers from `wc2026_model.py` as precise: that
  bracket is randomised, not the official R32 third-place map.
- Don't forget the unmodeled effects: cross-match form correlation and dead-rubber
  rotation in the third group game.
- This is research tooling, not financial advice; Polymarket access/funding/tax in
  Norway has real frictions (state monopoly, payment blocking, 28% tax >10k NOK).
