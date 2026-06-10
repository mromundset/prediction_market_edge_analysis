# CLAUDE.md — Prediction-market edge analysis

Context brief for Claude Code. Read this first each session. Keep it updated: when a
correction is made, add a rule to the "Don't" section so it doesn't recur.

## What this project is

A collection of **explorations** hunting for *tradeable* mispricings on prediction
markets (primarily **Polymarket**). Each exploration lives in its own folder with its
own code, data, and a short `RESULTS.md` (question → second source used → verdict,
negative results included). Repo: folder-per-exploration; see `README.md`.

Guiding principle: a model calibrated *from* a market can never find an edge *against*
it. Every edge claim must be checked against a **second real source** — a sharper venue,
an objective ground-truth dataset, or a genuinely independent model.

## The economic bar — READ THIS BEFORE GETTING EXCITED

A price gap is not a strategy. Returns must be **annualized and net of all frictions**,
then clear two hurdles:

1. **Viability — beat the risk-free rate.** Annualized net return must exceed the
   risk-free rate of capital. Below that, T-bills/money-market win and there is no reason
   to take any risk. This is the floor, not the goal.
2. **Practicality — beat the index (~10%/yr).** To justify the effort, the locked-up
   capital, and the tail risk, the strategy must beat just buying the index. Treat **~10%
   annualized net** as the real go/no-go threshold.

Net return = gross edge − fees − **spread/slippage** − **capital-lockup cost** (you can't
touch the stake until the market resolves) − **tax/withdrawal frictions** (for this user:
Norwegian state monopoly, payment blocking, ~28% tax on gains >10k NOK).

Consequences that kill most "edges":
- **Annualize first.** Buying NO at 0.97 to make 0.03 is a 3.1% *gross* return; if the
  market runs a year that's ~3%/yr — fails both hurdles before frictions. The most
  lopsided prices pay the least.
- **Tail risk is real.** Shorting longshots is picking up pennies in front of a
  steamroller: many small wins, rare total loss. EV must clear the hurdle *after* pricing
  in the catastrophic outcome, not just on the modal path.
- **Liquidity ceiling.** An edge you cannot size is not a strategy. Sub-$15k order books
  (common in the interesting corners) cap deployable capital so low that even a real edge
  can't move the portfolio.

## How the Polymarket API works (hard-won — don't re-discover)

No API key needed. Always send a `User-Agent` header (a bare request can 403).

### Gamma API — metadata + current prices  `https://gamma-api.polymarket.com`
- `/markets?active=true&closed=false&limit=100&offset=N` — flat list of markets.
- `/events?active=true&closed=false&limit=100&offset=N&order=volume24hr&ascending=false`
  — events with **`tags` AND `markets` embedded inline**. This is the efficient
  single-scan path for whole-market sweeps (no per-event follow-up needed).
- `/events/slug/<slug>` — one event (sometimes returns a 1-element list).
- **Pagination:** page size caps at 100; loop `offset` until an empty batch (Polymarket
  has ~8–9k active events, so allow a high stop).
- **`outcomePrices` is a JSON-encoded STRING** (e.g. `'["0.29","0.71"]'`), not a list —
  `json.loads` it. For a binary Yes/No market, index `[0]` is the YES price = implied
  probability. `outcomes` is likewise often a JSON string; binary markets are
  `["Yes","No"]`.
- **Trade at the book, not the mid.** Use `bestBid` / `bestAsk` / `spread`, not just
  `outcomePrices`. The ask is what you actually pay; the spread is a real cost. A wide
  spread can manufacture a fake "edge" out of the midpoint (seen on thin meteor markets).
- **Useful fields:** `volume`/`volumeNum`, `volume24hr`, `liquidityNum` (order-book
  depth — the sizing limit), `endDate`/`endDateIso` (→ days-to-resolve, for annualizing),
  `createdAt`, `conditionId` (dedupe key), `clobTokenIds`, and **`description`** (the
  exact resolution criteria — read it, see rule 6).
- **Exclude sports** by checking each event's tag slugs against a sports set
  (`sports, soccer, nfl, nba, mlb, nhl, ufc, tennis, golf, cricket, f1, …`).

### CLOB API — historical price time series  `https://clob.polymarket.com`
- `prices-history?market=<clobTokenIds[0]>&interval=max&fidelity=1440` → daily YES-price
  history (`fidelity` is in minutes; 1440 = daily). Use the **YES** token id
  (`clobTokenIds[0]`).
- Use it to study price evolution, time decay, and to back out the market-implied rate
  over time (e.g. `λ = −ln(1−p)·365/days_left` for a "≥1 event in the year" market).

### Devig (compare like-for-like)
- **Proportional:** rescale a multi-outcome market so values sum to the true total
  (1.0 for a 3-way; N for an "N advance" market).
