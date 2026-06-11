# B4 — Kalshi Weather Market-Making: Implementation Plan

**Status:** feasibility passed in gross (see [RESULTS.md](RESULTS.md)); this document
specifies exactly what the strategy is, the precise hypotheses it must still prove, the
metrics and go/no-go thresholds, and a phased build — from a zero-capital paper-trading
harness to a sized live pilot. Nothing here recommends deploying capital before Phase 1
(paper trade) clears its bar.

> One-line thesis: **Kalshi's daily city high-temperature ladders are sharp, liquid, and
> objective; we do not try to *predict* them better than the market — we *provide
> liquidity* to the noise traders who cross the spread, collecting a fee-free spread with
> mild, slow-moving adverse selection.**

---

## 1. Background and why this edge plausibly exists

### 1.1 The instrument
Kalshi lists, for each of several US cities, a **daily "highest temperature" market** that
resolves on the official NWS Climatological Report for that city's station (e.g. NYC =
Central Park / OKX; LAX, CHI = O'Hare, MIA, AUS). Each day is a **MECE ladder** of ~6
mutually-exclusive, collectively-exhaustive buckets:

```
KXHIGHNY-26JUN09-T78    "<78°"        (77 or below)
KXHIGHNY-26JUN09-B78.5  "78–79°"
KXHIGHNY-26JUN09-B80.5  "80–81°"
KXHIGHNY-26JUN09-B82.5  "82–83°"
KXHIGHNY-26JUN09-B84.5  "84–85°"
KXHIGHNY-26JUN09-T85    ">85°"        (86 or above)
```

Exactly one bucket resolves YES (pays $1); the rest resolve NO ($0). Across a single day's
ladder the YES prices sum to ≈1 (plus a small overround). The market opens ~1–2 days
before the measured day and closes 11:59 PM ET on the measured day; it settles the next
morning on the NWS report.

### 1.2 Why the passive side makes money (the measured edge)
From 30 days of NYC trade history (249k trades, 6.3M contracts — [RESULTS.md](RESULTS.md)):

- The **maker fee is $0** on weather (only takers pay `roundup(0.07·C·P·(1−P))`).
- Computing the *exact* realized PnL of whoever took the passive side of every historical
  trade, held to resolution: **+$64k = +1.0¢/contract = +3.5% of notional**, +$2.1k/day,
  daily Sharpe 0.53 (~8.4 annualized), 67% up-days, worst day −$2.9k.
- Takers lost **−$108k net** (−$64k to makers, −$44k in fees). Weather takers are
  overwhelmingly **noise / retail / convenience flow** crossing the spread.

### 1.3 Why a *non-HFT* operator can plausibly play here (the key differentiator)
Internal arbitrage (B3) and crypto strategies (A1/D10) died because the money is captured
by colocated bots in **milliseconds**. Weather is different: the information that moves
fair value arrives on **hour timescales** —

- new numerical-model runs land roughly every 6 hours (00/06/12/18 UTC GFS cycles);
- the realized daily high builds over the afternoon and is not "known" until late.

The measured maker PnL stays **positive right up to the final hour** before close; the
*only* losing window is **>24 h before close**, when the book is thin and stale. So the
adverse-selection clock is minutes-to-hours — within reach of a REST/WebSocket re-quoting
loop, even from Norway. **This is the whole reason B4-on-weather is worth building when
the other ten ideas were not.**

### 1.4 What is NOT yet proven (the reason for Phase 1)
The +$64k is the **aggregate pie shared by all liquidity providers**. Incumbent bots
already quote 1¢ spreads. Historical trade data **cannot** tell us:

1. what **fraction** of that pie a *new, non-colocated* maker captures (queue position);
2. the **realized adverse selection** specifically on *our* fills (we may win only the
   toxic residual that the fast bots decline);
3. our **fill rate** at a given quoting aggressiveness.

These are answerable only by **resting (simulated, then real) orders against the live book
and watching what fills and how it settles.** That is Phase 1.

---

## 2. Hypotheses, metrics, and go/no-go thresholds

