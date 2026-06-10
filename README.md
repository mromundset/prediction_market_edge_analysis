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
