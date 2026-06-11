# A1 revisit — risk-neutral vs physical, and the full forecast-evaluation toolkit

**Question (revisited):** The original A1 backtest compared Polymarket's daily
"BTC/ETH above $K" prices directly to Deribit's option-implied `N(d2)` and found
them Brier-equivalent (no edge). Two things were missing: (1) `N(d2)` is a
**risk-neutral** probability with zero drift, but PM prices **physical** beliefs
that include crypto's large positive risk premium — so the right null is
`PM ≈ P_physical`, not `PM ≈ P_risk-neutral`; (2) the original used only
point t-stats, not the modern forecast-evaluation battery. This revisit fixes both.

**Answer: still no edge — but now with a mechanism and properly-powered tests.**
The residual "PM sits ~1pp above Deribit" lean is fully explained by a plausible
crypto risk premium (it vanishes at λ≈0.7–1.0/yr, squarely in the BTC literature
range). With proper inference — Diebold–Mariano (HLN-corrected), Spiegelhalter
calibration, leave-one-day-out forecast pooling, a power analysis, a
drift-contamination check, and a multiple-testing guard — **nothing survives.**

Second source(s): Deribit options (risk-neutral price) + the crypto
risk-premium literature (the Q→P wedge) + realized Binance outcomes (ground truth).
Code: `advanced_analysis.py` (reads `rows.json` from the original backtest);
figure `fig_a1_revisit.png`.

---

## Why the original comparison was the wrong null

`N(d2)` from Deribit is the **Q-measure** (risk-neutral) digital probability: it
assumes the asset drifts at the risk-free rate (≈0 for crypto). A betting market
prices the **P-measure** (physical) probability — what traders actually believe.
The two differ by the integrated pricing kernel; the gap `P_P − P_Q` is a **risk
premium, not arbitrage** (Almeida–Grith–Miftachov 2024 estimate the Bitcoin
return premium at ~66%/yr and a positive variance risk premium ≈0.14).

For an at-the-money digital the physical adjustment is
`P_P = N(d2 + λ·T/v)`, with `v = σ√T` the total vol and `λ` the annualized
premium. Because the drift gets divided by `σ√T`, even a short horizon produces a
non-trivial wedge:

| Horizon | ATM wedge `P_P − P_Q` (σ=0.5, λ=0.66) |
|---|---|
| 6h  | ~1.4pp |
| 20h | ~2.5pp |
| 1wk | ~7pp |
| 1mo | ~15pp |

So the original A1's "PM 3–6pp above Deribit" live reading — and the ~1pp residual
after smile/settlement correction — are **the expected sign and order of magnitude
of the risk premium**, not evidence of mispricing. (See `fig_a1_revisit.png`,
right panel.)

---

## 1–2. The lean vanishes under a plausible risk premium

Daily product, 155 banded in-smile-range observations across 20 days (BTC+ETH).

**20h horizon (D-1_20Z), n=93:**

| λ (/yr) | mean physical P_P | gap (PM − P_P) |
|---|---|---|
| 0.00 (raw RN) | 0.5178 | **+1.20pp** |
| 0.30 | 0.5219 | +0.80pp |
| 0.66 | 0.5266 | +0.32pp |
| 1.00 | 0.5310 | −0.11pp |

The +1.2pp raw lean shrinks monotonically to **zero around λ≈1.0/yr**, well within
the BTC risk-premium range. At the 6h horizon the raw gap is already only +0.08pp.
There is no lean left to trade once the risk premium is acknowledged.
(`fig_a1_revisit.png`, left panel.)

---

## 3. Both venues are well-calibrated (Spiegelhalter z)

| Horizon | Forecast | Brier | reliability | Spiegelhalter z | p |
|---|---|---|---|---|---|
| 20h | PM | 0.1495 | 0.021 | +0.70 | 0.48 |
| 20h | RN model | 0.1479 | 0.020 | +0.27 | 0.79 |
| 6h | PM | 0.1193 | 0.029 | −0.31 | 0.76 |
| 6h | RN model | 0.1199 | 0.031 | +0.14 | 0.89 |

Neither venue is miscalibrated (all |z|<1). Reliability terms are tiny; the Brier
difference between PM and Deribit is in the third decimal.

---

## DM, encompassing, pooling — no skill difference, no exploitable combination

**Diebold–Mariano** (Brier, day-aggregated to the 20 independent days,
Harvey–Leybourne–Newbold small-sample correction):

| Horizon | n_days | mean loss diff | DM (HLN) | p |
|---|---|---|---|---|
| 20h | 20 | +0.0008 | +0.33 | **0.75** |
| 6h  | 20 | +0.0000 | +0.00 | **1.00** |

