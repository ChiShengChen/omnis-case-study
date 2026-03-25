# Omnis Labs — CLAMM Vault Case Study

Multi-Layer LP strategy backtest and performance analysis for Steer Protocol vaults on Katana (Ronin L2).

## Key Results

| Strategy | WBTC-USDC Alpha | USDC-ETH Alpha | Rebalances |
|----------|----------------|----------------|------------|
| Omnis (actual) | -3.65% | -10.86% | 1,287 / 678 |
| Charm.fi (actual) | +1.50% | -1.85% | 516 / 376 |
| **Multi-Layer (ours)** | **+1.29%** | **+3.02%** | **48 / 47** |

## Strategy Design

Charm.fi-inspired 3-layer architecture with trend-aware asymmetric shifting:

| Layer | Allocation | Width | Role |
|-------|-----------|-------|------|
| Full-range | 8.3% | Full tick range | Downside protection |
| Wide | 74.8% | ±17.85% | Main liquidity, moderate IL |
| Narrow | 16.9% | ±3.9% + trend shift | Aggressive fee capture |

Parameters extracted from Charm.fi's 101 on-chain rebalance Mint events. Trend shifting (±1.4x/0.6x) is our addition.

## Live Dashboard

Interactive React + D3.js dashboard: [omnis-backtest-dashboard.vercel.app](https://omnis-backtest-dashboard.vercel.app/)

Charts include: cumulative returns, alpha decomposition, entry/exit heatmaps, rebalance timing, position width, in-range percentage.

## Data Sources

All data collected from Katana chain via direct JSON-RPC using [defi-onchain-analytics](https://github.com/Omnis-Labs/defi-onchain-analytics) skill.

| Data | Pool | Records |
|------|------|---------|
| Price series | WBTC-USDC | 4,157 points |
| Price series | USDC-ETH | 1,914 points |
| Swap events | WBTC-USDC | 187,975 |
| Swap events | USDC-ETH | 391,080 |
| Burn/Collect/Mint events | Both pools | ~44K |
| Share price history | Both vaults | ~1,200 samples |

## Directory Structure

```
case_study/
├── data/                        # WBTC-USDC on-chain data (CSV + JSON)
├── data_eth/                    # USDC-ETH on-chain data
├── charts/                      # Static PNG charts (matplotlib)
├── backtest-dashboard/          # Interactive React+D3 dashboard
│   ├── src/                     # Dashboard source (with ML components)
│   ├── dist/                    # Built static site (deployed to Vercel)
│   └── data/                    # Processed JSON for dashboard
│
├── collect_wbtc_usdc_data.py    # RPC data collection — WBTC-USDC
├── collect_usdc_eth_data.py     # RPC data collection — USDC-ETH
├── collect_share_prices.py      # Vault share price history sampling
├── analyze_charm.py             # Extract Charm.fi strategy parameters
│
├── backtest_engine.py           # V1 backtest (deploy_ratio model)
├── backtest_v2.py               # V2 backtest (calibrated)
├── backtest_v3.py               # V3 backtest (fair comparison)
├── backtest_v3_full.py          # V3 Full V3 liquidity math
├── backtest_eth.py              # USDC-ETH specific backtest
├── backtest_jeff.py             # Jeff LP loss case study
│
├── generate_backtest_dashboard.py  # Dashboard data generation + build
├── export_charts.py             # Static chart export (matplotlib)
├── export_charts_v2.py          # Additional charts (rebalance timing, etc.)
│
├── report-jeff-lp-loss-zh.md          # Jeff early LP loss analysis (Chinese)
├── report-vault-performance-zh.md     # Vault performance report (Chinese)
├── BACKTEST_CALIBRATION_ANALYSIS.md   # Model calibration analysis
└── build_price_series.py        # Price series from swap events
```

## Calibration

Ground truth from vault `totalAmounts()`/`totalSupply()` historical sampling:

| Pool | Our Share Price Return | Report | Deviation |
|------|----------------------|--------|-----------|
| WBTC-USDC | -22.90% | -22.19% | 0.71% |
| USDC-ETH | -10.31% | -8.73% | 1.58% |

## Cost Model

Rebalance costs included in backtest:
- Swap slippage: 0.15% per swap (pool fee 0.05% + price impact 0.10%)
- Only Narrow layer (16.9%) requires token swap per rebalance
- Katana gas: ~$0 (negligible)
- ML total cost: ~$0.62 over 96 days (0.024% of TVL)

## Reproduce

```bash
# 1. Collect on-chain data
python3 collect_wbtc_usdc_data.py
python3 collect_usdc_eth_data.py

# 2. Run backtest
python3 backtest_v3_full.py

# 3. Generate dashboard
python3 generate_backtest_dashboard.py

# 4. Export static charts
python3 export_charts.py
python3 export_charts_v2.py
```

## Related Repos

- [Omnis-Labs/Steer_demo](https://github.com/Omnis-Labs/Steer_demo) — Main Steer v2 MVP with multi-layer strategy implementation
- [Omnis-Labs/defi-onchain-analytics](https://github.com/Omnis-Labs/defi-onchain-analytics) — AI agent skill for on-chain analysis
- [omnis_backtest-dashboard](https://github.com/ChiShengChen/omnis_backtest-dashboard) — Dashboard static site (Vercel)
