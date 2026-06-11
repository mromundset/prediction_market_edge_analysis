# Polymarket Strategy Candidates — research memo

*Author: quant research pass, June 2026. Status: hypothesis catalog for testing, not
validated PnL. Every return figure below is a rough, pre-backtest estimate with wide error
bars; treat them as priorities for what to build and measure, not as expected value.*

This memo enumerates candidate trading strategies on Polymarket, scores each against the
project's economic bar (**beat the risk-free rate to be viable; beat the index, ~10%/yr
net, to be worth doing**), and proposes what to build/measure next. It is grounded in (a)
a full live scan of 8,748 active events, (b) a live Deribit-vs-Polymarket proof of concept,
(c) Polymarket's current fee/reward/oracle mechanics, and (d) the 2025–2026 academic
literature on prediction-market efficiency. Supporting code is in `strategy_research/`.

---

## 0. Ranked shortlist (the answer up front)

| # | Strategy | Rough net annualized* | Capacity | Build effort | Verdict vs ~10% bar |
|---|---|---|---|---|---|
| **A1** | **Crypto digitals vs Deribit options** | ~~15–30%?~~ **≈0 (backtested)** | $ med ($0.5–2M/event) | Automation + options math | **TESTED → FAILED — see `crypto_deribit_edge_exploration/`** |
| **A2** | PM ↔ Kalshi cross-venue arb | ~~5–20%~~ **≈0.8% (backtested)** | $ low–med | Two-venue plumbing | **TESTED → FAILED — see `kalshi_cross_venue_exploration/`** |
| **B3** | Internal NegRisk / YES+NO Dutch-book | ~~risk-free/trade~~ **0 at snapshot speed (tested)** | $ high in aggregate | Low-latency bot | **TESTED → FAILED (no non-latency residual) — see `internal_arb_exploration/`** |
| **B4** | Liquidity provision + LP rewards | 10–30%? (unverified, bot-contested) | $ high | 24/7 maker bot | Plausible but operationally heavy |
| **B5** | Fed markets vs CME FedWatch (ZQ) | 5–10%, intermittent | $ med ($5M/event) | Rate math + alerts | Marginal; mostly monitoring |
| C6 | Favorite–longshot directional harvest | < risk-free after spread | — | Low | **No** (confirmed dead) |
| C7 | Theta / near-certain time-decay | ~3–5% | $ low | Low | **No** (fails bar) |
| C8 | News-latency / event-driven | n/a manually (half-life <1 min) | $ low | Pro infra | **No** without HFT stack |
| C9 | Date-ladder monotonicity arb | risk-free but negligible $ | $ tiny | Low | **No** (no capacity) |
| D10 | Crypto ladder RND / butterfly arb | folds into A1 + rare structural | $ low | Med | Test alongside A1 |
| D11 | Idle-collateral yield (not an edge) | raises the floor | — | — | Use to lift net return |
| D12 | Geopolitics fee-free expression | speculative | $ med | Med | Watch-list only |

\* Net of the dynamic taker fee, spread, and capital turnover; **before** Norway tax (28%
on gains >10k NOK) and withdrawal frictions, which apply on top and are often larger than
trading costs. "?" = the estimate rests on an unvalidated measured gap.

**One-line thesis of this memo:** the weight of evidence — our own World-Cup/meteor
negative results *and* the 2025–26 literature — is that liquid Polymarket is sharp and the
only large, documented edges are **infrastructure-driven** (internal arbitrage and
market-making captured by bots), not modeling/forecasting edges. The realistic path to a
>10% net return for a semi-automated operator is a **cross-reference divergence engine**
(A1 crypto-vs-Deribit first, A2 Kalshi second), *if* an automated pipeline is built and the
measured gaps survive rigorous validation.

---

## 1. The bar and the annualization framework

A price gap is not a return. The figure that must clear the hurdle is:

```
net annualized ≈ (edge_per_trade / capital_tied_up) × turnover_per_year
                 − fees − spread − slippage − (tax, withdrawal frictions)
```

Two implications dominate the rankings:

