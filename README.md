# Omnis Labs — CLAMM Vault Case Study

Multi-Layer LP strategy backtest, Monte Carlo robustness analysis, and interactive dashboard for Steer Protocol vaults on Katana (Ronin L2).

## Live Dashboard

**[omnis-backtest-dashboard.vercel.app](https://omnis-backtest-dashboard.vercel.app/)**

Interactive React + D3.js dashboard with 4 tabs: Performance, X-Ray Heatmap, Monte Carlo, Methodology.

## Key Results

| Strategy | WBTC-USDC Alpha | USDC-ETH Alpha | Rebalances (BTC/ETH) |
|----------|----------------|----------------|----------------------|
| Omnis (actual) | -3.65% | -10.86% | 1,287 / 678 |
| Charm.fi (actual) | +1.50% | -1.85% | 516 / 376 |
| **Multi-Layer (ours)** | **+1.29%** | **+3.02%** | **48 / 47** |
| Single-Range (overfitted) | +14.68%* | +5.15%* | 26 / 8 |

*\*Single-Range parameters were optimized on the same historical data — see [Monte Carlo Analysis](#monte-carlo-robustness) for why this is misleading.*

## Core Insight: More Fees ≠ More Profit

USDC-ETH pool (44 days, ETH +3.4%):

| | Omnis | Multi-Layer |
|---|---|---|
| Fee Earned | **29,239 bps** | 53 bps |
| Net Alpha | **-11.21%** | **+2.62%** |
| Rebalances | 678 | 47 |

Omnis earned **551× more fees** yet had the worst alpha. Every Burn→Swap→Mint rebalance cycle locks in impermanent loss. With 678 rebalances, cumulative IL consumed all fee income and then some.

**The lesson: in concentrated liquidity, minimizing rebalance damage matters more than maximizing fee capture.**

## Strategy Design

### Multi-Layer (ML) — Charm.fi-inspired 3-layer architecture

| Layer | Allocation | Width | Role |
|-------|-----------|-------|------|
| Full-range | 8.3% | Full tick range | Downside protection |
| Wide | 74.8% | ±17.85% | Main liquidity, moderate IL |
| Narrow | 16.9% | ±3.9% + trend shift | Aggressive fee capture |

Parameters extracted from Charm.fi's 101 on-chain rebalance Mint events. Trend shifting (±1.4x/0.6x) is our addition — the Narrow layer shifts asymmetrically based on a 20-period price trend.

### Single-Range (SR) — Theoretical upper bound

| Parameter | WBTC-USDC | USDC-ETH |
|-----------|-----------|----------|
| Width | ±5.0% | ±14.5% |
| Cooldown | 5,000 blocks | 1,500 blocks |
| Trend Shift | Yes | Yes |

> **Warning:** SR parameters were found by sweeping ±3%–±25% on the same historical data. This is look-ahead bias. SR serves as a theoretical maximum, not a deployable strategy.

## Monte Carlo Robustness

### Parameter Sensitivity (N=1,000 per strategy)

Each strategy's parameters perturbed ±30% around optimal:

| Strategy | BTC P(α>0) | ETH P(α>0) | Interpretation |
|----------|-----------|-----------|----------------|
| Omnis | 0% | 0% | Structurally broken — no parameter choice helps |
| Charm | 99.9% | 100% | Extremely robust |
| **ML (ours)** | **99.9%** | **100%** | **Same robustness as Charm** |
| Single-Range | 100% | 56.1% | BTC overfitted; ETH coin-flip |

### Block Bootstrap (N=500 synthetic price paths)

Price history cut into 4h blocks and reshuffled:

| Strategy | BTC P(α>0) | BTC Median | ETH P(α>0) | ETH Median |
|----------|-----------|------------|-----------|------------|
| Omnis | 0% | -50%+ | 0% | -35%+ |
| Charm | 31% | -3.9% | 32% | **-2.1%** |
| **ML (ours)** | **31%** | **-4.6%** | **30%** | **-2.6%** |
| Single-Range | 33% | -8.6% | 31% | -4.2% |

**Conclusion:** ML and Charm are equally robust. Single-Range has the worst downside under random market conditions (-8.6% median vs -4.6% for ML). Bootstrap P(α>0) < 50% is expected for any CLAMM strategy.

## Cost Model

Rebalance costs included in all simulations:

| Component | ML (3-Layer) | Single-Range |
|-----------|-------------|-------------|
| Swap volume per rebalance | 16.9% × 50% of TVL | 50% of TVL |
| Slippage per swap | 0.15% (pool fee + impact) | 0.15% |
| Gas (Katana) | ~$0 | ~$0 |
| Total cost (96 days) | ~$0.62 (0.024% TVL) | ~$2.50 (0.10% TVL) |

## Data Sources

All data collected from Katana chain via direct JSON-RPC using [defi-onchain-analytics](https://github.com/Omnis-Labs/defi-onchain-analytics).

| Data | Pool | Records |
|------|------|---------|
| Price series | WBTC-USDC | 4,157 points |
| Price series | USDC-ETH | 1,914 points |
| Swap events | WBTC-USDC | 187,975 |
| Swap events | USDC-ETH | 391,080 |
| Burn/Collect/Mint events | Both pools | ~44K |

## Directory Structure

```
case_study/
├── data/                           # WBTC-USDC on-chain data
├── data_eth/                       # USDC-ETH on-chain data
├── charts/                         # Static PNG charts (matplotlib + MC)
├── backtest-dashboard/             # Interactive React+D3 dashboard
│   ├── src/                        # Dashboard source
│   ├── dist/                       # Built static site → Vercel
│   └── data/                       # Processed JSON
│
├── collect_wbtc_usdc_data.py       # RPC data collection — WBTC-USDC
├── collect_usdc_eth_data.py        # RPC data collection — USDC-ETH
├── analyze_charm.py                # Extract Charm.fi strategy parameters
│
├── backtest_v3_full.py             # Full V3 liquidity math backtest
├── generate_backtest_dashboard.py  # Dashboard data generation + ML/SR sim
│
├── monte_carlo.py                  # MC: param sensitivity + block bootstrap (ML)
├── mc_all_strategies.py            # MC: all 4 strategies comparison
├── single_range_sweep.py           # SR: width × cooldown parameter sweep
├── single_range_mc.py              # MC: SR-specific validation
│
├── monte_carlo_results.json        # ML Monte Carlo output
├── mc_all_results.json             # All-strategy MC output
├── single_range_results.json       # SR sweep output
│
├── export_charts.py                # Static chart export
├── export_charts_v2.py             # Additional charts
│
├── report-vault-performance-zh.md  # Vault performance report (Chinese)
└── report-jeff-lp-loss-zh.md       # Jeff early LP loss analysis (Chinese)
```

## Calibration

Ground truth from vault `totalAmounts()`/`totalSupply()` historical sampling:

| Pool | Our Return | On-chain Report | Deviation |
|------|-----------|----------------|-----------|
| WBTC-USDC | -22.90% | -22.19% | 0.71% |
| USDC-ETH | -10.31% | -8.73% | 1.58% |

## Reproduce

```bash
# 1. Collect on-chain data
python3 collect_wbtc_usdc_data.py
python3 collect_usdc_eth_data.py

# 2. Generate dashboard (includes ML + SR simulation)
python3 generate_backtest_dashboard.py

# 3. Monte Carlo analysis
python3 mc_all_strategies.py

# 4. Single-Range parameter sweep
python3 single_range_sweep.py
python3 single_range_mc.py
```

## Related Repos

- [Omnis-Labs/Steer_demo](https://github.com/Omnis-Labs/Steer_demo) — Main Steer v2 MVP
- [Omnis-Labs/defi-onchain-analytics](https://github.com/Omnis-Labs/defi-onchain-analytics) — AI agent skill for on-chain analysis
- [ChiShengChen/omnis_backtest-dashboard](https://github.com/ChiShengChen/omnis_backtest-dashboard) — Dashboard static site (Vercel)
- [ChiShengChen/omnis-case-study](https://github.com/ChiShengChen/omnis-case-study) — Full case study backup
