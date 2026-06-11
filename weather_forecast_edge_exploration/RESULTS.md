# Weather markets vs forecast ensembles — results

**Question:** Kalshi runs liquid daily city high-temperature ladders (KXHIGHNY, …)
resolved on the official NWS Climatological Report. Weather is the canonical domain
where numerical models beat human intuition. Does the Kalshi crowd misprice the
daily high-temp vs a calibrated forecast, giving a real, objective, daily-turnover
edge? (This is the last untested "model beats crowd on objective resolution" corner.)

**Answer: No.** The Kalshi NYC high-temp market is liquid (~10k trades/day, ~1¢
spreads), well-calibrated, and **sharper than a genuine day-ahead GFS forecast**
(market RPS 0.084 vs honest-forecast RPS 0.122). An apparent +63%/trade edge
appeared only when the forecast was allowed to **peek** (Open-Meteo's "historical
forecast" uses same-day model runs); with a point-in-time-honest ~1-day-ahead
forecast the edge inverts — the market wins. The crowd already embeds the forecast.

Second sources: Open-Meteo GFS ensemble + previous-runs forecasts (free, no key);
realized = Kalshi `result` (= NWS Central Park high). Code: `fetch_data.py`,
`analyze.py`; figure `fig_weather.png`.

---

## The market: liquid, coherent, objective

- **Liquidity:** KXHIGHNY ~8,000–12,000 trades/day across the ladder; open interest
  ~8,000 contracts/bucket; trades of 85–500 contracts; **median bucket spread 1¢**.
  (Kalshi's `volume`/`bid`/`ask` aggregate fields read null in the public market
  object, but the trades + candlestick feeds are fully populated — the market is real.)
- **Structure:** a MECE 6-bucket ladder per day (e.g. <78°, 78-79°, 80-81°, 82-83°,
  84-85°, >85°). Devigged bucket mids sum to 1.035 (3.5% overround) — coherent.
- **Resolution:** NWS Climatological Report for NYC (Central Park / OKX) — objective,
  data-resolved, low resolution risk. Realized bucket available via Kalshi `result`.
- **Fee:** Kalshi quadratic taker `0.07·p·(1−p)` (max 1.75% at p=0.5).

## The market is well-calibrated and sharp (60 NYC days)

Decision time = evening before (D-1 22:00 UTC). Devigged market prices vs realized:

| market bucket prob | realized frequency | n |
|---|---|---|
| 0.00–0.10 | 0.027 | 185 |
| 0.10–0.25 | 0.169 | 65 |
| 0.25–0.50 | 0.371 | 97 |
| 0.50–0.75 | 0.583 | 12 |

Near-perfect reliability (`fig_weather.png`, left). Market RPS skill vs climatology
= **0.48** (sharp). This is a market that already prices the weather well.

---

## The decisive test: point-in-time honesty (the A1 lesson, again)

A first pass using Open-Meteo's **"historical forecast"** showed the forecast beating
the market: RPS 0.064 vs 0.084 (t=+2.0), trade sim **+63%/trade**. Three red flags
said *artifact*:

1. The "forecast" error std was **1.65°F — smaller than the after-the-fact
   reanalysis std (1.74°F)**. A genuine forecast cannot beat the reanalysis.
2. +63%/trade with t=3 is too good — the signature of lookahead.
3. Open-Meteo's historical-forecast API concatenates **shortest-lead (same-day)**
   model runs, which have seen the morning-of data — not available at a D-1 decision.

Re-running with a genuinely point-in-time forecast (Open-Meteo `temperature_2m_previous_day1`,
the forecast made ~1 day earlier, daily-max recomputed from its hourly trace):

| Forecast | err std | forecast RPS | market RPS | trade sim | verdict |
|---|---|---|---|---|---|
| **lead0** (same-day run, *peeks*) | 1.65°F | 0.064 | 0.084 | +63%/trade, t=3.1 | **fake (lookahead)** |
| **prev1** (honest ~1-day-ahead) | 2.74°F | **0.122** | **0.084** | +2%/trade, t≈0 | **market beats forecast** |

With an honest forecast the result inverts: **the market (RPS 0.084) is sharper than
the GFS day-ahead forecast (RPS 0.122)**, t = −2.55 against the forecast. The trade
sim is a coin flip (~50% hit, ~0% net). (`fig_weather.png`, right.)

Even the *cheating* same-day forecast only reaches RPS 0.064 — so the absolute
headroom over the market is ~0.02 RPS and is only accessible by peeking. A
legitimately better-than-market forecast would have to nearly match a same-day
nowcast using only day-ahead information — not realistic, especially since the
market is almost certainly already pricing ECMWF + MOS via professional weather
traders (the ~10k trades/day are not a naive retail crowd).

---

## Why this fails (and why it's the same failure as crypto)

Identical structure to the A1 crypto/Deribit result:
- A liquid, objective market that looks beatable by a "model."
- An apparent edge that is entirely a **measurement-not-point-in-time artifact**
  (there: settlement-clock + nearest-strike IV; here: same-day vs day-ahead forecast).
- On honest, point-in-time measurement the edge evaporates and the **market is at
  least as sharp as the sharp second source.**

The weather crowd embeds the forecast just as the crypto book embeds Deribit. The
recurring project lesson holds: where Polymarket/Kalshi is liquid, it is sharp.

## What would change the verdict (and the honest caveats)

- **A better ensemble** (full ECMWF 51-member, multi-model blend, MOS-corrected)
  *might* shave the gap — but it must beat market RPS 0.084 **net of** the 1¢ spread
  and the quadratic fee, and the honest GFS is at 0.122. Closing 0.038 RPS *and*
  overtaking is implausible against a market that likely already uses ECMWF.
- **Forward, point-in-time collection** is the only fully-clean test (the free
  ensemble API has no deep history; only ~4 archived days exist). Given the honest
  GFS deterministic result (market wins by t=−2.55), the prior for a forward ECMWF
  test clearing the bar is low. Not worth the wait unless a cheaper signal appears.
- **Intraday / shorter-lead** trading (reacting to the 12Z run faster than the book)
  is a latency game (B4-style), not a forecasting edge.

---

## REVISIT (5 cities, correct order-book API, per-city bias correction)

Prompted by the (correct) observation that these markets are clearly liquid and that
the first pass mis-called an API, the revisit fixed two things and broadened the test:

1. **Live order-book API correction.** The live book is
   `GET /markets/{ticker}/orderbook → {"orderbook_fp": {"yes_dollars":[[px,sz]...],
   "no_dollars":[...]}}` — NOT `orderbook`/`yes`/`no`. Best YES bid = max yes_dollars
   price; best YES ask = 1 − max no_dollars price. The market-OBJECT fields
   (`yes_bid`, `volume`, `open_interest`) read null for these series; the live book,
   trades, and candlesticks are the real source. (The *historical* backtest already
   used candlesticks with the correct `_dollars` fields, so its prices were valid.)
   Live depth is large: e.g. LAX T79 NO-book had 1,884 contracts @ $0.46, 2,289 @ $0.80.

2. **Full ensemble + PER-CITY bias correction across 5 cities** (NYC, CHI, MIA, LAX,
   AUS; 60 days each = 300 city-days). A live raw-ensemble check showed big divergences
   (CHI ensemble ~5°F hot, MIA ~5°F cold vs the market) — but these are **grid-vs-station
   bias**, not mispricing: MIA's grid cell sits over coastal water (raw ensemble 85°F vs
   a physically-correct market ~90°F for June). Estimated per-city day-ahead bias:
   LAX −1.86°F, MIA −1.84°F, AUS −1.04°F, NYC +0.10°F, CHI −0.04°F.

