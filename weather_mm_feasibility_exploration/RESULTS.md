# B4: Market-making Kalshi weather ladders — feasibility study

**Question:** The weather exploration showed Kalshi's daily city high-temp ladders are
liquid (~10k trades/day, 1¢ spreads) and *not* beatable by a forecast — the market is
sharp. But a sharp, liquid, high-turnover, objective market is the ideal place to
*provide* liquidity rather than predict. Does the passive (maker) side actually make
money, net of fees and adverse selection?

**Answer: Yes, in gross — this is the first real edge the project has found.** Over 30
days of NYC (180 bucket-markets, 249k trades, 6.3M contracts), the passive side earned
**+$64k = +1.0¢/contract = +3.5% of traded notional, with ZERO maker fee** (Kalshi
charges weather makers nothing; only takers pay 0.07·p·(1−p)). Daily PnL: **+$2,132/day
mean, 67% up-days, daily Sharpe 0.53 (~8.4 annualized), worst day −$2.9k.** Takers lost
−$108k net (−$64k to makers + −$44k in fees).

**The catch — and why this is "promising," not "proven":** that +$64k is the *aggregate*
pie earned by *all* liquidity providers. Incumbent bots already quote the 1¢ spreads, so
the question that historical trade data **cannot** answer is what *share* a single,
non-colocated, REST-API maker (in Norway) actually captures versus being left the toxic
flow. That requires a forward quote-simulation test.

Second source: the trades themselves (every trade has a taker side + known resolution,
so the maker's realized PnL is computed exactly). Code: `fetch_trades.py`, `analyze_mm.py`;
figure `fig_mm.png`.

---

## The fee structure makes this possible

Researched (June 2026): **Kalshi weather markets charge makers $0.00.** Only the taker
pays `roundup(0.07·C·P·(1−P))` (1.75% at p=0.5, →0 at extremes). The maker-fee exception
list is small (FOMC/GDP) and excludes weather. There's also a Liquidity Incentive Program
(rebates, but capped ~$7k/week). So a maker keeps the **full** captured spread fee-free —
the opposite of the kill-criterion. (Verify the primary fee PDF before funding.)

## The core result — passive side held to resolution

For every trade: maker took the other side, so
`maker_pnl = (P − outcome)` if the taker bought YES, else `(outcome − P)`, × size.

| metric | value |
|---|---|
| contracts traded (30d, NYC) | 6,347,949 |
| notional traded | $1,830,507 |
| **maker PnL** | **+$63,961** |
| maker PnL / contract | **+1.008¢** |
| as % of notional | **+3.49%** |
| taker net (incl. $44k fees) | −$108,249 |

Takers — predominantly noise/retail crossing the spread — systematically lose; the
liquidity providers collect. This is the textbook market-making relationship, and unlike
the 10 prior explorations it is **gross-positive after the (zero) maker fee.**

## Daily consistency (the "is it real or lucky" check)

| metric | value |
|---|---|
| mean daily maker PnL | +$2,132 |
| std | $4,009 |
| positive days | 20/30 (67%) |
| daily Sharpe | 0.53 (≈8.4 annualized) |
| worst day | −$2,908 |
| best day / top-3 days as % of total | 22% / 54% |

Consistent, not a one-day fluke (`fig_mm.png`). Per-*bucket* PnL swings are large
(±$7–12k) because makers carry real directional inventory in each bucket — but across the
full MECE ladder the buckets hedge (exactly one resolves YES), so *daily* risk is far
tamer than per-bucket. A real MM must quote the **whole ladder** to get this netting.

## Adverse selection is mild (the weather advantage)

Maker PnL/contract by time-to-resolution:

| hours before close | maker PnL/contract |
|---|---|
| >24h | **−0.525¢** (thin, stale book — quoting too early loses) |
| 12–24h | +0.698¢ |
| 6–12h | +1.962¢ (the sweet spot) |
| 3–6h | +0.526¢ |
| 1–3h | +0.999¢ |
| <1h | +0.998¢ |

Crucially, makers stay **positive right up to resolution** — they are *not* destroyed
late. Weather information arrives slowly (forecast runs every 6h; the realized high builds
over the afternoon), so the adverse-selection timescale is minutes-to-hours, not the
milliseconds of crypto/sports. **This is the key argument that a non-HFT maker can play
here** where it cannot in crypto (the B3 lesson). The only losing window is >24h out, when
the book is thin and stale — trivially avoided by not quoting until ~18h before close.

## Capacity and rough return

- Daily traded notional ≈ **$61k/day/city**; ×5 liquid cities (NYC/CHI/MIA/LAX/AUS) ≈
  **$300k/day** of flow to compete for.
- Per-cycle maker return on collateral ≈ +1.0¢/contract ÷ ~35¢ collateral ≈ **+2.9% per
  daily cycle** on captured volume — capital recycles daily, so even a small captured
  share, heavily haircut, clears the 10%/yr bar *in gross terms*.
- But capacity is modest and the **LIP rebate is capped at ~$7k/week**, so this does not
  scale to large size.

---

## What this study CANNOT settle (and the honest risks)

1. **Capturable share vs incumbent bots.** +$64k is the whole pie. Bots already quote 1¢
   spreads; a slow maker wins fills only by queue priority or by quoting *inside*, which
   invites adverse selection. The realized share for a non-colocated REST player is
   unknown and could be a fraction — or, on the toxic residual, negative. **This is the
   decisive open question and needs a live test.**
2. **Latency on the cancel side.** Even if weather is slow, a maker must *cancel* stale
   quotes when a new model run or the realized high shifts fair value. A REST loop from
   Norway re-quoting every few minutes is plausibly fast enough (the <1h bin stays
   positive in aggregate), but a single-name surprise could hit before you cancel.
3. **Inventory tail.** Per-bucket ±$10k swings mean a maker who fails to balance the
   ladder carries large directional risk on a temperature surprise.
4. **Norway frictions.** Kalshi access is regulatorily fragile; 28% tax on gains >10k NOK;
   withdrawal/funding hurdles — all apply on top and compress net returns.
5. **Sample.** 30 days, one city, one season (late-spring/summer). Winter regimes (storms,
   higher volatility) likely carry more adverse selection. Needs multi-season validation.

## Verdict

**PROMISING — the first strategy to clear the gross bar.** Kalshi weather ladders pay the
passive side +3.5% of notional (+$2.1k/day NYC, Sharpe 0.53) fee-free, with mild,
slow-moving adverse selection that a non-HFT operator can plausibly survive — unlike every
prior corner. It is *not* proven for this user: the capturable share against incumbent
bots is unknown and unanswerable from historical trade data.

**Recommended next step (decisive):** a forward **quote-simulation / paper-trade** — rest
notional limit orders just inside/at the live book across the full ladder for several
weeks, log fills, realized adverse selection, and queue position, to estimate the *captured*
fraction of this gross edge. Only then size it. This is the one strategy worth that effort.

---

## Reproduce

```
cd weather_mm_feasibility_exploration
python fetch_trades.py NYC      # full trade history, 30d, -> cache_trades/
python analyze_mm.py            # passive-side PnL, time/price decomposition, capacity
```

Outputs: console report + `fig_mm.png`.