1. **Turnover is everything.** A 3pp edge on a market that resolves in **1 day** and
   recycles capital ~daily annualizes enormously; the *same* 3pp edge on a market that
   resolves in **2 years** (most election/geo markets) annualizes to ~1.5%/yr — below the
   risk-free rate. This is why short-dated crypto/Fed/weather markets dominate the
   shortlist and long-dated political aggregates (despite being the deepest, most liquid
   markets on the platform) are structurally useless for this strategy even if mispriced.
2. **Capital that can't be deployed at size is not a strategy.** The genuinely inefficient
   corners are inefficient *because* they are illiquid (literature is unanimous on this),
   so realized dollars are liquidity-capped regardless of percentage edge.

**Fees (current, post-2025 — the 0% era is over).** Maker = 0 (and makers earn a ~25%
rebate of taker fees). Taker fee = `C · feeRate · p · (1−p)` per share, i.e. effective
`feeRate · (1−p)` on the YES leg, maximal near p=0.5, ~0 at the extremes. `feeRate` by
category: **Crypto 0.07, Econ/Culture/Weather 0.05, Finance/Politics/Tech 0.04, Sports
0.03, Geopolitics 0 (fee-free)**. Trading is gasless (relayer-paid); no deposit/withdrawal
fees. → **Resting as a maker is nearly free; crossing the book on a crypto market near 50/50
costs up to ~1.8%** and must be subtracted from any taker-side edge.

**Settlement risk.** UMA optimistic oracle: ~2h liveness if uncontested, but **days of
capital lock-up and tail risk of an adverse/ambiguous resolution** on subjectively-worded
markets (documented 2025–26 controversies incl. a $60M+ MicroStrategy dispute). Objective,
data-resolved markets (crypto price off an exchange candle, Fed decisions, fireball energy)
are low-risk here; vaguely-worded ones are not.

---

## 2. Empirical landscape (what the live scan shows)

From `scan_markets.py` / `analyze_snapshot.py` over 8,748 active events (5,838 non-sports):

- **Where deployable depth actually is (non-sports, order-book liquidity):** 2028 election
  nominee/winner markets ($66M / $46M / $36M — but multi-year horizon, useless per §1),
  global elections (Peru/France/Brazil/Colombia, $4–11M each), **geopolitics** (Iran $7.8M;
  fee-free), **Fed Decision in June $4.8M liq / $79M vol**, AI-model markets ($3.8M), crypto
  price ladders ($0.5–2M/event), commodities, daily temperature.
- **Spreads in liquid markets are tight:** for non-sports binaries with >$50k volume,
  median best-spread = **0.2pp**, p75 = 1pp, p90 = 3pp. So in markets where you can size,
  costs are low — but those are also the efficient markets. Wide spreads (1,300–1,800 bps)
  live in the sub-10% longshot tail (Dubach 2026), which is exactly where naive
  "longshot overpricing" gets eaten by the spread.
- **Internal coherence is mostly closed on mids:** proper NegRisk (MECE) events have median
  |∑YES − 1| = **3.9pp**; the eye-popping "∑YES = 16" cases are **non-MECE nested ladders**
  ("BTC hits $X" for many X are not mutually exclusive), not arbitrage. The real Dutch-book
  ($10.6M/yr, below) lives at the **order-book (ask) level** and is captured in seconds by
  bots, not findable on mids.
- **Richest sharp-comparable veins:** **1,822 crypto price binaries** across 190 events
  (incl. *daily* "BTC above $X" markets → Deribit), and a cluster of **Fed/rates markets**
  → CME FedWatch/ZQ.

---

## 3. Strategy catalog

### Tier A — most promising (clean independent second price, free data, plausibly >10%)

#### A1. Crypto digital markets vs Deribit options-implied probability *(flagship)*

- **Thesis.** Polymarket's "Will BTC/ETH be above $X on DATE?" and price-ladder markets are
  digital options priced by a retail crowd. Deribit is the deep, sharp crypto-options venue.
  Where PM's implied probability diverges from the options-implied probability beyond
  fees+spread, take the cheaper side.