The strategy is a sequence of falsifiable tests. Each phase has an explicit kill switch.

| # | Hypothesis | Metric | GO threshold | KILL |
|---|---|---|---|---|
| H1 | A passive ladder quoter gets **filled** at meaningful volume | simulated fills / day / city | ≥ 2,000 contracts/day/city | < 500 |
| H2 | Our fills are **not** dominated by toxic flow | realized PnL/contract on *our* simulated fills, held to resolution | ≥ +0.4¢/contract | ≤ 0 |
| H3 | Net of inventory & realistic queue, the sleeve **clears the bar** | annualized net return on deployed collateral, post-Norway-tax | ≥ 10%/yr | < risk-free |
| H4 | Risk is bounded | daily PnL Sharpe; worst-day / capital | Sharpe ≥ 0.3, max daily loss ≤ 5% of capital | drawdown > 20% |
| H5 | It survives **out of season / other cities** | repeat H2–H4 on ≥3 cities, ≥2 months incl. a volatile spell | edge persists | edge only in one city/season |

**The single decisive number is H2** (realized PnL/contract on *our own* simulated fills).
The historical aggregate is +1.0¢/contract; if our captured fills come in at, say,
+0.4–0.7¢/contract after losing the best flow to faster bots, the strategy is real but
smaller. If they come in ≤0, the pie exists but we only get the toxic slice — kill it.

---

## 3. The strategy logic (precise specification)

### 3.1 Fair value
Because the market is **sharp** (we proved a day-ahead ensemble does not beat it), our
fair value is the **market's own devigged consensus**, not an independent forecast:

```
For each live bucket i in a day's ladder:
  mid_i      = (best_yes_bid_i + best_yes_ask_i) / 2          # from orderbook_fp
  fair_i     = mid_i / Σ_j mid_j                               # devig to sum to 1 (MECE)
```