- **Two-way:** from decimal odds, `P(yes) = (1/yes_dec) / (1/yes_dec + 1/no_dec)`.
- **American → prob:** `(-a)/(-a+100)` if a<0 else `100/(a+100)`.
- Always devig **every** venue to the **same** total before comparing, and only compare
  **identical market definitions** (e.g. "advance to R32" ≠ "reach the Round of 16").

### Objective ground-truth sources (for non-sports markets)
When a market resolves on a public dataset, that dataset — or a physical/statistical
model of it — is your second price. Example used here: NASA/CNEOS Fireball API
(`https://ssd-api.jpl.nasa.gov/fireball.api`, field `impact-e` = impact energy in kt),
plus the Brown et al. (2002/2013) bolide impact-flux power law for the data-starved tail.

## The rules for finding edges (methodology)

1. **A model built FROM a market can't detect edges AGAINST it** — it just re-expresses
   the market's view, usually amplified. Edge detection needs a *second real price*.
2. **Monotonic-with-status "edges" are a red flag.** An apparent edge that grows smoothly
   with favorite/underdog status is almost always a structural artifact (e.g. an
   independence assumption, or the favorite–longshot bias), not a real mispricing.
3. **Resolve model-vs-market with a THIRD price.** Lay model, Polymarket, and a book side
   by side; the outlier is the one that's wrong.
4. **Sharp hierarchy.** Pinnacle & Betfair Exchange = true sharps (low margin, ≈ fair).
   DraftKings/FanDuel/etc = recreational — they over-price underdogs (favorite–longshot
   bias). Polymarket, when liquid, sits at sharp value. Never use a recreational book as
   the arbiter of "fair."
5. **READ THE RESOLUTION TEXT** (`description`). Soft/ambiguous criteria mean part of the
   price is *resolution risk*, not belief — so it is not a mispricing. (E.g. "US confirms
   aliens" resolves on *any* official statement, not on aliens existing; that's why YES
   sat at 13.5%.)
6. **Lopsidedness is inversely correlated with profit.** The most extreme prices (YES
   ~0.1%) pay essentially nothing. Score candidates by **annualized net return**, not by
   how lopsided they look; the action is in a mid-band.
7. **For rare events, test against the base-rate CONFIDENCE INTERVAL.** If the
   market-implied rate falls inside the empirical CI, there is no *statistically
   significant* edge no matter how large the point-estimate gap looks. (Short physical
   records give very wide CIs at the tail.)
8. **Where Polymarket is liquid, expect ≈ sharp pricing.** Prior from every exploration
   so far. Hunt instead in illiquid/novel corners, live/in-play reaction speed, or
   objective-resolution markets where a better model beats the crowd — but always respect
   the liquidity ceiling and the economic bar above.

## Prior results (explorations done — don't re-litigate without a new angle)

- **`lopsided_market_scan/`** — shorting "impossible" meme events. The genuinely-absurd
  universe is tiny: clean impossibles (e.g. "Jesus returns", YES ~2%) pay ~4%/yr → fail
  both hurdles; the ones that pay (aliens 13.5%) pay for *resolution ambiguity*, not edge.
- **`meteor_strike_edge_exploration/`** — Polymarket meteor ladder vs the CNEOS record and
  the Brown impact-flux model. Market is well-calibrated to physics: the tail
  "overpricing" matches the modern Brown-2013 flux; the only persistent lean (5/10 kt YES
  mildly underpriced) is within the base-rate CI and capped by <$15k liquidity. No
  sizeable edge.
- **Bottom line so far:** Polymarket is efficient at every testable corner; nothing has
  cleared the risk-free, let alone the index, hurdle.

## Environment

Python 3, `numpy`, `scipy`, `matplotlib`, internet access. No API key. Each exploration is
a self-contained folder; run scripts from inside their folder. Generated bulk data (e.g.
the full market dump) is git-ignored and regenerated by the folder's fetch script.

## Don't

- Don't get excited by a *gross* return — annualize it and net out fees, spread, lockup,
  and tax, then check it against the risk-free and ~10% index hurdles before anything else.
- Don't quote a mid-price "edge"; quote the `bestAsk` and the `spread`, and check
  `liquidityNum` — thin books turn the midpoint into a mirage.
- Don't read an internal model as an independent edge detector vs the market (it's the
  market's view + amplification). Edge work must be real-price vs real-price.
- Don't treat an edge that rides the favorite–longshot tilt as signal — resolve the
  confound with a real second price first.
- Don't ignore the resolution wording; soft criteria masquerade as mispricings.
- Don't call a rare-event gap an edge if the market-implied rate is within the base-rate
  confidence interval.
- Don't calibrate a quantity from the same market you then benchmark against — circular,
  always shows "no edge" (or a fake one).
- This is research tooling, **not financial advice**; Polymarket access/funding/tax in
  Norway has real frictions (state monopoly, payment blocking, ~28% tax on gains >10k NOK).
