import styles from './styles.module.css'

export default function Methodology() {
  return (
    <div className={styles.container}>
      <h2>Data Processing Pipeline</h2>

      <h3>Source Data</h3>
      <p>• Vault state snapshots from on-chain data (amount0, amount1, total_supply, price, block)</p>
      <p>• Sampled every ~10,000 blocks (~5.5 hours on Katana)</p>
      <p>• Pool swap volume aggregated in 10K-block windows</p>
      <p>• Fee events from vault rebalance transactions</p>

      <h3>Vault NAV Calculation</h3>
      <div className={styles.formula}>share_nav = (amount0 × price + amount1) / total_supply    [for WBTC-USDC]</div>
      <div className={styles.formula}>share_nav = (amount0 + amount1 × ETH_price) / total_supply  [for USDC-ETH]</div>
      <p className={styles.note}>where ETH_price = 1 / pool_price</p>

      <h3>HODL NAV Calculation</h3>
      <div className={styles.formula}>hodl_nav = q0_entry × current_price + q1_entry    [for WBTC-USDC]</div>
      <div className={styles.formula}>hodl_nav = q0_entry + q1_entry × current_ETH_price  [for USDC-ETH]</div>
      <p className={styles.note}>where q0_entry, q1_entry = per-share token amounts at entry</p>
      <p className={styles.note}>Note: HODL return differs per vault because each vault holds a different token ratio at entry (determined by its LP range width).</p>

      <h3>Return Calculations</h3>
      <div className={styles.formula}>vault_return = share_nav / entry_share_nav - 1</div>
      <div className={styles.formula}>hodl_return = hodl_nav / entry_hodl_nav - 1</div>
      <div className={styles.formula}>net_alpha = vault_return - hodl_return</div>

      <h3>Fee Decomposition</h3>
      <div className={styles.formula}>realized_fee_return = cumulative_fees_usd / entry_vault_nav_usd</div>
      <div className={styles.formula}>residual_drag = net_alpha - realized_fee_return</div>
      <p>Interpretation:</p>
      <p>• Fee Income (realized_fee_return): cumulative trading fees earned by the vault</p>
      <p>• IL + Drag (residual_drag): impermanent loss + rebalancing costs + any other P&L</p>
      <p>• Net Alpha = Fee Income + IL + Drag</p>

      <h3>Rolling Metrics</h3>
      <div className={styles.formula}>realized_vol_14 = stdev(log_returns) over 14-day window</div>
      <p className={styles.note}>where log_returns[i] = ln(price[i] / price[i-1])</p>
      <div className={styles.formula}>price_displacement_14 = |price[t] / price[t-14] - 1|</div>
      <div className={styles.formula}>rolling_window_alpha_14 = vault_return[t,t-14] - hodl_return[t,t-14]</div>

      <h3>Window (Heatmap) Data</h3>
      <p>For each (entry_date, exit_date) pair:</p>
      <p>• vault_return: share_nav at exit / share_nav at entry - 1</p>
      <p>• hodl_return: computed from entry-day per-share token amounts at exit prices</p>
      <p>• alpha: vault_return - hodl_return</p>
      <p>• fee_bps: (cumulative_fees[entry→exit] / entry_vault_nav) × 10000</p>
      <p>• realized_vol: stdev of daily log price returns within window</p>
      <p>• avg_daily_vol_usdc: total pool swap volume / days</p>
      <p>• price_change: exit_price / entry_price - 1</p>
      <p>• entry_token0_pct: USD value of token0 / total USD value at entry</p>

      <h3>Pool-Level Metric Alignment</h3>
      <p>price_change, realized_vol, and avg_daily_vol_usdc are computed from a CANONICAL pool price/volume series (longest available vault's daily data). This ensures these metrics are identical across all vaults in the same pool for the same date range.</p>

      <h3>Volume Data</h3>
      <p>Pool swap volumes from on-chain data, aggregated in 10K-block windows. Volume is mapped to vault observations using bisect-based lookup (finds the volume window containing each vault's observation block).</p>

      <h3>Daily Resampling</h3>
      <p>Dense block-level data is resampled to daily granularity (last observation per day). Date gaps are forward-filled to produce a dense daily matrix for the heatmap.</p>

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Multi-Layer Strategy (ML) — Simulated Vaults</h2>
      <p className={styles.note}>ML-WBTC-USDC and ML-USDC-ETH are <strong>backtested simulations</strong>, not live on-chain vaults. They use real price and swap data with simulated position management.</p>

      <h3>Strategy Design</h3>
      <p>Inspired by Charm.fi's on-chain 3-layer architecture (validated from 101 rebalance Mint events), the Multi-Layer strategy decomposes liquidity into 5 non-overlapping Steer-compatible positions:</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Layer</th><th>Allocation</th><th>Width</th><th>Role</th></tr>
        </thead>
        <tbody>
          <tr><td>Full-range</td><td>8.3%</td><td>Full tick range</td><td>Downside protection; never triggers rebalance IL</td></tr>
          <tr><td>Wide</td><td>74.8%</td><td>±17.85%</td><td>Main liquidity; captures most fees with moderate IL</td></tr>
          <tr><td>Narrow</td><td>16.9%</td><td>±3.9%</td><td>Aggressive fee capture near current price</td></tr>
        </tbody>
      </table>
      <p>The allocation ratios (8.3 / 74.8 / 16.9) and fixed widths (35.7% / 7.8%) were extracted from Charm.fi's actual on-chain Mint events across 101 rebalances.</p>

      <h3>Trend-Aware Asymmetric Shifting</h3>
      <p>The Narrow layer (Layer 3) shifts asymmetrically based on a 20-period trend signal. The total width stays constant at 7.8%; only the center point shifts in the trend direction.</p>

      <h4>Trend Calculation</h4>
      <div className={styles.formula}>{"trend = clamp((price[t] / price[t-20] - 1) / 0.20, -1, +1)"}</div>
      <p>20-period return, normalized to [-1, +1] range (±20% price move maps to ±1). |trend| &lt; 0.2 = sideways; trend &lt; -0.2 = downtrend; trend &gt; 0.2 = uptrend.</p>

      <h4>Asymmetric Bounds</h4>
      <table className={styles.table}>
        <thead>
          <tr><th>Market State</th><th>Lower Bound</th><th>Upper Bound</th><th>Effect</th></tr>
        </thead>
        <tbody>
          <tr><td>Sideways (|t| &lt; 0.2)</td><td>price × (1 - 3.9%)</td><td>price × (1 + 3.9%)</td><td>Symmetric</td></tr>
          <tr><td>Downtrend (t &lt; -0.2)</td><td>price × (1 - 5.46%)</td><td>price × (1 + 2.34%)</td><td>More room below; fewer rebalances during drops</td></tr>
          <tr><td>Uptrend (t &gt; 0.2)</td><td>price × (1 - 2.34%)</td><td>price × (1 + 5.46%)</td><td>More room above; fewer rebalances during rallies</td></tr>
        </tbody>
      </table>
      <p>Layers 1 (full-range) and 2 (wide) always use symmetric ranges and do not shift with trend.</p>

      <h3>Rebalance Trigger</h3>
      <p>Two conditions must both be met before a rebalance executes:</p>

      <h4>Gate 1: Minimum Cooldown</h4>
      <div className={styles.formula}>{"if (current_block - last_rebalance_block) < 5,000:  → skip (no rebalance)"}</div>
      <p>5,000 blocks ≈ 1.4 hours on Katana. Even if price exits the range, the strategy waits. This prevents rapid-fire rebalancing during high volatility.</p>

      <h4>Gate 2: Narrow Layer Boundary Check</h4>
      <p>Only the Narrow layer (16.9% of capital) is checked. Wide and Full-range are wide enough to rarely go out of range.</p>
      <div className={styles.formula}>{"Trigger if: price < narrow_lower OR price > narrow_upper OR position within 10% of boundary"}</div>

      <h4>What Happens on Rebalance</h4>
      <p>1. Burn all 3 layers → recover tokens to idle balance</p>
      <p>2. Swap the Narrow portion's tokens to match new range's required ratio</p>
      <p>3. Mint 3 new layers centered on current price (with trend shift applied to Narrow)</p>

      <h4>Rebalance Frequency</h4>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>Rebalances (96 days)</th><th>Avg Interval</th></tr>
        </thead>
        <tbody>
          <tr><td>Omnis (actual)</td><td>1,286</td><td>~6,400 blocks (~1.8 hrs)</td></tr>
          <tr><td>Multi-Layer</td><td>48</td><td>~173,000 blocks (~2 days)</td></tr>
          <tr><td>Charm (actual)</td><td>101</td><td>~82,000 blocks (~22 hrs)</td></tr>
        </tbody>
      </table>

      <h3>Steer Contract Format</h3>
      <p>The 3 overlapping layers are decomposed into 5 non-overlapping positions for the Steer vault contract:</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Segment</th><th>Coverage</th><th>Weight (of 65536)</th><th>Layers Active</th></tr>
        </thead>
        <tbody>
          <tr><td>S1 (edge)</td><td>[price_min, wide_lo)</td><td>~1,923</td><td>Full-range only</td></tr>
          <tr><td>S2 (mid)</td><td>[wide_lo, narrow_lo)</td><td>~19,257</td><td>Full-range + Wide</td></tr>
          <tr><td>S3 (core)</td><td>[narrow_lo, narrow_hi]</td><td>~23,173</td><td>All three layers</td></tr>
          <tr><td>S4 (mid)</td><td>(narrow_hi, wide_hi]</td><td>~19,257</td><td>Full-range + Wide</td></tr>
          <tr><td>S5 (edge)</td><td>(wide_hi, price_max]</td><td>~1,926</td><td>Full-range only</td></tr>
        </tbody>
      </table>
      <p>Positions are sorted ascending by tick, non-overlapping, with integer weights summing to 65,536.</p>

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Simulation Methodology & Cost Model</h2>

      <h3>Data Sources</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Data</th><th>Source</th><th>Real / Simulated</th></tr>
        </thead>
        <tbody>
          <tr><td>Price series</td><td>Pool slot0() sqrtPriceX96 via Katana RPC</td><td>Real (on-chain)</td></tr>
          <tr><td>Swap events (187K / 391K)</td><td>eth_getLogs Swap topic</td><td>Real (on-chain)</td></tr>
          <tr><td>Omnis/Charm rebalance history</td><td>eth_getLogs Burn+Mint topics</td><td>Real (on-chain)</td></tr>
          <tr><td>ML position decisions</td><td>Simulated from strategy logic</td><td>Simulated</td></tr>
          <tr><td>ML fee income</td><td>Real swaps × simulated in-range check</td><td>Semi-real</td></tr>
          <tr><td>ML IL/position value</td><td>Full V3 liquidity math simulation</td><td>Simulated</td></tr>
        </tbody>
      </table>

      <h3>V3 Liquidity Math</h3>
      <div className={styles.formula}>{"x = L × (1/√P - 1/√P_upper)   [base token]\ny = L × (√P - √P_lower)         [quote token]\nL = min(x/(1/√P - 1/√P_upper), y/(√P - √P_lower))"}</div>

      <h3>Rebalance Cost Model</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Cost Component</th><th>Estimate</th><th>Basis</th></tr>
        </thead>
        <tbody>
          <tr><td>Swap volume per rebalance</td><td>~16.9% × 50% of TVL</td><td>Only Narrow layer needs token ratio adjustment</td></tr>
          <tr><td>Pool fee on swap</td><td>0.05%</td><td>5 bps fee tier</td></tr>
          <tr><td>Price impact</td><td>~0.10%</td><td>Conservative estimate for small swaps</td></tr>
          <tr><td>Total slippage per rebalance</td><td>0.15% of swap volume</td><td>Pool fee + price impact</td></tr>
          <tr><td>Gas cost (Katana)</td><td>~$0</td><td>Gas price ~0.001 Gwei</td></tr>
        </tbody>
      </table>

      <h3>Cost Impact</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>Rebalances</th><th>Total Cost</th><th>Cost % of TVL</th></tr>
        </thead>
        <tbody>
          <tr><td>Multi-Layer</td><td>48</td><td>~$0.62</td><td>0.024%</td></tr>
          <tr><td>Omnis (actual)</td><td>1,286</td><td>~$97.49</td><td>3.75%</td></tr>
        </tbody>
      </table>
      <p className={styles.note}>Multi-Layer's cost is 157× lower: 96% fewer rebalances, and only 16.9% of capital needs swap per rebalance.</p>

      <h3>Known Limitations</h3>
      <p>• ML vaults are simulations, not live on-chain results</p>
      <p>• Fee uses fixed vault_fee_share rather than dynamic liquidity-proportional accrual</p>
      <p>• Swap slippage assumes constant 0.15%; actual varies with size and depth</p>
      <p>• No MEV or sandwich attack costs modeled</p>

      <h3>Calibration</h3>
      <p>Validated against on-chain ground truth (vault totalAmounts/totalSupply sampling):</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Pool</th><th>Our Share Price Return</th><th>Report</th><th>Deviation</th></tr>
        </thead>
        <tbody>
          <tr><td>WBTC-USDC</td><td>-22.90%</td><td>-22.19%</td><td>0.71%</td></tr>
          <tr><td>USDC-ETH</td><td>-10.31%</td><td>-8.73%</td><td>1.58%</td></tr>
        </tbody>
      </table>


      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Multi-Layer Strategy (ML) — Simulated Vaults</h2>
      <p className={styles.note}>ML-WBTC-USDC and ML-USDC-ETH are <strong>backtested simulations</strong>, not live on-chain vaults. They use real price and swap data with simulated position management.</p>

      <h3>Strategy Design</h3>
      <p>Inspired by Charm.fi's on-chain 3-layer architecture (validated from 101 rebalance Mint events), the Multi-Layer strategy decomposes liquidity into 5 non-overlapping Steer-compatible positions:</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Layer</th><th>Allocation</th><th>Width</th><th>Role</th></tr>
        </thead>
        <tbody>
          <tr><td>Full-range</td><td>8.3%</td><td>Full tick range</td><td>Downside protection; never triggers rebalance IL</td></tr>
          <tr><td>Wide</td><td>74.8%</td><td>±17.85%</td><td>Main liquidity; captures most fees with moderate IL</td></tr>
          <tr><td>Narrow</td><td>16.9%</td><td>±3.9%</td><td>Aggressive fee capture near current price</td></tr>
        </tbody>
      </table>
      <p>The allocation ratios (8.3 / 74.8 / 16.9) and fixed widths (35.7% / 7.8%) were extracted from Charm.fi's actual on-chain Mint events across 101 rebalances.</p>

      <h3>Trend-Aware Asymmetric Shifting</h3>
      <p>The Narrow layer (Layer 3) shifts asymmetrically based on a 20-period trend signal. The total width stays constant at 7.8%; only the center point shifts in the trend direction.</p>

      <h4>Trend Calculation</h4>
      <div className={styles.formula}>{"trend = clamp((price[t] / price[t-20] - 1) / 0.20, -1, +1)"}</div>
      <p>20-period return, normalized to [-1, +1] range (±20% price move maps to ±1). |trend| &lt; 0.2 = sideways; trend &lt; -0.2 = downtrend; trend &gt; 0.2 = uptrend.</p>

      <h4>Asymmetric Bounds</h4>
      <table className={styles.table}>
        <thead>
          <tr><th>Market State</th><th>Lower Bound</th><th>Upper Bound</th><th>Effect</th></tr>
        </thead>
        <tbody>
          <tr><td>Sideways (|t| &lt; 0.2)</td><td>price × (1 - 3.9%)</td><td>price × (1 + 3.9%)</td><td>Symmetric</td></tr>
          <tr><td>Downtrend (t &lt; -0.2)</td><td>price × (1 - 5.46%)</td><td>price × (1 + 2.34%)</td><td>More room below; fewer rebalances during drops</td></tr>
          <tr><td>Uptrend (t &gt; 0.2)</td><td>price × (1 - 2.34%)</td><td>price × (1 + 5.46%)</td><td>More room above; fewer rebalances during rallies</td></tr>
        </tbody>
      </table>
      <p>Layers 1 (full-range) and 2 (wide) always use symmetric ranges and do not shift with trend.</p>

      <h3>Rebalance Trigger</h3>
      <p>Two conditions must both be met before a rebalance executes:</p>

      <h4>Gate 1: Minimum Cooldown</h4>
      <div className={styles.formula}>{"if (current_block - last_rebalance_block) < 5,000:  → skip (no rebalance)"}</div>
      <p>5,000 blocks ≈ 1.4 hours on Katana. Even if price exits the range, the strategy waits. This prevents rapid-fire rebalancing during high volatility.</p>

      <h4>Gate 2: Narrow Layer Boundary Check</h4>
      <p>Only the Narrow layer (16.9% of capital) is checked. Wide and Full-range are wide enough to rarely go out of range.</p>
      <div className={styles.formula}>{"Trigger if: price < narrow_lower OR price > narrow_upper OR position within 10% of boundary"}</div>

      <h4>What Happens on Rebalance</h4>
      <p>1. Burn all 3 layers → recover tokens to idle balance</p>
      <p>2. Swap the Narrow portion's tokens to match new range's required ratio</p>
      <p>3. Mint 3 new layers centered on current price (with trend shift applied to Narrow)</p>

      <h4>Rebalance Frequency</h4>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>Rebalances (96 days)</th><th>Avg Interval</th></tr>
        </thead>
        <tbody>
          <tr><td>Omnis (actual)</td><td>1,286</td><td>~6,400 blocks (~1.8 hrs)</td></tr>
          <tr><td>Multi-Layer</td><td>48</td><td>~173,000 blocks (~2 days)</td></tr>
          <tr><td>Charm (actual)</td><td>101</td><td>~82,000 blocks (~22 hrs)</td></tr>
        </tbody>
      </table>

      <h3>Steer Contract Format</h3>
      <p>The 3 overlapping layers are decomposed into 5 non-overlapping positions for the Steer vault contract:</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Segment</th><th>Coverage</th><th>Weight (of 65536)</th><th>Layers Active</th></tr>
        </thead>
        <tbody>
          <tr><td>S1 (edge)</td><td>[price_min, wide_lo)</td><td>~1,923</td><td>Full-range only</td></tr>
          <tr><td>S2 (mid)</td><td>[wide_lo, narrow_lo)</td><td>~19,257</td><td>Full-range + Wide</td></tr>
          <tr><td>S3 (core)</td><td>[narrow_lo, narrow_hi]</td><td>~23,173</td><td>All three layers</td></tr>
          <tr><td>S4 (mid)</td><td>(narrow_hi, wide_hi]</td><td>~19,257</td><td>Full-range + Wide</td></tr>
          <tr><td>S5 (edge)</td><td>(wide_hi, price_max]</td><td>~1,926</td><td>Full-range only</td></tr>
        </tbody>
      </table>
      <p>Positions are sorted ascending by tick, non-overlapping, with integer weights summing to 65,536.</p>

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Simulation Methodology & Cost Model</h2>

      <h3>Data Sources</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Data</th><th>Source</th><th>Real / Simulated</th></tr>
        </thead>
        <tbody>
          <tr><td>Price series</td><td>Pool slot0() sqrtPriceX96 via Katana RPC</td><td>Real (on-chain)</td></tr>
          <tr><td>Swap events (187K / 391K)</td><td>eth_getLogs Swap topic</td><td>Real (on-chain)</td></tr>
          <tr><td>Omnis/Charm rebalance history</td><td>eth_getLogs Burn+Mint topics</td><td>Real (on-chain)</td></tr>
          <tr><td>ML position decisions</td><td>Simulated from strategy logic</td><td>Simulated</td></tr>
          <tr><td>ML fee income</td><td>Real swaps × simulated in-range check</td><td>Semi-real</td></tr>
          <tr><td>ML IL/position value</td><td>Full V3 liquidity math simulation</td><td>Simulated</td></tr>
        </tbody>
      </table>

      <h3>V3 Liquidity Math</h3>
      <div className={styles.formula}>{"x = L × (1/√P - 1/√P_upper)   [base token]\ny = L × (√P - √P_lower)         [quote token]\nL = min(x/(1/√P - 1/√P_upper), y/(√P - √P_lower))"}</div>

      <h3>Rebalance Cost Model</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Cost Component</th><th>Estimate</th><th>Basis</th></tr>
        </thead>
        <tbody>
          <tr><td>Swap volume per rebalance</td><td>~16.9% × 50% of TVL</td><td>Only Narrow layer needs token ratio adjustment</td></tr>
          <tr><td>Pool fee on swap</td><td>0.05%</td><td>5 bps fee tier</td></tr>
          <tr><td>Price impact</td><td>~0.10%</td><td>Conservative estimate for small swaps</td></tr>
          <tr><td>Total slippage per rebalance</td><td>0.15% of swap volume</td><td>Pool fee + price impact</td></tr>
          <tr><td>Gas cost (Katana)</td><td>~$0</td><td>Gas price ~0.001 Gwei</td></tr>
        </tbody>
      </table>

      <h3>Cost Impact</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>Rebalances</th><th>Total Cost</th><th>Cost % of TVL</th></tr>
        </thead>
        <tbody>
          <tr><td>Multi-Layer</td><td>48</td><td>~$0.62</td><td>0.024%</td></tr>
          <tr><td>Omnis (actual)</td><td>1,286</td><td>~$97.49</td><td>3.75%</td></tr>
        </tbody>
      </table>
      <p className={styles.note}>Multi-Layer's cost is 157× lower: 96% fewer rebalances, and only 16.9% of capital needs swap per rebalance.</p>

      <h3>Known Limitations</h3>
      <p>• ML vaults are simulations, not live on-chain results</p>
      <p>• Fee uses fixed vault_fee_share rather than dynamic liquidity-proportional accrual</p>
      <p>• Swap slippage assumes constant 0.15%; actual varies with size and depth</p>
      <p>• No MEV or sandwich attack costs modeled</p>

      <h3>Calibration</h3>
      <p>Validated against on-chain ground truth (vault totalAmounts/totalSupply sampling):</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Pool</th><th>Our Share Price Return</th><th>Report</th><th>Deviation</th></tr>
        </thead>
        <tbody>
          <tr><td>WBTC-USDC</td><td>-22.90%</td><td>-22.19%</td><td>0.71%</td></tr>
          <tr><td>USDC-ETH</td><td>-10.31%</td><td>-8.73%</td><td>1.58%</td></tr>
        </tbody>
      </table>


      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Multi-Layer Strategy (ML) — Simulated Vaults</h2>
      <p className={styles.note}>ML-WBTC-USDC and ML-USDC-ETH are <strong>backtested simulations</strong>, not live on-chain vaults. They use real price and swap data with simulated position management.</p>

      <h3>Strategy Design</h3>
      <p>Inspired by Charm.fi's on-chain 3-layer architecture (validated from 101 rebalance Mint events), the Multi-Layer strategy decomposes liquidity into 5 non-overlapping Steer-compatible positions:</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Layer</th><th>Allocation</th><th>Width</th><th>Role</th></tr>
        </thead>
        <tbody>
          <tr><td>Full-range</td><td>8.3%</td><td>Full tick range</td><td>Downside protection; never triggers rebalance IL</td></tr>
          <tr><td>Wide</td><td>74.8%</td><td>±17.85%</td><td>Main liquidity; captures most fees with moderate IL</td></tr>
          <tr><td>Narrow</td><td>16.9%</td><td>±3.9%</td><td>Aggressive fee capture near current price</td></tr>
        </tbody>
      </table>
      <p>The allocation ratios (8.3 / 74.8 / 16.9) and fixed widths (35.7% / 7.8%) were extracted from Charm.fi's actual on-chain Mint events across 101 rebalances.</p>

      <h3>Trend-Aware Asymmetric Shifting</h3>
      <p>The Narrow layer (Layer 3) shifts asymmetrically based on a 20-period trend signal. The total width stays constant at 7.8%; only the center point shifts in the trend direction.</p>

      <h4>Trend Calculation</h4>
      <div className={styles.formula}>{"trend = clamp((price[t] / price[t-20] - 1) / 0.20, -1, +1)"}</div>
      <p>20-period return, normalized to [-1, +1] range (±20% price move maps to ±1). |trend| &lt; 0.2 = sideways; trend &lt; -0.2 = downtrend; trend &gt; 0.2 = uptrend.</p>

      <h4>Asymmetric Bounds</h4>
      <table className={styles.table}>
        <thead>
          <tr><th>Market State</th><th>Lower Bound</th><th>Upper Bound</th><th>Effect</th></tr>
        </thead>
        <tbody>
          <tr><td>Sideways (|t| &lt; 0.2)</td><td>price × (1 - 3.9%)</td><td>price × (1 + 3.9%)</td><td>Symmetric</td></tr>
          <tr><td>Downtrend (t &lt; -0.2)</td><td>price × (1 - 5.46%)</td><td>price × (1 + 2.34%)</td><td>More room below; fewer rebalances during drops</td></tr>
          <tr><td>Uptrend (t &gt; 0.2)</td><td>price × (1 - 2.34%)</td><td>price × (1 + 5.46%)</td><td>More room above; fewer rebalances during rallies</td></tr>
        </tbody>
      </table>
      <p>Layers 1 (full-range) and 2 (wide) always use symmetric ranges and do not shift with trend.</p>

      <h3>Rebalance Trigger</h3>
      <p>Two conditions must both be met before a rebalance executes:</p>

      <h4>Gate 1: Minimum Cooldown</h4>
      <div className={styles.formula}>{"if (current_block - last_rebalance_block) < 5,000:  → skip (no rebalance)"}</div>
      <p>5,000 blocks ≈ 1.4 hours on Katana. Even if price exits the range, the strategy waits. This prevents rapid-fire rebalancing during high volatility.</p>

      <h4>Gate 2: Narrow Layer Boundary Check</h4>
      <p>Only the Narrow layer (16.9% of capital) is checked. Wide and Full-range are wide enough to rarely go out of range.</p>
      <div className={styles.formula}>{"Trigger if: price < narrow_lower OR price > narrow_upper OR position within 10% of boundary"}</div>

      <h4>What Happens on Rebalance</h4>
      <p>1. Burn all 3 layers → recover tokens to idle balance</p>
      <p>2. Swap the Narrow portion's tokens to match new range's required ratio</p>
      <p>3. Mint 3 new layers centered on current price (with trend shift applied to Narrow)</p>

      <h4>Rebalance Frequency</h4>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>Rebalances (96 days)</th><th>Avg Interval</th></tr>
        </thead>
        <tbody>
          <tr><td>Omnis (actual)</td><td>1,286</td><td>~6,400 blocks (~1.8 hrs)</td></tr>
          <tr><td>Multi-Layer</td><td>48</td><td>~173,000 blocks (~2 days)</td></tr>
          <tr><td>Charm (actual)</td><td>101</td><td>~82,000 blocks (~22 hrs)</td></tr>
        </tbody>
      </table>

      <h3>Steer Contract Format</h3>
      <p>The 3 overlapping layers are decomposed into 5 non-overlapping positions for the Steer vault contract:</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Segment</th><th>Coverage</th><th>Weight (of 65536)</th><th>Layers Active</th></tr>
        </thead>
        <tbody>
          <tr><td>S1 (edge)</td><td>[price_min, wide_lo)</td><td>~1,923</td><td>Full-range only</td></tr>
          <tr><td>S2 (mid)</td><td>[wide_lo, narrow_lo)</td><td>~19,257</td><td>Full-range + Wide</td></tr>
          <tr><td>S3 (core)</td><td>[narrow_lo, narrow_hi]</td><td>~23,173</td><td>All three layers</td></tr>
          <tr><td>S4 (mid)</td><td>(narrow_hi, wide_hi]</td><td>~19,257</td><td>Full-range + Wide</td></tr>
          <tr><td>S5 (edge)</td><td>(wide_hi, price_max]</td><td>~1,926</td><td>Full-range only</td></tr>
        </tbody>
      </table>
      <p>Positions are sorted ascending by tick, non-overlapping, with integer weights summing to 65,536.</p>

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Simulation Methodology & Cost Model</h2>

      <h3>Data Sources</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Data</th><th>Source</th><th>Real / Simulated</th></tr>
        </thead>
        <tbody>
          <tr><td>Price series</td><td>Pool slot0() sqrtPriceX96 via Katana RPC</td><td>Real (on-chain)</td></tr>
          <tr><td>Swap events (187K / 391K)</td><td>eth_getLogs Swap topic</td><td>Real (on-chain)</td></tr>
          <tr><td>Omnis/Charm rebalance history</td><td>eth_getLogs Burn+Mint topics</td><td>Real (on-chain)</td></tr>
          <tr><td>ML position decisions</td><td>Simulated from strategy logic</td><td>Simulated</td></tr>
          <tr><td>ML fee income</td><td>Real swaps × simulated in-range check</td><td>Semi-real</td></tr>
          <tr><td>ML IL/position value</td><td>Full V3 liquidity math simulation</td><td>Simulated</td></tr>
        </tbody>
      </table>

      <h3>V3 Liquidity Math</h3>
      <div className={styles.formula}>{"x = L × (1/√P - 1/√P_upper)   [base token]\ny = L × (√P - √P_lower)         [quote token]\nL = min(x/(1/√P - 1/√P_upper), y/(√P - √P_lower))"}</div>

      <h3>Rebalance Cost Model</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Cost Component</th><th>Estimate</th><th>Basis</th></tr>
        </thead>
        <tbody>
          <tr><td>Swap volume per rebalance</td><td>~16.9% × 50% of TVL</td><td>Only Narrow layer needs token ratio adjustment</td></tr>
          <tr><td>Pool fee on swap</td><td>0.05%</td><td>5 bps fee tier</td></tr>
          <tr><td>Price impact</td><td>~0.10%</td><td>Conservative estimate for small swaps</td></tr>
          <tr><td>Total slippage per rebalance</td><td>0.15% of swap volume</td><td>Pool fee + price impact</td></tr>
          <tr><td>Gas cost (Katana)</td><td>~$0</td><td>Gas price ~0.001 Gwei</td></tr>
        </tbody>
      </table>

      <h3>Cost Impact</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>Rebalances</th><th>Total Cost</th><th>Cost % of TVL</th></tr>
        </thead>
        <tbody>
          <tr><td>Multi-Layer</td><td>48</td><td>~$0.62</td><td>0.024%</td></tr>
          <tr><td>Omnis (actual)</td><td>1,286</td><td>~$97.49</td><td>3.75%</td></tr>
        </tbody>
      </table>
      <p className={styles.note}>Multi-Layer's cost is 157× lower: 96% fewer rebalances, and only 16.9% of capital needs swap per rebalance.</p>

      <h3>Known Limitations</h3>
      <p>• ML vaults are simulations, not live on-chain results</p>
      <p>• Fee uses fixed vault_fee_share rather than dynamic liquidity-proportional accrual</p>
      <p>• Swap slippage assumes constant 0.15%; actual varies with size and depth</p>
      <p>• No MEV or sandwich attack costs modeled</p>

      <h3>Calibration</h3>
      <p>Validated against on-chain ground truth (vault totalAmounts/totalSupply sampling):</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Pool</th><th>Our Share Price Return</th><th>Report</th><th>Deviation</th></tr>
        </thead>
        <tbody>
          <tr><td>WBTC-USDC</td><td>-22.90%</td><td>-22.19%</td><td>0.71%</td></tr>
          <tr><td>USDC-ETH</td><td>-10.31%</td><td>-8.73%</td><td>1.58%</td></tr>
        </tbody>
      </table>

    </div>
  )
}
