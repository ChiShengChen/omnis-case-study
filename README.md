# Omnis Labs — CLAMM Vault Case Study

Multi-Layer LP strategy backtest, Monte Carlo robustness analysis, divination-based strategies, and interactive dashboard for Steer Protocol vaults on Katana (Ronin L2).

## Live Dashboard

**[omnis-backtest-dashboard.vercel.app](https://omnis-backtest-dashboard.vercel.app/)**

Interactive React + D3.js dashboard with 6 tabs: Performance, X-Ray Heatmap, Monte Carlo, Dual Oracle, Methodology.

## Strategies Compared (9 total)

| # | Strategy | Type | Description |
|---|----------|------|-------------|
| 1 | **Omnis** | On-chain | ATR-based single range, frequent rebalance |
| 2 | **Charm.fi** | On-chain | 3-layer (8.3/74.8/16.9), fixed widths |
| 3 | **Steer** | On-chain | Default Steer strategy (ETH only) |
| 4 | **Multi-Layer (ML)** | Simulated | Charm architecture + trend shift (ours) |
| 5 | **SR-Fixed** | Simulated | Fixed-width single range (overfitted*) |
| 6 | **SR1-RVWidth** | Simulated | Realized volatility adaptive width |
| 7 | **SR2-Lazy** | Simulated | No-chase: only rebalance when price returns |
| 8 | **Meihua (梅花易數)** | Simulated | Chinese I Ching divination driven |
| 9 | **Astro** | Simulated | Western financial astrology driven |

*\*SR-Fixed parameters optimized on same historical data (look-ahead bias).*

## Key Results

| Strategy | WBTC-USDC Alpha | USDC-ETH Alpha | Rebalances (BTC/ETH) |
|----------|----------------|----------------|----------------------|
| Omnis (actual) | -3.65% | -10.86% | 1,287 / 678 |
| Charm.fi (actual) | +1.50% | -1.85% | 516 / 376 |
| **Multi-Layer** | **+1.29%** | **+9.31%** | **48 / 47** |
| SR-Fixed | +14.68%* | +12.32%* | 26 / 8 |
| SR1-RVWidth | +16.96%* | +11.97%* | 13 / 5 |
| SR2-Lazy | +4.46% | +8.39% | 2 / 10 |
| Meihua (梅花) | -1.62% | +6.70% | 4 / 1 |
| Astro (占星) | -0.92% | +10.00% | 4 / 4 |

## CLAMM Performance Metrics

Five CLAMM-specific metrics computed for all vaults:

| Metric | What it measures | Why it matters |
|--------|-----------------|----------------|
| **Fee/IL Ratio** | Total fee earned / Total IL suffered | >1x means fees cover IL (profitable). The single most important CLAMM metric |
| **Max Drawdown** | Worst peak-to-trough alpha decline | How bad can it get? LP's #1 risk question |
| **Sharpe Ratio** | Risk-adjusted alpha (mean/std × √365) | Industry standard. High alpha with high volatility isn't good |
| **Capital Efficiency** | Fee earned per $ per day (bps/day) | Normalizes fee capture across time periods. Narrow ≠ better |
| **IL per Rebalance** | Total IL / number of rebalances (bps) | Quantifies the cost of each Burn→Swap→Mint cycle |

## Core Insight: More Fees ≠ More Profit

USDC-ETH pool (44 days, ETH +3.4%):

| | Omnis | Multi-Layer |
|---|---|---|
| Fee Earned | **29,239 bps** | 53 bps |
| Net Alpha | **-11.21%** | **+2.62%** |
| Cap Efficiency | **655 bps/d** | 1.2 bps/d |
| Fee/IL Ratio | <1x | >1x |

Omnis earned **551× more fees** and had the highest capital efficiency, yet had the worst alpha. Every Burn→Swap→Mint rebalance cycle locks in impermanent loss. With 678 rebalances, cumulative IL consumed all fee income.

**The lesson: in concentrated liquidity, minimizing rebalance damage matters more than maximizing fee capture.**

## Strategy Design

### Multi-Layer (ML) — Charm.fi-inspired 3-layer architecture

| Layer | Allocation | Width | Role |
|-------|-----------|-------|------|
| Full-range | 8.3% | Full tick range | Downside protection |
| Wide | 74.8% | ±17.85% | Main liquidity, moderate IL |
| Narrow | 16.9% | ±3.9% + trend shift | Aggressive fee capture |

Parameters extracted from Charm.fi's 101 on-chain rebalance Mint events. Trend shifting (±1.4x/0.6x) is our addition.

### Single-Range Variants

| Variant | Width Logic | Rebalance Logic |
|---------|-----------|-----------------|
| SR-Fixed | Fixed ±5%/±14.5% (swept) | Boundary trigger + cooldown |
| SR1-RVWidth | k × 7d realized vol | Boundary trigger + cooldown |
| SR2-Lazy | Fixed ±7% | Only when price **returns** to center |

> **Warning:** SR-Fixed and SR1 have look-ahead bias. SR2-Lazy is the only zero-parameter single-range strategy.

### Divination Strategies

| Strategy | Signal Source | Width Mapping | Trend Mapping |
|----------|-------------|---------------|---------------|
| **Meihua (梅花易數)** | Time + price digits → hexagram → 體用五行生克 | 生體=±4% (aggressive), 克體=±20% (defensive) | 動爻位置 → shift direction |
| **Astro (金融占星)** | Planetary positions + aspects + moon phase | Jupiter trine=narrow, Mars square=wide, Mercury Rx=very wide | Moon fire signs=bullish, water=bearish |

Both are deterministic (no tunable parameters) and produce very few rebalances (1-4), acting as "cosmic stop-loss" strategies.

## Monte Carlo Robustness (v2 — wide parameter ranges)

### Parameter Sensitivity (N=1,000, uniform wide ranges)

| Strategy | BTC P(α>0) | ETH P(α>0) |
|----------|-----------|-----------|
| Omnis | 21% | 2% |
| Charm | **92%** | **98%** |
| **ML** | **90%** | **97%** |
| SR-Fixed | 70% | 72% |
| SR1-RVWidth | 58% | 73% |
| SR2-Lazy | 28% | 32% |
| Meihua | — (deterministic) | — |
| Astro | — (deterministic) | — |

### Block Bootstrap (N=500 synthetic price paths)

| Strategy | BTC P(α>0) | BTC Median | ETH P(α>0) | ETH Median |
|----------|-----------|------------|-----------|------------|
| Omnis | 0% | -60% | 0% | -35% |
| Charm | 33% | -3.6% | 31% | **-2.2%** |
| **ML** | **33%** | **-3.7%** | **31%** | **-2.3%** |
| SR-Fixed | 31% | -6.9% | 31% | -3.7% |
| SR1-RVWidth | 31% | -7.2% | 32% | -3.4% |
| SR2-Lazy | 29% | -6.1% | 31% | -4.1% |
| Meihua | 36% | -5.5% | 34% | -3.0% |
| **Astro** | 27% | -5.3% | **53%** | **+1.1%** |

**Key findings:**
- ML and Charm are equally robust (90%+ param sensitivity, best bootstrap downside)
- Astro has the only positive bootstrap median (+1.1% on ETH) — but sample size is small
- All single-range variants have worse bootstrap downside than 3-layer strategies

## Cost Model

| Component | ML (3-Layer) | Single-Range | Divination |
|-----------|-------------|-------------|------------|
| Swap volume per rebalance | 16.9% × 50% TVL | 50% TVL | 50% TVL |
| Slippage per swap | 0.15% | 0.15% | 0.15% |
| Gas (Katana) | ~$0 | ~$0 | ~$0 |
| Rebalances (96d) | 48 | 2-26 | 1-4 |
| Total cost | ~$0.62 | ~$0.10–$2.50 | ~$0.05–$0.30 |

## Data Sources

All data collected from Katana chain via direct JSON-RPC.

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
├── charts/                         # Static PNG charts
├── backtest-dashboard/             # Interactive React+D3 dashboard
│   ├── src/components/             # 11 components + 6 tabs
│   ├── dist/                       # Built static site → Vercel
│   └── data/                       # Processed JSON (intervals, windows, metrics)
│
├── generate_backtest_dashboard.py  # Dashboard data generation (all strategies)
│
├── monte_carlo.py                  # MC: ML param sensitivity + bootstrap
├── mc_all_v2.py                    # MC: all 6 strategies (wide ranges)
├── single_range_sweep.py           # SR: width × cooldown sweep
├── rv_width_strategy.py            # SR1: realized vol + SR2: lazy return
├── meihua_strategy.py              # 梅花易數 divination strategy
├── astro_strategy.py               # Financial astrology strategy
│
├── mc_all_v2_results.json          # MC results (6 strategies)
├── meihua_results.json             # Meihua simulation + bootstrap
├── astro_results.json              # Astro simulation + bootstrap
├── rv_lazy_results.json            # RV-Width + Lazy Return results
│
├── report-vault-performance-zh.md  # Performance report (Chinese)
└── report-jeff-lp-loss-zh.md       # Jeff LP loss analysis (Chinese)
```

## Calibration

| Pool | Our Return | On-chain Report | Deviation |
|------|-----------|----------------|-----------|
| WBTC-USDC | -22.90% | -22.19% | 0.71% |
| USDC-ETH | -10.31% | -8.73% | 1.58% |

## Reproduce

```bash
# 1. Collect on-chain data
python3 collect_wbtc_usdc_data.py
python3 collect_usdc_eth_data.py

# 2. Generate dashboard (all 9 strategies)
python3 generate_backtest_dashboard.py

# 3. Monte Carlo (6 strategies, wide ranges)
python3 mc_all_v2.py

# 4. Divination strategies
python3 meihua_strategy.py
python3 astro_strategy.py

# 5. Single-range experiments
python3 rv_width_strategy.py
```

## Related Repos

- [Omnis-Labs/Steer_demo](https://github.com/Omnis-Labs/Steer_demo) — Main Steer v2 MVP
- [Omnis-Labs/defi-onchain-analytics](https://github.com/Omnis-Labs/defi-onchain-analytics) — AI agent skill for on-chain analysis
- [ChiShengChen/omnis_backtest-dashboard](https://github.com/ChiShengChen/omnis_backtest-dashboard) — Dashboard static site (Vercel)
- [ChiShengChen/omnis-case-study](https://github.com/ChiShengChen/omnis-case-study) — Full case study backup