The ensemble forecast (bias-corrected per §RESULTS of the forecast study) is used **only
as a guardrail**: if our fair value and the bias-corrected ensemble disagree by more than
a threshold, **widen or pull** (we may be about to be run over by information the consensus
hasn't absorbed). We do not quote *through* the consensus on the basis of the forecast —
that bet already failed (C4).

### 3.2 Quoting
For each bucket we post a two-sided quote around fair:

```
half_spread δ_i = max( 1 tick (=1¢),  k_vol · σ_i,  k_inv · |inv_i| )
quote_bid_i = clamp( fair_i − δ_i,  0.01,  0.99 )
quote_ask_i = clamp( fair_i + δ_i,  0.01,  0.99 )
size_i      = base_size · liquidity_weight_i · inventory_brake_i
```

- `δ_i` widens with bucket volatility `σ_i` (ATM buckets move more) and with our current
  inventory in that bucket.
- **Inventory skew:** if we are net long bucket i, shift *both* quotes down by `β·inv_i`
  so we are more likely to sell and rebalance (and vice versa). This is the core risk
  control of any MM.
- **Ladder coverage:** quote the **whole ladder**. The MECE structure means our per-bucket
  directional risks partially cancel (exactly one bucket pays $1), which is what tames daily
  variance (RESULTS: per-bucket swings ±$7–12k → daily std only $4k).

### 3.3 Re-quote / cancel triggers
Re-center quotes when any of:
- the consensus `fair_i` moves by ≥ 1 tick (a trade printed or the book shifted);
- a new model-run boundary passes (00/06/12/18 UTC) — re-pull the ensemble guardrail;
- our inventory in a bucket exceeds a soft cap (skew harder or pull one side);
- **the realized daily high becomes effectively known** (see §3.4).

### 3.4 The two hard timing rules (from the data)
1. **Do not quote >24 h before close.** That window had **negative** maker PnL
   (−0.525¢/contract) — thin, stale, low-information book. Begin quoting ~18–24 h out.
2. **Pull decided buckets once the high is locked.** Late afternoon, once the day's high is
   essentially in (observed temp trending down off the peak, confirmed via the NWS
   observation feed / Open-Meteo "current"), the winning bucket is near-certain. Stop
   quoting buckets whose outcome is decided — that is the one window where a faster taker
   could lift a stale ask on the now-known winner. Keep only minimal, wide quotes.

### 3.5 Risk controls (hard limits)
- **Per-bucket inventory cap** and **per-day-ladder net cap** (so a single temperature
  surprise can't blow up).
- **Per-city capital cap** and **global capital cap**.
- **Max daily loss kill switch** (flatten and stop for the day at −X% of capital).
- **Stale-quote watchdog:** if the order-feed/heartbeat lags > T seconds, cancel all
  (don't rest stale quotes during a data outage).
- **Settlement-source sanity:** only trade cities whose NWS station and Kalshi resolution
  text we have verified match the data feed we monitor.

---

## 4. Phased build

### Phase 0 — Read-only data recorder (1–2 days of coding, then runs continuously)
**Goal:** capture ground-truth microstructure we currently lack (we only have trades +
hourly candles; we need the *live book over time* to model fills and queue).

- Poll (or, better, WebSocket-subscribe to) the live order book for every bucket of every
  open ladder in the target cities, every 1–5 s; append-only log: timestamp, full
  `orderbook_fp` (yes/no price-size levels), best bid/ask, and the trade feed.
- Also log: the ensemble forecast at each model-run boundary, and NWS current obs.
- Output: a timestamped book+trade tape per market — the substrate for Phase 1.

**No capital, no auth required** (all read endpoints are public).

### Phase 1 — Paper-trade / quote simulation (the decisive test)
**Goal:** estimate the *captured* edge (H1–H2) without risking money.

- Replay (or run live against) the Phase-0 tape. Maintain **simulated** resting orders per
  §3 logic.
- **Fill model (conservative):** a simulated resting buy at price `p` with size `s` is
  filled by a real trade only when:
  - a real trade prints at a price that crosses `p` (taker would have hit us), **and**
  - the cumulative real volume at/through `p` exceeds the real resting depth that was
    *ahead of us* in the queue (we assume we join the back of the queue at the time we
    posted). Tunable queue-position assumptions: optimistic (front), realistic (back),
    pessimistic (never ahead of existing size).
- Mark every simulated fill to the known resolution → realized PnL; also mark to mid at
  fill+{1,5,15} min to measure **short-horizon adverse selection** separately from
  directional/inventory PnL.
- **Report:** fills/day/city, realized PnL/contract (H2) under each queue assumption,
  adverse-selection curve, inventory paths, daily PnL distribution, and the implied
  net annualized return on collateral (H3) after Kalshi taker rebate (n/a to us as maker),
  zero maker fee, and Norway tax.

**GO to Phase 2 only if H1 & H2 clear under the *realistic* (back-of-queue) assumption.**

### Phase 2 — Live pilot, minimal capital
**Goal:** confirm the paper-trade model matches reality (real fills, real latency, real
queue) at trivial size.

- Authenticated trading (see §5.2). Quote **one city**, smallest viable size, the full
  ladder, with all risk controls and the §3.4 timing rules.
- Reconcile **actual fills vs the Phase-1 simulator's predicted fills** — this validates
  (or breaks) the fill model. Track realized PnL/contract vs the +1.0¢ aggregate.
- Run ≥ 3–4 weeks. Kill on H4 breach.

### Phase 3 — Scale within capacity
**Goal:** grow to the capacity ceiling, add cities, harvest LIP rebates.

- Add CHI/MIA/LAX/AUS; size up to the per-city capacity (~$61k/day flow ⇒ realistically a
  few $k of deployed collateral/city before our own quotes move the mid).
- Register for the **Liquidity Incentive Program** (rebates, but **capped ~$7k/week** — a
  bonus, not the core).
- Continuous H5 monitoring across seasons; widen/pull discipline in volatile regimes.

---

## 5. System architecture

### 5.1 Components
```
                  ┌─────────────────────────────────────────────┐
                  │                 Strategy core                │
   Kalshi WS/REST │  ┌────────────┐   ┌────────────┐  ┌────────┐ │
  ───────────────▶│  │ MarketData │──▶│ FairValue  │─▶│ Quoter │ │──▶ Order
   orderbook_fp   │  │  client    │   │  engine    │  │ engine │ │    manager ──▶ Kalshi
   trades         │  └────────────┘   └─────┬──────┘  └───┬────┘ │      (auth)
                  │        │                 │            │      │
  Open-Meteo  ───▶│  ┌────────────┐    ┌─────▼──────┐ ┌───▼────┐ │
  ensemble/obs    │  │ Forecast   │───▶│  Risk /    │◀┤ Position│ │◀── fills/positions
                  │  │ guardrail  │    │ inventory  │ │ tracker │ │
                  │  └────────────┘    └────────────┘ └─────────┘ │
                  │              ┌──────────────┐                 │
                  │              │ Logger /     │  (Phase0 tape,  │
                  │              │ analytics    │   Phase1 sim,   │
                  │              └──────────────┘   Phase2 recon) │
                  └─────────────────────────────────────────────┘
```

- **MarketData client** — subscribes to the Kalshi market-data WebSocket
  (`orderbook_delta`, `trade`, `ticker` channels) with a REST snapshot on (re)connect;
  maintains the live book per market. (Phase 0 can poll REST `orderbook_fp` if WS access
  is delayed.)
- **FairValue engine** — devigged consensus per §3.1 + volatility estimate per bucket.
- **Forecast guardrail** — bias-corrected ensemble (reuse `weather_forecast_edge_exploration`
  code) refreshed at model-run boundaries; emits widen/pull signals.
- **Quoter engine** — computes desired quotes per §3.2–3.4.
- **Order manager** — diffs desired vs resting orders, sends create/cancel, handles
  rate limits and acks; idempotent and crash-safe.
- **Position/inventory tracker** — authoritative inventory and realized/unrealized PnL.
- **Risk manager** — enforces §3.5 hard limits; owns the kill switch.
- **Logger/analytics** — append-only tape + post-hoc metrics (the H1–H5 dashboards).

The same codebase runs in three modes — **record** (Phase 0), **simulate** (Phase 1,
Order manager replaced by the fill simulator), **live** (Phase 2/3) — so the strategy
logic under test is identical to what trades.

### 5.2 Kalshi API specifics
**Read (public, no auth)** — already used in this repo:
- `GET /markets?series_ticker=KXHIGH..&status=open` — the day's ladder.
- `GET /markets/{ticker}/orderbook` → `{"orderbook_fp": {"yes_dollars":[[px,sz]…],
  "no_dollars":[…]}}`. **best YES bid = max(yes_dollars px); best YES ask = 1 − max(no_dollars
  px).** (The market-object `yes_bid/volume/open_interest` fields read null — do **not** use
  them; the book/trades/candlesticks are the truth.)
- `GET /markets/trades?ticker=…` → `count_fp`, `yes_price_dollars`, `taker_side`
  (`"yes"` ⇒ taker bought YES ⇒ maker sold YES), `created_time`.
- `GET /series/{s}/markets/{t}/candlesticks` → OHLC/bid/ask with `_dollars`/`_fp` fields.
- Market-data **WebSocket** for real-time `orderbook_delta` / `trade` (avoids poll latency).

**Trade (authenticated — Phase 2+):**
- Kalshi auth = **API key ID + RSA private key**, signing each request (RSA-PSS over
  `timestamp + method + path`), or a legacy email/password session token.
- `POST /portfolio/orders` (limit/maker order: ticker, side yes/no, action buy/sell, count,
  yes/no price in cents, `post_only` to guarantee maker), `DELETE /portfolio/orders/{id}`,
  batch create/cancel endpoints, `GET /portfolio/positions`, `GET /portfolio/balance`.
- Mind **rate limits** (tiered; market-makers can request elevated limits) and use
  `post_only` so we never accidentally pay taker fees.

### 5.3 Tech choices (proposal — to confirm in the regroup)
- **Language:** Python for Phase 0/1 (reuses this repo's stack: `numpy`, `urllib`/`httpx`,
  `websockets`). For Phase 2 live, Python is adequate given the hour-scale clock; revisit
  only if cancel latency proves binding.
- **Hosting:** a small always-on VPS in **us-east** (close to Kalshi/AWS us-east-1) to
  minimize the cancel-side latency that matters near resolution — *not* run from a Norwegian
  laptop for the live phase. Phase 0/1 can run anywhere.
- **Storage:** append-only Parquet/JSONL tapes; DuckDB for analytics.
- **Secrets:** API key in an env/secret store, never in the repo.

---

## 6. Economic model (what success looks like)

Per-cycle (daily) unit economics, from RESULTS, with explicit haircuts:

```
gross aggregate edge        = +1.0¢ / contract  (+3.5% of notional, maker fee = $0)
× captured share (H1/H2)    = s ∈ [0.1 … 0.5]   (UNKNOWN — Phase 1 measures this)
collateral per contract     ≈ 35¢                (avg min(p,1−p))
⇒ captured return / cycle    = s · 1.0¢ / 35¢ = s · 2.9%   per daily cycle
annualized (≈250 cycles)    = s · 2.9% · 250 ≈ s · 720%    (before frictions)
− Norway tax (28% on gains >10k NOK) and access/withdrawal frictions
− capacity ceiling: ~$61k/day flow/city ⇒ few-$k collateral/city before we move the mid
− LIP rebate: small bonus, capped ~$7k/week
```

Even a **pessimistic** captured share (s≈0.1) and a deep haircut for capacity/tax leaves a
return that clears the 10%/yr bar — *if* H2 holds (our fills aren't toxic). The binding
constraints are **captured share** and **capacity**, not the gross edge. This is why
Phase 1's measured `s` and the capacity ceiling decide everything.

---

## 7. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| We only get **toxic flow** (fast bots decline it) | Phase 1 H2 measures realized PnL on *our* fills under back-of-queue assumption; kill if ≤0 |
| **Information event** (model run / front passing) runs over stale quotes | model-run-boundary re-quote; forecast guardrail widen/pull; stale-quote watchdog |
| **Realized-high pick-off** late in the day | §3.4 rule 2: pull decided buckets once the high is locked via NWS obs |
| **Inventory blow-up** on a temperature surprise | per-bucket + per-ladder caps; inventory skew; whole-ladder MECE netting |
| **Capacity** too small to matter | measure depth in Phase 0; accept it as an income sleeve, not a scalable fund |
| **Kalshi access from Norway** is regulatorily fragile | confirm funding/withdrawal before Phase 2; treat as a real operational risk |
| **Tax/withdrawal** friction (28% >10k NOK) | model net-of-tax in H3; size accordingly |
| **Seasonality** (summer is calm; winter storms = adverse selection) | H5: validate across seasons before scaling; widen in volatile regimes |
| **Single point of failure** (outage while holding inventory) | crash-safe order manager, heartbeat kill, flatten-on-disconnect |

---

## 8. Milestones / definition of done

- **M0 (Phase 0):** continuous book+trade recorder running for ≥2 weeks across 5 cities;
  verified `orderbook_fp` parsing and clean tape.
- **M1 (Phase 1):** quote simulator produces H1/H2 numbers under optimistic/realistic/
  pessimistic queue assumptions; written up as a RESULTS addendum. **Decision point.**
- **M2 (Phase 2):** authenticated live pilot, one city, min size, ≥3 weeks; fill model
  validated against reality (predicted vs actual fills within tolerance).
- **M3 (Phase 3):** multi-city, sized to capacity, LIP enrolled, seasonal monitoring.

Each milestone is a commit + a short results note in this folder. We do not advance a phase
until the prior phase's GO thresholds (§2) are met.

---

## 9. Immediate next step

Build **Phase 0 (the read-only recorder)** and the **Phase 1 simulator** — both
zero-capital, zero-auth, and reusing this repo's HTTP/analytics stack. That produces the
one number the historical data cannot: the **captured** edge `s` for a non-colocated maker.
The infrastructure design for that recorder/simulator is the subject of the next working
session.