After honest point-in-time (`prev_day1`) forecasting with **per-city, leave-one-out**
bias + spread correction:

| City | bias°F | market RPS | forecast RPS | diff (mkt−fc) | t | trade ret/trade |
|---|---|---|---|---|---|---|
| AUS | −1.04 | 0.105 | 0.150 | −0.045 | −3.0 | −13% |
| CHI | −0.04 | 0.096 | 0.146 | −0.050 | −3.6 | −29% |
| LAX | −1.86 | 0.077 | 0.102 | −0.025 | −2.5 | −30% |
| MIA | −1.84 | 0.082 | 0.111 | −0.029 | −2.7 | −12% |
| NYC | +0.10 | 0.086 | 0.121 | −0.034 | −2.3 | +8% (t=0.5) |
| **Pooled** | | | | **−0.037** | **−6.3** | no edge |

**The market beats the honest day-ahead GFS ensemble in all 5 cities** (pooled
t = −6.3 over 300 city-days). The live divergences vanish under per-city bias
correction. Trade sims are negative or insignificant everywhere.

Remaining caveat: this is the GFS ensemble. A better model (ECMWF 51-member, MOS) is
maybe 10–20% sharper — not enough to close a 30–50% RPS gap *and* overtake a market
that almost certainly already prices ECMWF. The absolute ceiling — the lookahead
same-day forecast — only reached RPS 0.064 vs market 0.085, so there is little
headroom even with perfect information at lead 0. `live_compare.py` runs the corrected
live book-vs-ensemble comparison for any city/day.

## Verdict

**FAILED — no forecast edge.** Kalshi weather is the most promising market we found
(genuinely liquid, objective, daily turnover) and the first pass did mis-call the
live-book API — but with the book parsed correctly, the full ensemble, per-city bias
correction, and point-in-time-honest forecasts across 300 city-days, the market is
decisively sharper than the numerical day-ahead forecast (pooled t = −6.3). The
apparent edges were lookahead contamination (historical pass) and grid-vs-station
bias (live pass) — both caught by the same discipline that killed A1.

**Running scorecard: 10 straight negatives.**

---

## Reproduce

```
cd weather_forecast_edge_exploration
python fetch_data.py NYC      # Kalshi candlesticks + Open-Meteo; caches to cache/
python analyze.py             # calibration, market skill, honest vs contaminated forecast
```

Outputs: console report + `fig_weather.png`. The genuine lead-1 forecasts are in
`cache/omforecast_leads.json` (Open-Meteo `temperature_2m_previous_day1`).