- **Second price.** Deribit public REST (free, no key). European, cash-settled → the
  Black-76 digital `P(S>K) = N(d2)` is exact; or model-free Breeden–Litzenberger
  `P(S>K) ≈ −∂C/∂K` from adjacent call marks. (`deribit_poc.py`.)
- **Evidence (live PoC, BTC, 11-Jun expiry).** Near-the-money, **PM sat 3–6pp above** the
  options-implied prob ($60k: PM 87.5% vs Deribit 81.2%; $62k: 37.5% vs 33.9%), mean |gap|
  1.8pp across strikes, with a clear structural shape (PM over-prices the body). The
  literature (Le 2026) independently finds Crypto calibration slope 1.05 (mild longshot
  tilt), consistent with PM over-pricing mid-body "above" probabilities.
- **Rough return.** The *raw* gap implies very high per-trade EV (e.g. buying NO at 0.125
  when fair ≈ 0.19 is +50% on a ~1-day hold). **That is almost certainly overstated** by
  (i) nearest-strike IV instead of smile interpolation, (ii) the 8-hour settlement mismatch
  (PM = Binance 12:00 ET close; Deribit = 08:00 UTC TWAP), (iii) different reference index.
  After a validation haircut, smile-correct measurement, and realistic capacity:
  **preliminary target 15–30%/yr**, but with a real chance the true edge is near zero once
  artifacts are removed. Crypto taker fee (~0.9pp NTM) and ~0.5pp spread are affordable
  against a multi-pp gap; capital recycles weekly/daily → high annualization if real.
- **Capacity / liquidity.** $0.5–2M order-book per crypto event; daily + weekly + ladder
  markets across BTC/ETH/SOL/XRP → genuinely sizeable for a small book.
- **Infra.** Deribit chain snapshot + smile interpolation (in variance) + PM resolution-time
  alignment + an execution loop. Moderate. Optional: hedge the residual on Deribit (needs a
  Deribit account; crypto-native, generally accessible from Norway with KYC).
- **Key risks.** Settlement-clock/index mismatch is the dominant execution risk; smile
  mis-estimation; the gap shrinking to noise after correct measurement; crypto fee.
- **Validation (do this first).** Re-run the PoC with (1) full smile interpolation, (2) T to
  the *exact* PM resolution candle, (3) the same reference index PM uses, then (4)
  out-of-sample backtest over ≥60 daily markets, paper-trading the rule, measuring realized
  edge net of fees/spread. Go/no-go on whether the structural gap survives.
- **Verdict.** **Build and validate first.** Best combination of clean sharp + free data +
  high turnover + real liquidity in the catalog.
- **POST-TEST UPDATE (2026-06-11): FAILED validation.** Full-history backtest (40 events,
  913 observations, smile-interpolated + settlement-aligned, net of costs) in
  `crypto_deribit_edge_exploration/RESULTS.md`: the live 3–6pp gap was a measurement
  artifact; the true body gap is ~1pp (inside spread+fee); Brier(model) ≈ Brier(PM) — the
  options market is *not* a better forecaster of these resolutions; the largest gaps were
  model error (0-for-4 on high-conviction trades); no configuration is significant
  (all |t| < 1). Revisit only per the conditions in that RESULTS.md.

#### A2. Polymarket ↔ Kalshi cross-venue arbitrage

- **Thesis.** The *same* contract (Fed decisions, CPI/NFP prints, some elections) trades on
  both venues; both quote native 0–1 probabilities. When the same-definition contract
  diverges beyond combined spreads, arb it.
- **Second price.** Kalshi public market-data REST (free, no key) — `yes_bid/ask_dollars`
  are already probabilities; compare directly to PM mid, check gap > PM spread + Kalshi
  spread + fees.
- **Evidence.** Gebele & Matthes (2026): only ~6% of contracts are cross-platform fungible;
  on those, execution-adjusted spreads average ~3¢ and the gaps that persist ≥30 min are
  largely capital-frictioned (semantic non-fungibility — *different resolution wording* — is
  the trap, and exactly the failure mode our World-Cup work warned about).