**Encompassing** `outcome ~ a + b1·PM + b2·RNmodel` (day-clustered SE): PM and the
model are near-collinear (the two forecasts agree), so neither coefficient is
significant (t=+0.76 and +0.04). The constant is significantly negative
(−0.117, t=−3.0) — **both** venues over-predicted "above" over this window, a
shared directional miss (see drift check), not a venue advantage.

**Leave-one-day-out logit pool** (the cleanest inefficiency detector — if an
out-of-sample combination beats *both* venues, neither is efficient):

| Forecast | OOS Brier |
|---|---|
| PM | 0.1374 |
| RN model | 0.1367 |
| **pool** | **0.1397** |

The pool is *worse* than both. **No exploitable inefficiency.**

---

## 5. The null is adequately powered (at the daily horizon)

This is the key honesty check the original lacked. Day-level Brier loss-diff SD
and the minimum detectable edge at 80% power:

| Horizon | daily SD | min detectable Brier edge | days for 0.01 edge | days for 0.005 edge |
|---|---|---|---|---|
| 20h | 0.0109 | **0.0068** | 9 | 37 |
| 6h | 0.0219 | 0.0137 | 38 | 150 |

At the 20h horizon, 20 days is **enough power to detect a 0.01 Brier edge** — and
we detect nothing (DM p=0.75). So "no edge" here is a reasonably-powered null, not
merely an underpowered shrug. (At 6h the test is weaker and the null is softer.)

---

## 6. The window is drift-contaminated

Regressing each day's PM-vs-model Brier advantage on that day's directional
surprise (realized − PM mean):

| Horizon | corr(directional surprise, PM advantage) |
|---|---|
| 20h | **+0.79** |
| 6h | +0.08 |

At 20h the correlation is +0.79: on days BTC moved, whichever venue leaned that
direction looked "smart." Apparent skill differences over this window are
directional luck, not forecasting ability — exactly the CLAUDE.md drift warning.
Realized "above" rate was 0.42 vs ~0.52 priced by both venues: BTC drifted down
over the 20-day window and both venues shared the miss.

---

## 7. Nothing survives the multiple-testing guard

Max-|t| sign-flip bootstrap (Romano–Wolf-style) across the 6-config grid
(2 horizons × {ITM, ATM, OTM} moneyness):

| Config | t (PM − model Brier) |
|---|---|
| 20h / ITM | +1.57 |
| 6h / OTM | +1.54 |
| 6h / ITM | −1.19 |
| others | |t| < 0.6 |

Observed max|t| = 1.57; **FWER-controlled p = 0.62.** No config's PM-vs-Deribit
difference survives the search.

---

## What would change the verdict (and why the data can't currently provide it)

- **Kalshi as a third venue / extra data: dead end.** Kalshi's BTC/ETH markets
  (KXBTCD, KXBTC, KXETHD) show `bid=None ask=None` live and **zero volume on
  every settled market** — they have never traded. No live third price, no
  historical resolution events. (Reconfirms the A2 finding, now definitively.)
- **SOL/XRP instruments: no second price.** PM has liquid daily SOL/XRP ladders,
  but Deribit lists **0 options** for SOL and XRP — only BTC/ETH have a sharp
  options venue. Can't extend the instrument set.
- **Longer-dated PM crypto digitals (weekly/monthly):** here the risk-premium
  wedge is large (7–15pp), so a naive PM-vs-Deribit gap looks huge — but it is
  the premium, whose magnitude is uncertain to ±tens of percent, so any deviation
  sits inside the base-rate CI (rule 7). And turnover is low → fails the bar even
  if real.
- **Maker-side variant:** resting limit orders earns the ~2pp spread fee-free,
  but that is market-making (B4), an infra/latency game contested by bots, not a
  forecasting edge.

---

## Verdict

**A1 stays dead — now conclusively.** The original null ("PM ≈ Deribit, Brier
equal") was theoretically *expected*: at the daily horizon the only systematic
PM-vs-Deribit wedge is the crypto risk premium (~1–2pp ATM), which is not alpha.
After acknowledging it, the residual lean is zero; PM and Deribit are equally
well-calibrated (Spiegelhalter, DM-HLN), no out-of-sample combination beats
either, the test is adequately powered at 20h, the apparent differences are
drift-contaminated (corr +0.79), and nothing survives multiple-testing
correction.

The deeper lesson for the whole project: **a sharp options venue prices the
risk-neutral measure; a betting market prices the physical measure; the wedge
between them is a risk premium and must be subtracted before any "edge" is
claimed.** This is the formal version of CLAUDE.md rule 2 (an edge that rides
smoothly with moneyness/horizon is a structural artifact).

---

## Reproduce

```
cd crypto_deribit_edge_exploration
python backtest.py            # regenerates rows.json from data_cache
python advanced_analysis.py   # the full toolkit above
```

Outputs: console report + `fig_a1_revisit.png`.
