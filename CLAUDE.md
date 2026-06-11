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

**Fees (current — the 0% era ended early 2025).** Maker = **0** (+ ~25% rebate of taker
fees). Taker = `C · feeRate · p · (1−p)` per share, i.e. effective `feeRate · (1−p)` on
the YES leg, maximal near p=0.5, ~0 at the extremes. `feeRate` by category: **Crypto 0.07,
Econ/Culture/Weather 0.05, Finance/Politics/Tech 0.04, Sports 0.03, Geopolitics 0
(fee-free)**. Trading is gasless (relayer-paid); no deposit/withdrawal fees. → Resting as a
**maker is nearly free**; crossing the book on a crypto market near 50/50 costs up to ~1.8%.
Settlement is the UMA optimistic oracle: ~2h if uncontested, but **days of lock-up + tail
risk of adverse/ambiguous resolution** on subjective markets — prefer objective, data-resolved ones.

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
  history (`fidelity` is in minutes; 1440 = daily, **10 = intraday** for short-dated markets).
  For a fixed window pass `&startTs=<unix>&endTs=<unix>` instead of `interval`. Use the
  **YES** token id (`clobTokenIds[0]`). History is mid-quote only (no historical order book).
- Use it to study price evolution, time decay, and to back out the market-implied rate
  over time (e.g. `λ = −ln(1−p)·365/days_left` for a "≥1 event in the year" market).
- **Recurring "ladder" products** (tag `multi-strikes`=102516): daily/weekly `<coin>-above-
  on-<month>-<d>-2026` events, ~11 strikes each, resolve on a fixed exchange candle (e.g.
  BTC = Binance BTC/USDT 12:00 ET close). Closed events + outcomes are queryable for backtests.

### Devig (compare like-for-like)
- **Proportional:** rescale a multi-outcome market so values sum to the true total
  (1.0 for a 3-way; N for an "N advance" market).
- **Two-way:** from decimal odds, `P(yes) = (1/yes_dec) / (1/yes_dec + 1/no_dec)`.
- **American → prob:** `(-a)/(-a+100)` if a<0 else `100/(a+100)`.
- Always devig **every** venue to the **same** total before comparing, and only compare
  **identical market definitions** (e.g. "advance to R32" ≠ "reach the Round of 16").

### Second-price sources (free APIs, verified)
When a market resolves on a public dataset/venue, that dataset — or a sharper market — is
your second price:
- **Objective datasets:** NASA/CNEOS Fireball API (`ssd-api.jpl.nasa.gov/fireball.api`,
  field `impact-e` = kt), + Brown et al. (2002/2013) impact-flux power law for the tail.
- **Crypto digitals → Deribit options** (deep sharp). Public REST `deribit.com/api/v2`
  (live) and `history.deribit.com/api/v2` (expired-option **trades with per-trade IV**;
  expiry token format `1JUN26`, not `01JUN26`). European cash-settled → digital
  `P(S>K)=N(d2)`; or model-free Breeden–Litzenberger `−∂C/∂K`. Gotcha: PM's resolution
  clock/index ≠ Deribit's 08:00 UTC expiry — interpolate total variance to PM's exact time.
- **Crypto-price index** for resolution: Binance klines `api.binance.com/api/v3/klines`.
- **Kalshi** (CFTC venue) — free no-auth market data `api.elections.kalshi.com/trade-api/v2`;
  prices are already 0–1. Direct PM↔Kalshi cross-venue compare (match on *resolution text*).
- **Fed/rates → CME FedWatch / ZQ fed-funds futures** (self-compute via `pyfedwatch`).
- **Sports sharps** (Pinnacle/Betfair) are scraping-walled / API-shut (Jul-2025); paid resellers only.

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
- **`STRATEGY_CANDIDATES.md` + `strategy_research/`** — PhD-quant strategy enumeration vs
  the literature (liquid PM is sharp; the only large *documented* edge is bot-captured
  internal/NegRisk arbitrage, $39.6M/yr, ~99% uncaptured). Ranked shortlist:
  A1 crypto-vs-Deribit (tested↓) > A2 Kalshi cross-venue > B4 market-making/B3 arb-bot
  (need latency infra) > B5 Fed-vs-FedWatch (marginal); C-tier (favorite-longshot, theta,
  news-latency, ladder-arb) all fail the bar.
- **`crypto_deribit_edge_exploration/`** — A1 backtest, full daily-product history (40
  BTC/ETH events, 913 obs). **FAILED:** the live 3–6pp "gap" was a measurement artifact
  (settlement-clock + nearest-strike IV); correctly measured (smile fit + total-variance
  interp to PM's resolution) the body gap is ~1pp (inside spread+fee); Brier(model)≈Brier(PM)
  — Deribit is **not** a sharper forecaster of these prints; biggest gaps were model error;
  no config significant (|t|<1). 20 days = one regime (don't over-conclude, but no go).
- **`kalshi_cross_venue_exploration/`** — A2 (PM↔Kalshi cross-venue arb). **FAILED:** Kalshi
  is ~60k zero-liquidity sports parlays + a thin macro overlap (~6%). Crypto overlap is NOT
  fungible (Kalshi=CF BRTI @5pm EDT vs PM=Binance @noon ET) and one-sided-empty. The one
  deep matched overlap (FOMC decision; Kalshi resolves on the Fed, like PM) is efficient to
  ~1pp; best executable arb net of *both* fee schedules = +0.1¢ → 0.8%/yr (unsizeable tail);
  liquid buckets net-negative. Two-sided fees + months lockup + fragile Norway Kalshi access.
  Kalshi data API (free, no auth): `api.elections.kalshi.com/trade-api/v2`; series→events→
  markets; `yes_bid/ask_dollars` already 0–1; `rules_primary`+`settlement_sources` for
  semantic matching; quadratic fee ~0.07·p·(1−p).
- **`internal_arb_exploration/`** — B3 (internal/NegRisk Dutch-book arb). **FAILED for a
  non-latency player:** live both-leg scan of 1,005 binary complete-sets — `ask(YES)+ask(NO)`
  min 1.001/median 1.002 (never <$1), bid-sum never >$0.999; books bot-coherent to the tick.
  37/40 NegRisk MECE Dutch-books unexecutable (a leg has no NO ask). Zero positive-net arb.
  The documented $39.6M/yr is captured in ms by bots; nothing left at REST-snapshot speed.
  CLOB books: POST `clob.polymarket.com/books` with `[{token_id}]` → both legs' depth.
- **Bottom line so far:** Polymarket is efficient at every testable corner; nothing has
  cleared the risk-free, let alone the index, hurdle. The recurring failure mode is an
  apparent gap that **dies on correct, settlement-aligned, like-for-like measurement.**

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
- Don't trust a snapshot "gap" vs a second venue until it's measured **like-for-like**:
  same resolution clock/index, vol interpolated to the *exact* resolution time, smile-fit
  (not nearest-strike) IV, and net of spread+fee. A1's 3–6pp gap evaporated to ~1pp this way.
- Don't read a profitable backtest leg as edge if it coincides with a one-directional spot
  move over a short window — that's shared directional luck, not forecasting skill (check
  realized base rate vs *both* venues, like the A1 drift check).
- This is research tooling, **not financial advice**; Polymarket access/funding/tax in
  Norway has real frictions (state monopoly, payment blocking, ~28% tax on gains >10k NOK).
