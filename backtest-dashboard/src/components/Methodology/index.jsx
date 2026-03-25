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

      <h3>Multi-Layer Strategy (Simulated)</h3>
      <p>
        The Multi-Layer (ML) vaults are <strong>backtested simulations</strong>, not live vaults.
        They model a Charm.fi-inspired 3-layer liquidity architecture using on-chain validated parameters:
      </p>
      <ul>
        <li><strong>Layer 1 — Full-range (8.3%)</strong>: Deployed across the entire tick range. Acts as downside protection; never triggers rebalance IL.</li>
        <li><strong>Layer 2 — Wide (74.8%)</strong>: ±17.85% around current price. Captures most trading fees with moderate IL amplification.</li>
        <li><strong>Layer 3 — Narrow (16.9%)</strong>: ±3.9% with trend-aware asymmetric shifting. Maximizes fee capture near current price.</li>
      </ul>
      <p>
        Parameters (8.3 / 74.8 / 16.9 allocation, 35.7% / 7.8% widths) were extracted from Charm.fi's actual
        on-chain Mint events (101 rebalances). The trend-shifting mechanism in Layer 3 is our addition — in
        downtrending markets, the narrow range shifts down (1.4x below, 0.6x above); in uptrending, vice versa.
      </p>
      <p>
        Rebalance trigger: Layer 3 price exits 90% of range, with minimum 5,000 block (~1.4 hr) cooldown.
        Typical result: ~48 rebalances vs Omnis ~1,300 over the same period.
      </p>

    </div>
  )
}
