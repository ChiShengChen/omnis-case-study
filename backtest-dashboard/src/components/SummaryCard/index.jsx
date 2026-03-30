import { useEffect, useState } from 'react'
import styles from './styles.module.css'
import { POOL_VAULTS, getVaultMetadata, loadWindows, getWindowData } from '../../utils/dataHelpers'
import { fmtPct, fmtBps, fmtDollar, fmtDate } from '../../utils/formatters'
import useDashboardStore from '../../store/dashboard'
import metadata from '../../../data/metadata.json'

export default function SummaryCard() {
  const selectedPool = useDashboardStore(state => state.selectedPool)
  const visibleVaults = useDashboardStore(state => state.visibleVaults)
  const brushRange = useDashboardStore(state => state.brushRange)
  const selectedWindow = useDashboardStore(state => state.selectedWindow)
  const poolVaults = POOL_VAULTS[selectedPool]
  const [windows, setWindows] = useState(null)
  const [clammMetrics, setClammMetrics] = useState(null)

  useEffect(() => {
    loadWindows().then(setWindows)
    import('../../../data/clamm-metrics.json').then(m => setClammMetrics(m.default))
  }, [])

  if (!windows) return <div className={styles.loading}>Loading data…</div>

  const displayVaults = poolVaults.filter(v => visibleVaults.includes(v))
  const omnisVault = displayVaults.find(v => v.startsWith('omnis')) || displayVaults[0]
  
  let windowStart, windowEnd, days
  if (brushRange) {
    windowStart = new Date(brushRange.startDate).toISOString().split('T')[0]
    windowEnd = new Date(brushRange.endDate).toISOString().split('T')[0]
    days = (brushRange.endDate - brushRange.startDate) / 86400000
  } else if (selectedWindow) {
    windowStart = selectedWindow.ei_date
    windowEnd = selectedWindow.xi_date
    days = (new Date(windowEnd) - new Date(windowStart)) / 86400000
  } else {
    // Default to Omnis period
    const omnisDates = windows[omnisVault]?.dates || []
    windowStart = omnisDates[0] || '2025-12-17'
    windowEnd = omnisDates[omnisDates.length - 1] || '2026-03-23'
    days = omnisDates.length ? omnisDates.length - 1 : 97
  }

  const resolveWindowIndices = (vaultDates, startDate, endDate) => {
    if (!vaultDates?.length || !startDate || !endDate) return null
    const startTs = new Date(startDate).getTime()
    const endTs = new Date(endDate).getTime()
    if (Number.isNaN(startTs) || Number.isNaN(endTs) || endTs <= startTs) return null
    let ei = vaultDates.findIndex(d => new Date(d).getTime() >= startTs)
    if (ei === -1) ei = 0
    let xi = -1
    for (let i = vaultDates.length - 1; i >= 0; i--) {
      if (new Date(vaultDates[i]).getTime() <= endTs) {
        xi = i
        break
      }
    }
    if (xi === -1) xi = vaultDates.length - 1
    if (xi <= ei) {
      xi = Math.min(vaultDates.length - 1, ei + 1)
      if (xi <= ei) return null
    }
    return { ei, xi, ei_date: vaultDates[ei], xi_date: vaultDates[xi] }
  }

  const summaryData = displayVaults.map(vaultId => {
    const meta = getVaultMetadata(vaultId)
    const vaultDates = windows[vaultId]?.dates || []
    let data = null
    const snappedWindow = resolveWindowIndices(vaultDates, windowStart, windowEnd)
    if (snappedWindow) {
      data = getWindowData(vaultId, snappedWindow.ei, snappedWindow.xi)
    }
    
    if (!data) {
      data = {
        vault_return: meta.full_period_vault_return,
        hodl_return: meta.full_period_hodl_return,
        alpha: meta.full_period_alpha,
        fee_bps: null,
        realized_vol: null,
        avg_daily_vol_usdc: null,
        price_change: null
      }
    }
    return { vaultId, meta, data }
  })

  const omnisData = summaryData.find(d => d.vaultId.startsWith('omnis'))?.data || summaryData[0]?.data || {}
  const poolMeta = metadata.pools[selectedPool]
  const token0 = poolMeta?.token0 || 'Token0'
  const token1 = poolMeta?.token1 || 'Token1'

  const fmtComposition = (data) => {
    if (data?.entry_token0_pct == null) return '—'
    const t0 = (data.entry_token0_pct * 100).toFixed(0)
    const t1 = ((1 - data.entry_token0_pct) * 100).toFixed(0)
    return `${t0}% ${token0} / ${t1}% ${token1}`
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>WINDOW INFO</span>
        <span className={styles.info}>
          Entry: {fmtDate(windowStart)} • Exit: {fmtDate(windowEnd)} • {days.toFixed(0)} days
        </span>
      </div>
      
      <div className={styles.content}>
        <div className={styles.poolMetrics}>
          <div className={styles.sectionTitle}>POOL METRICS <span className={styles.faint}>(same for all)</span></div>
          <div className={styles.metricRow}>
            <span className={styles.label}>Price Change</span>
            <span className={styles.value}>{fmtPct(omnisData.price_change)}</span>
          </div>
          <div className={styles.metricRow}>
            <span className={styles.label}>Price Volatility</span>
            <span className={styles.value}>{fmtPct(omnisData.realized_vol)}</span>
          </div>
          <div className={styles.metricRow}>
            <span className={styles.label}>Avg Daily Vol</span>
            <span className={styles.value}>{fmtDollar(omnisData.avg_daily_vol_usdc)}</span>
          </div>
        </div>

        <div className={styles.divider} />

        <div className={styles.vaultMetrics}>
          <div className={styles.sectionTitle}>VAULT COMPARISON</div>
          <table className={styles.table}>
            <thead>
              <tr>
                <th></th>
                {summaryData.map(d => (
                  <th key={d.vaultId} style={{ color: d.meta.color }}>
                    {d.meta.label.split(' ')[0]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Vault Return</td>
                {summaryData.map(d => <td key={d.vaultId}>{fmtPct(d.data?.vault_return)}</td>)}
              </tr>
              <tr>
                <td className={styles.hasTooltip}>
                  HODL Return
                  <div className={styles.tooltipIcon}>
                    ⓘ
                    <div className={styles.tooltipContent}>
                      Return from holding the vault's entry-day token mix without LP. Differs per vault because each strategy uses a different range width, resulting in a different {token0}/{token1} ratio at entry.
                    </div>
                  </div>
                </td>
                {summaryData.map(d => <td key={d.vaultId}>{fmtPct(d.data?.hodl_return)}</td>)}
              </tr>
              <tr className={styles.subRow}>
                <td className={styles.subLabel}>Entry Mix</td>
                {summaryData.map(d => (
                  <td key={d.vaultId} className={styles.subValue}>{fmtComposition(d.data)}</td>
                ))}
              </tr>
              <tr>
                <td className={styles.hasTooltip}>
                  Net Alpha
                  <div className={styles.tooltipIcon}>
                    ⓘ
                    <div className={styles.tooltipContent}>
                      Vault Return minus HODL Return. Measures the strategy's value-add over passive holding.
                    </div>
                  </div>
                </td>
                {summaryData.map(d => <td key={d.vaultId}>{fmtPct(d.data?.alpha)}</td>)}
              </tr>
              <tr>
                <td>Fee Earned (bps)</td>
                {summaryData.map(d => <td key={d.vaultId}>{fmtBps(d.data?.fee_bps)}</td>)}
              </tr>
              {clammMetrics && (<>
              <tr>
                <td className={styles.hasTooltip}>
                  Fee/IL Ratio
                  <div className={styles.tooltipIcon}>
                    ⓘ
                    <div className={styles.tooltipContent}>
                      Total fees earned divided by total impermanent loss. Above 1 means fees outweigh IL.
                    </div>
                  </div>
                </td>
                {summaryData.map(d => {
                  const cm = clammMetrics[d.vaultId]
                  if (!cm) return <td key={d.vaultId}>—</td>
                  const v = cm.fee_il_ratio
                  const isInf = v === 'Infinity'
                  const display = isInf ? '∞' : v === 0 ? '0' : `${v.toFixed(2)}x`
                  const color = isInf || v > 1 ? '#22C55E' : v < 1 ? '#EF4444' : 'var(--text-main)'
                  return <td key={d.vaultId} style={{ color }}>{display}</td>
                })}
              </tr>
              <tr>
                <td className={styles.hasTooltip}>
                  Max Drawdown
                  <div className={styles.tooltipIcon}>
                    ⓘ
                    <div className={styles.tooltipContent}>
                      Largest peak-to-trough decline in net alpha over the full period.
                    </div>
                  </div>
                </td>
                {summaryData.map(d => {
                  const cm = clammMetrics[d.vaultId]
                  if (!cm) return <td key={d.vaultId}>—</td>
                  return <td key={d.vaultId} style={{ color: '#EF4444' }}>-{cm.max_drawdown_pct.toFixed(1)}%</td>
                })}
              </tr>
              <tr>
                <td className={styles.hasTooltip}>
                  Sharpe Ratio
                  <div className={styles.tooltipIcon}>
                    ⓘ
                    <div className={styles.tooltipContent}>
                      Annualised Sharpe of daily alpha returns. Measures risk-adjusted outperformance vs HODL.
                    </div>
                  </div>
                </td>
                {summaryData.map(d => {
                  const cm = clammMetrics[d.vaultId]
                  if (!cm) return <td key={d.vaultId}>—</td>
                  const color = cm.sharpe > 0 ? '#22C55E' : cm.sharpe < 0 ? '#EF4444' : 'var(--text-main)'
                  return <td key={d.vaultId} style={{ color }}>{cm.sharpe.toFixed(2)}</td>
                })}
              </tr>
              <tr>
                <td className={styles.hasTooltip}>
                  Cap Efficiency
                  <div className={styles.tooltipIcon}>
                    ⓘ
                    <div className={styles.tooltipContent}>
                      Fee capture normalised per day in basis points. Higher = more capital-efficient.
                    </div>
                  </div>
                </td>
                {summaryData.map(d => {
                  const cm = clammMetrics[d.vaultId]
                  if (!cm) return <td key={d.vaultId}>—</td>
                  return <td key={d.vaultId}>{cm.cap_efficiency_bps_day.toFixed(1)} bps/d</td>
                })}
              </tr>
              <tr>
                <td className={styles.hasTooltip}>
                  IL/Rebalance
                  <div className={styles.tooltipIcon}>
                    ⓘ
                    <div className={styles.tooltipContent}>
                      Impermanent loss per rebalance event in basis points. Lower = less costly rebalances.
                    </div>
                  </div>
                </td>
                {summaryData.map(d => {
                  const cm = clammMetrics[d.vaultId]
                  if (!cm) return <td key={d.vaultId}>—</td>
                  const v = cm.il_per_rebalance_bps
                  // Red intensity: deeper red for higher IL/rebalance
                  const alpha = Math.min(1, v / 200)
                  const color = v > 0 ? `rgba(239, 68, 68, ${0.5 + alpha * 0.5})` : 'var(--text-main)'
                  return <td key={d.vaultId} style={{ color }}>{v.toFixed(0)} bps</td>
                })}
              </tr>
              </>)}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