- **Rough return.** ~2–4¢ per matched contract, frequency- and capacity-limited;
  **5–20%/yr** on the matched sleeve at best.
- **Capacity / infra.** Low–medium; needs two-venue capital and plumbing.
- **Key risks.** (1) Resolution-semantics mismatch — must verify *identical* resolution
  before treating as arb. (2) **Kalshi access from Norway is currently open but regulatorily
  fragile** (Spain/Germany already restricted) — funding could vanish. (3) Capital split
  across venues.
- **Validation.** Build a contract-matcher that pairs PM↔Kalshi on *resolution text*, not
  title; log persistent (>30 min) gaps net of both spreads for a month; confirm Norway
  Kalshi funding works *before* committing capital.
- **Verdict.** **Second to build.** Cleanest "no-model" play, but access-fragile and
  capacity-capped.
- **POST-TEST UPDATE (2026-06-11): FAILED validation.** Full overlap map + FOMC arb
  computation in `kalshi_cross_venue_exploration/RESULTS.md`: the matched-and-liquid
  intersection is tiny (~6% overlap, mostly Fed); the crypto overlap is **not fungible**
  (Kalshi=CF BRTI @5pm vs PM=Binance @noon) and one-sided-empty; the one clean deep match
  (FOMC decision) prices both venues within ~1pp on liquid buckets, and the best executable
  arb net of *both* venues' fees is +0.1¢ → 0.8%/yr (unsizeable tail bucket); every liquid
  bucket is net-negative after fees. Two-sided fees + months-long lockup + fragile Norway
  Kalshi access sink it.

### Tier B — structurally sound but infra- or capacity-limited

#### B3. Internal NegRisk / single-condition Dutch-book

- **Thesis.** When YES+NO < $1 (buy both, redeem $1) or a complete MECE set's prices sum off
  1, there is near-risk-free arbitrage; NegRisk's convert mechanic enables capital-efficient
  multi-outcome baskets.
- **Evidence.** IMDEA (arXiv:2508.03474): **$39.6M extracted Apr-24→Apr-25** —
  NegRisk $29M, single-condition YES+NO≠$1 $10.6M (median **$0.60 profit per dollar**),
  cross-market only $94k. **But ~99% of opportunities go uncaptured and the captured slice
  is taken by a handful of bots in seconds.** Our scan confirms mids are coherent (NegRisk
  median 3.9pp) — the money is at the ask, fleetingly.
- **Rough return.** Per-trade near-risk-free, but **~0 without low-latency infra**; with a
  competitive bot, plausibly 10–30% on actively cycled capital — against entrenched bots.
- **Infra.** Low-latency CLOB streaming + auto-execution + (for NegRisk) the convert/mint
  path. High build, gasless helps.
- **Verdict.** **Only with a latency bot.** Not a manual/modeling play; it's an engineering
  race.
- **POST-TEST UPDATE (2026-06-11): FAILED for a non-latency player.** Live both-leg
  order-book scan (1,005 binary complete-sets + 40 NegRisk MECE sets) in
  `internal_arb_exploration/RESULTS.md`: **zero** positive-net arbs — `ask(YES)+ask(NO)`
  min 1.001/median 1.002 (never <$1), bid-sum never >$0.999; 37/40 Dutch-books unexecutable
  (a leg has no NO ask). Books are bot-coherent to within the tick; the $39.6M is captured
  in ms. No snapshot-speed/analysis edge — pursuing it = building colocated execution to
  out-race entrenched bots.

#### B4. Liquidity provision + LP rewards (market-making)

- **Thesis.** Quote tight two-sided, earn the spread + 0 maker fee + 25% taker rebate + the
  liquidity-rewards pool. Reward score is quadratic in tightness × size × uptime.
- **Evidence.** **$12M LP rewards paid in 2025; >$5M allocated April 2026** (concentrated in
  sports/esports; the `earn-4` flagship election markets are reward-boosted). Historical
  peak anecdotes (700%+ APR) are gone; the program is now bot-competitive and a current
  realistic APR could **not** be verified.
