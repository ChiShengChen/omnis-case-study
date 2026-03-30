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
      <div className={styles.formula}>share_nav = (amount0 * price + amount1) / total_supply    [for WBTC-USDC]</div>
      <div className={styles.formula}>share_nav = (amount0 + amount1 * ETH_price) / total_supply  [for USDC-ETH]</div>
      <p className={styles.note}>where ETH_price = 1 / pool_price</p>

      <h3>HODL NAV Calculation</h3>
      <div className={styles.formula}>hodl_nav = q0_entry * current_price + q1_entry    [for WBTC-USDC]</div>
      <div className={styles.formula}>hodl_nav = q0_entry + q1_entry * current_ETH_price  [for USDC-ETH]</div>
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

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Multi-Layer Strategy (ML) — Simulated Vaults</h2>
      <p className={styles.note}>ML-WBTC-USDC and ML-USDC-ETH are <strong>backtested simulations</strong>, not live on-chain vaults. They use real price and swap data with simulated position management.</p>

      <h3>Strategy Design</h3>
      <p>Inspired by Charm.fi's on-chain 3-layer architecture (validated from 101 rebalance Mint events):</p>
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

      <h3>Trend-Aware Asymmetric Shifting</h3>
      <p>The Narrow layer shifts asymmetrically based on a 20-period trend signal. Total width stays constant at 7.8%; only the center shifts.</p>
      <div className={styles.formula}>{"trend = clamp((price[t] / price[t-20] - 1) / 0.20, -1, +1)"}</div>
      <table className={styles.table}>
        <thead>
          <tr><th>Market State</th><th>Lower Bound</th><th>Upper Bound</th><th>Effect</th></tr>
        </thead>
        <tbody>
          <tr><td>Sideways (|t| &lt; 0.2)</td><td>price * (1 - 3.9%)</td><td>price * (1 + 3.9%)</td><td>Symmetric</td></tr>
          <tr><td>Downtrend (t &lt; -0.2)</td><td>price * (1 - 5.46%)</td><td>price * (1 + 2.34%)</td><td>More room below</td></tr>
          <tr><td>Uptrend (t &gt; 0.2)</td><td>price * (1 - 2.34%)</td><td>price * (1 + 5.46%)</td><td>More room above</td></tr>
        </tbody>
      </table>

      <h3>Rebalance Trigger</h3>
      <p>Two conditions must both be met:</p>
      <p><strong>Gate 1:</strong> Cooldown — at least 5,000 blocks (~1.4h) since last rebalance</p>
      <p><strong>Gate 2:</strong> Narrow layer price within 10% of boundary or out of range</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>Rebalances (96 days)</th><th>Avg Interval</th></tr>
        </thead>
        <tbody>
          <tr><td>Omnis (actual)</td><td>1,286</td><td>~1.8 hrs</td></tr>
          <tr><td>Multi-Layer</td><td>48</td><td>~2 days</td></tr>
          <tr><td>Charm (actual)</td><td>101</td><td>~22 hrs</td></tr>
        </tbody>
      </table>

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Single-Range Strategy (SR) — Simulated Vaults</h2>
      <p className={styles.note} style={{background: 'rgba(231, 76, 60, 0.1)', border: '1px solid rgba(231, 76, 60, 0.3)', padding: '12px', borderRadius: '6px'}}><strong>Warning: Look-Ahead Bias.</strong> Single-Range parameters were <strong>optimized on the same historical data</strong> used for backtesting. Results should NOT be interpreted as forward-looking expected performance.</p>

      <h3>Strategy Design</h3>
      <p>Deploy 100% of capital into a single concentrated range with trend-aware centering.</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Parameter</th><th>WBTC-USDC</th><th>USDC-ETH</th></tr>
        </thead>
        <tbody>
          <tr><td>Range Width</td><td>±5.0%</td><td>±14.5%</td></tr>
          <tr><td>Cooldown</td><td>5,000 blocks (~1.4h)</td><td>1,500 blocks (~0.4h)</td></tr>
          <tr><td>Boundary Trigger</td><td>5% from edge</td><td>3% from edge</td></tr>
          <tr><td>Trend Shift</td><td colSpan="2">Yes (1.4x / 0.6x asymmetric)</td></tr>
        </tbody>
      </table>
      <p>These parameters were found by sweeping ±3% to ±25% width across the same historical data — classic overfitting.</p>

      <h3>Why SR Alpha Is Misleadingly High</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Metric</th><th>Single-Range</th><th>ML 3-Layer</th></tr>
        </thead>
        <tbody>
          <tr><td>Baseline Alpha (BTC)</td><td>+14.68%</td><td>+1.30%</td></tr>
          <tr><td>Bootstrap P(alpha &gt; 0)</td><td>32%</td><td>31%</td></tr>
          <tr><td>Bootstrap Median</td><td style={{color: '#e74c3c', fontWeight: 'bold'}}>-8.59%</td><td style={{fontWeight: 'bold'}}>-4.56%</td></tr>
          <tr><td>Bootstrap 5th Percentile</td><td style={{color: '#e74c3c', fontWeight: 'bold'}}>-23.97%</td><td style={{fontWeight: 'bold'}}>-17.66%</td></tr>
        </tbody>
      </table>
      <p>On reshuffled market conditions, SR's median alpha is <strong>-8.59%</strong> — nearly twice as bad as ML's -4.56%. The baseline +14.68% only works on this specific 96-day path where prices dropped gradually.</p>

      <h3>When SR Fails</h3>
      <p>• <strong>Flash crash:</strong> A single-day 10% drop instantly pushes price outside ±5%, locking in massive IL on 100% of capital</p>
      <p>• <strong>Sustained trend:</strong> Continuous one-directional movement forces repeated rebalances, each locking IL</p>
      <p>• <strong>No downside protection:</strong> Unlike ML's 8.3% full-range + 74.8% wide layers, SR has zero fallback positions</p>
      <p className={styles.note}>SR demonstrates the <strong>theoretical maximum alpha</strong> achievable with perfect hindsight. It is an upper bound, not a deployable strategy.</p>

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Monte Carlo Robustness Analysis</h2>

      <h3>Parameter Sensitivity (N=1,000 per strategy)</h3>
      <p>Each strategy's parameters randomly perturbed ±30%. Tests whether alpha depends on precise tuning or is structurally robust.</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>BTC P(alpha &gt; 0)</th><th>ETH P(alpha &gt; 0)</th><th>Interpretation</th></tr>
        </thead>
        <tbody>
          <tr><td>Omnis</td><td>0%</td><td>0%</td><td>Structurally broken — no parameter choice helps</td></tr>
          <tr><td>Charm</td><td>99.9%</td><td>100%</td><td>Extremely robust to parameter variation</td></tr>
          <tr><td>ML (ours)</td><td>99.9%</td><td>100%</td><td>Same robustness as Charm</td></tr>
          <tr><td>Single-Range</td><td>100%</td><td>56.1%</td><td>BTC overfitted; ETH only coin-flip</td></tr>
        </tbody>
      </table>

      <h3>Block Bootstrap (N=500 synthetic paths per strategy)</h3>
      <p>Price history cut into 4-hour blocks and reshuffled. Tests robustness across different market regimes.</p>
      <table className={styles.table}>
        <thead>
          <tr><th>Strategy</th><th>BTC P(alpha &gt; 0)</th><th>BTC Median</th><th>ETH P(alpha &gt; 0)</th><th>ETH Median</th></tr>
        </thead>
        <tbody>
          <tr><td>Omnis</td><td>0%</td><td>-50%+</td><td>0%</td><td>-35%+</td></tr>
          <tr><td>Charm</td><td>31%</td><td>-3.9%</td><td>32%</td><td>-2.1%</td></tr>
          <tr><td>ML (ours)</td><td>31%</td><td>-4.6%</td><td>30%</td><td>-2.6%</td></tr>
          <tr><td>Single-Range</td><td>33%</td><td>-8.6%</td><td>31%</td><td>-4.2%</td></tr>
        </tbody>
      </table>
      <p className={styles.note}>Bootstrap P(alpha &gt; 0) below 50% is expected for any CLAMM strategy — concentrated liquidity inherently loses to HODL in sustained trending markets. The key metric is <strong>median and 5th percentile</strong>: lower downside = more robust.</p>

      <h3>Key Insight: More Fees Does Not Mean More Profit</h3>
      <p>USDC-ETH pool over 44 days (ETH +3.4%):</p>
      <table className={styles.table}>
        <thead>
          <tr><th></th><th>Omnis</th><th>Multi-Layer</th></tr>
        </thead>
        <tbody>
          <tr><td>Fee Earned</td><td><strong>29,239 bps</strong></td><td>53 bps</td></tr>
          <tr><td>Net Alpha</td><td style={{color: '#e74c3c', fontWeight: 'bold'}}>-11.21%</td><td style={{color: '#2ecc71', fontWeight: 'bold'}}>+2.62%</td></tr>
          <tr><td>Rebalances</td><td>678</td><td>47</td></tr>
        </tbody>
      </table>
      <p>Omnis earned 551x more fees yet had the worst alpha. Each Burn-Swap-Mint rebalance locks in impermanent loss. <strong>In concentrated liquidity, minimizing rebalance damage matters more than maximizing fee capture.</strong></p>

      <hr style={{ borderColor: 'var(--border-color)', margin: '2rem 0' }} />

      <h2>Simulation Cost Model</h2>
      <table className={styles.table}>
        <thead>
          <tr><th>Cost Component</th><th>Estimate</th><th>Basis</th></tr>
        </thead>
        <tbody>
          <tr><td>Swap volume per rebalance (ML)</td><td>~16.9% * 50% of TVL</td><td>Only Narrow layer needs token ratio adjustment</td></tr>
          <tr><td>Swap volume per rebalance (SR)</td><td>~50% of TVL</td><td>100% of capital in single range</td></tr>
          <tr><td>Pool fee on swap</td><td>0.05%</td><td>5 bps fee tier</td></tr>
          <tr><td>Price impact</td><td>~0.10%</td><td>Conservative estimate for small swaps</td></tr>
          <tr><td>Total slippage per rebalance</td><td>0.15% of swap volume</td><td>Pool fee + price impact</td></tr>
          <tr><td>Gas cost (Katana)</td><td>~$0</td><td>Gas price ~0.001 Gwei</td></tr>
        </tbody>
      </table>

      <h3>Known Limitations</h3>
      <p>• ML and SR vaults are simulations, not live on-chain results</p>
      <p>• Fee uses fixed vault_fee_share rather than dynamic liquidity-proportional accrual</p>
      <p>• Swap slippage assumes constant 0.15%; actual varies with size and depth</p>
      <p>• No MEV or sandwich attack costs modeled</p>
      <p>• Single-Range parameters are optimized on historical data (look-ahead bias)</p>

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
