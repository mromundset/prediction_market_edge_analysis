# Prediction Market Edge Analysis

A collection of explorations hunting for **mispricings on prediction markets** (primarily
[Polymarket](https://polymarket.com)). Each exploration tests a specific edge hypothesis
against a real second source — a sportsbook, a sharp, or physical ground truth — because a
model built *from* a market can never find an edge *against* it.

## Structure

Each exploration is a **self-contained folder** with its own code, data, and write-up:

| Exploration | Question | Verdict |
|---|---|---|
| [`lopsided_market_scan/`](lopsided_market_scan/) | Can you profit by shorting "impossible" meme events (Jesus returns, aliens confirmed) that aren't fully priced out? | No clean, sizeable edge — see below |
| [`meteor_strike_edge_exploration/`](meteor_strike_edge_exploration/) | Are Polymarket's 2026 meteor-strike markets mispriced vs the NASA/CNEOS record and the Brown impact-flux model? | Well-calibrated to physics; only a marginal, liquidity-capped lean — [RESULTS.md](meteor_strike_edge_exploration/RESULTS.md) |
| [`crypto_deribit_edge_exploration/`](crypto_deribit_edge_exploration/) | Do Polymarket's daily "BTC/ETH above $K" digitals diverge tradeably from Deribit options-implied probabilities? (Strategy A1) | **No** — apparent gap was a measurement artifact; PM ≈ Deribit, no significant config — [RESULTS.md](crypto_deribit_edge_exploration/RESULTS.md). **Revisited** with risk-neutral→physical adjustment + full forecast-eval toolkit (DM-HLN, encompassing, LOO pooling, power, drift, FWER): residual lean = crypto risk premium, not alpha — [RESULTS_A1_REVISIT.md](crypto_deribit_edge_exploration/RESULTS_A1_REVISIT.md) |
| [`kalshi_cross_venue_exploration/`](kalshi_cross_venue_exploration/) | Is there cross-venue arbitrage between Polymarket and Kalshi on the same contracts? (Strategy A2) | **No** — overlap is tiny/non-fungible; the one deep match (FOMC) is efficient to within fees (~0.8%/yr) — [RESULTS.md](kalshi_cross_venue_exploration/RESULTS.md) |
| [`internal_arb_exploration/`](internal_arb_exploration/) | Is internal/NegRisk Dutch-book arbitrage capturable without a low-latency bot? (Strategy B3) | **No** — 1,005 live books all bracketed by $1.00 to the tick; zero non-latency residual — [RESULTS.md](internal_arb_exploration/RESULTS.md) |
| [`crypto_ladder_d10_exploration/`](crypto_ladder_d10_exploration/) | Are monotonicity violations or RND shape differences exploitable in PM's BTC/ETH daily ladders? (Strategy D10) | **No** — violations are transient bot-corrected artefacts; PM and Deribit agree on distribution shape; one live violation was 0.18% net at near-zero depth — [RESULTS.md](crypto_ladder_d10_exploration/RESULTS.md) |
| [`cross_market_consistency_exploration/`](cross_market_consistency_exploration/) | Do hierarchically related markets violate P(A) ≤ P(B) when A ⊆ B, allowing a risk-free Dutch-book? (Strategy B6) | **No** — 0 violations in 5,401 non-sports events; 10 sports "hits" were all classifier false positives (mutually exclusive NegRisk legs) — [RESULTS.md](cross_market_consistency_exploration/RESULTS.md) |
| [`kalshi_macro_elections_exploration/`](kalshi_macro_elections_exploration/) | Do Kalshi's 2026 US election markets (Senate/House control) or macro-financial markets (CPI, commodities, Treasury) diverge from PM prices enough to trade? (Strategy C3) | **No** — Senate/House control IS fungible across venues; Senate within fees, House best net +1.18% (+2.80%/yr) — below risk-free. No commodity/rate PM equivalent. — [RESULTS.md](kalshi_macro_elections_exploration/RESULTS.md) |
| [`weather_forecast_edge_exploration/`](weather_forecast_edge_exploration/) | Is Kalshi's liquid daily city high-temp market (NWS-resolved) beatable by a numerical weather ensemble? (Strategy C4) | **No** — market is well-calibrated and sharper than a genuine day-ahead GFS forecast (RPS 0.084 vs 0.122); the apparent +63%/trade edge was lookahead contamination (same-day vs day-ahead forecast) — [RESULTS.md](weather_forecast_edge_exploration/RESULTS.md) |

New explorations get a new folder, ideally with a short `RESULTS.md` stating the question,
the second source used, and the conclusion (including negative results).

## Running

Python 3 with internet access (no API keys needed). Per-exploration deps:

```
pip install numpy scipy matplotlib   # meteor_strike_edge_exploration
# lopsided_market_scan uses only the standard library
```

Run a script from inside its folder, e.g.:

```
cd meteor_strike_edge_exploration && python3 meteor_analysis.py
```

## Note

Research tooling, **not financial advice**. Findings are point-in-time snapshots of live
markets and will drift.