- **Rough return.** **10–30% on actively-managed capital** in well-chosen markets is a
  plausible (unverified) planning range, dominated by inventory/adverse-selection risk.
- **Infra.** 24/7 quoting bot with inventory and news risk controls; high operational load.
- **Key risks.** Adverse selection (run over on news), inventory risk, reward dilution as
  more makers enter, the unverified APR.
- **Verdict.** **Plausible income stream, heavy to operate.** Best in objective/short-dated
  markets where adverse selection is bounded; pair with B5/A1 markets you already monitor.

#### B5. Fed-rate markets vs CME FedWatch / ZQ futures

- **Thesis.** "Fed Decision in MONTH" / "how many cuts in 2026" map near-exactly to fed
  funds futures-implied probabilities. Edge when PM lags ZQ intraday around data/Fed-speak,
  or misprices compound multi-cut markets.
- **Second price.** Self-compute from ZQ futures (free; `pyfedwatch` replicates CME
  methodology) or paid CME FedWatch API.
- **Evidence.** "Fed Decision in June" is liquid ($4.8M liq / $79M vol). ZQ is among the
  most efficient markets on earth and FedWatch is widely watched → single-meeting PM markets
  usually pinned to it; the compound "how many cuts" markets carry more error.
- **Rough return.** **5–10%/yr, intermittent** — mostly an alerting play around FOMC/CPI
  windows; occasionally a clean gap on compound markets.
- **Verdict.** **Marginal; build the FedWatch feed anyway** (cheap, reusable, also feeds A2
  and B4 market selection).

### Tier C — documented-negative or inaccessible (catalogued so we don't re-explore)

- **C6. Favorite–longshot directional harvest.** Slope 1.05–1.31 (Le 2026) is *modest* and
  the apparent longshot overpricing is eaten by the 1,300–1,800 bps longshot spread (Dubach
  2026); our WC and meteor work already confirmed PM ≈ sharp. **< risk-free after costs. No.**
- **C7. Theta / near-certain time-decay.** Our meme scan: clean near-impossible NO shorts pay
  ~4%/yr. **Fails the bar** unless short-dated, where it collapses into A1/B5. **No.**
- **C8. News-latency / event-driven.** Arbitrage half-life fell to **<1 minute** in liquid
  markets (Tsang & Yang 2026). **Not accessible without a professional HFT stack. No** for a
  semi-automated operator.
- **C9. Date-ladder logical-consistency arb** ("by June" ≤ "by July"). Real but only $94k
  captured industry-wide, liquidity-bounded. **Risk-free but no capacity. No.**

### Tier D — novel angles worth a look

- **D10. Crypto ladder RND / butterfly arbitrage.** ~~Within a "BTC above $X" ladder, the
  implied probabilities must be monotone and the implied risk-neutral density non-negative
  (`P(>K−Δ) − 2P(>K) + P(>K+Δ) ≥ 0`). Butterfly violations are model-free arbitrage; and the
  PM-implied RND can be diffed wholesale against the Deribit RND. **Combines A1 + C9 in the
  richest vein.** Test alongside A1; structural arbs are rare/bot-contested but free to scan.~~
  **TESTED → FAILED — see `crypto_ladder_d10_exploration/RESULTS.md`.** Key corrections:
  the butterfly condition is a no-arb rule for *vanilla calls*, NOT binary digital options —
  the only applicable condition is monotonicity. Historical test (47k pair-snapshots): 0.29%
  mid-price violations, median 0.1pp, transient (<10 min, bot-corrected), not actionable.
  Live order-book test: zero executable arbs at meaningful size (the one violation found was
  0.18% net on a deep-ITM near-expiry market with near-zero depth). RND shape comparison (415
  buckets, 40 events): PM and Deribit agree on distribution shape to within noise (mean diff
  0.06pp). No tradeable edge.
- **D11. Idle-collateral yield (not an edge, a floor-raiser).** Polymarket's reward-boosted
  (`earn-4`) structure and any USDC yield on idle collateral raise the *opportunity-cost
  floor*: park undeployed collateral productively so the strategy's hurdle is measured
  against actual idle yield, not zero. Investigate the current "earn" mechanics; fold into
  net-return accounting.
- **D12. Geopolitics fee-free expression.** Geopolitics has **0 taker fee** and deep volume
  ($537M). If any short-horizon, data-resolvable geopolitical edge appears (e.g. a sharp
  second source for a specific event), it is cheapest to express here. Speculative;
  watch-list only — most geo markets are long-dated (fails §1) or resolution-ambiguous.

---

## 4. Cross-cutting risks (apply to all of the above)

1. **The edge may be a measurement artifact** (settlement clock, smile, index basis,
   resolution wording). Every cross-reference strategy must be backtested net of these before
   capital. This is the single most likely way to fool ourselves — and the exact lesson of
   the WC and meteor explorations.
2. **Liquidity ceiling** caps deployable dollars in precisely the inefficient corners.
3. **Norway frictions**: 28% tax on gains >10k NOK and funding/withdrawal hurdles apply on
   top of all figures and can exceed trading costs; Kalshi access is regulatorily fragile.
4. **Oracle/settlement tail risk** on subjectively-worded markets and days-long lock-up on
   disputes — prefer objective, data-resolved markets.
5. **Bot competition** in B3/B4 is an arms race; assume returns compress.

---

## 5. Recommended build order

1. ~~**A1 validation harness**~~ **DONE (2026-06-11) → NO-GO.** The measured 3–6pp body
   gap did not survive correct measurement; see `crypto_deribit_edge_exploration/`.
2. ~~**D10 scanner**~~ **DONE (2026-06-11) → NO-GO.** Monotonicity violations are transient
   (bot-corrected), the butterfly condition was wrong for digitals, and RND shapes agree
   to within noise; see `crypto_ladder_d10_exploration/`.
3. ~~**A2 contract-matcher** (Kalshi)~~ **DONE (2026-06-11) → NO-GO.** Overlap is tiny and
   the one deep match (FOMC) is efficient to within fees; see `kalshi_cross_venue_exploration/`.
4. **B5 FedWatch feed** (cheap, reusable infra) feeding market selection for A2/B4.
5. Only if 1–4 underwhelm: evaluate the engineering investment for **B3/B4** (latency bot /
   24-7 maker) against expected, bot-compressed returns.

**Honest prior:** given our own two negative results and the literature's consensus that
liquid PM is sharp and edges are bot-captured, the base-rate expectation is that A1's gap
shrinks under correct measurement and that no purely-modeling strategy clears ~10% net. The
program is worth running because A1 is *cheap to falsify* and, if even part of the measured
crypto gap survives, its turnover makes it the one realistic path over the bar.

---

## 6. Sources

- Fees / rewards / NegRisk / oracle / access: Polymarket docs (`docs.polymarket.com/trading/fees`,
  `/market-makers/liquidity-rewards`, `/advanced/neg-risk`, `/concepts/resolution`,
  `/api-reference/geoblock`).
- Le (2026), *Decomposing Crowd Wisdom* — arXiv:2602.19520 (calibration by domain).
- Tsang & Yang (2026) — arXiv:2603.03136 & 2603.03152 (efficiency, news half-life).
- Dubach (2026) — arXiv:2604.24366 (order-book spreads).
- Saguillo et al. / IMDEA (2025), *Arbitrage in Prediction Markets* — arXiv:2508.03474 ($39.6M).
- Cheng, Yang & Zou (2026) — arXiv:2605.00864 (NBA in-game arb scale).
- Gebele & Matthes (2026) — arXiv:2601.01706 (Law-of-One-Price / cross-venue).
- Deribit API `docs.deribit.com`; Kalshi API `docs.kalshi.com`; CME FedWatch methodology;
  `pyfedwatch` (github.com/ARahimiQuant/pyfedwatch); Breeden–Litzenberger (RND from options).
- Supporting code: `strategy_research/scan_markets.py`, `analyze_snapshot.py`, `deribit_poc.py`.

*Research tooling, not financial advice.*
