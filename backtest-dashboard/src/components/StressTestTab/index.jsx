import { useState, useEffect } from 'react'
import styles from './styles.module.css'

const STRATEGY_COLORS = {
  'ML':          '#22C55E',
  'SR-Fixed':    '#9B59B6',
  'SR1-RVWidth': '#E67E22',
  'SR2-Lazy':    '#1ABC9C',
  'Meihua':      '#8B5CF6',
  'Astro':       '#FF6B9D',
}

const STRATEGY_ORDER = ['ML', 'SR-Fixed', 'SR1-RVWidth', 'SR2-Lazy', 'Meihua', 'Astro']

const SCENARIO_DESCRIPTIONS = {
  'Flash Crash (-20%, 1h)':     'Sudden -20% drop in 1 hour, then price stabilizes. Tests reaction speed.',
  'Black Swan (-40%, 4h)':      'Catastrophic -40% drop over 4 hours with continued bleed. Worst case.',
  'Sustained Bleed (-3%/wk)':   'Gradual -3% per week decline for 12 weeks. Tests patience.',
  'V-Shape (-25% → +30%)':      '-25% crash followed by +30% bounce within 48 hours. Tests whether rebalancing at the bottom locks in unnecessary IL.',
  'Whipsaw (±10%, 6h cycles)':  '±10% oscillations every 6 hours with no net direction. Tests rebalance discipline.',
  'Moonshot (+50%, 1wk)':       '+50% pump over 1 week. Tests upside capture.',
}

const SCENARIO_ORDER = [
  'Flash Crash (-20%, 1h)',
  'Black Swan (-40%, 4h)',
  'Sustained Bleed (-3%/wk)',
  'V-Shape (-25% → +30%)',
  'Whipsaw (±10%, 6h cycles)',
  'Moonshot (+50%, 1wk)',
]

let _stressData = null
async function loadStressData() {
  if (!_stressData) {
    _stressData = (await import('../../../data/stress_test_results.json')).default
  }
  return _stressData
}

function fmt(v, decimals = 2) {
  const s = v >= 0 ? '+' : ''
  return `${s}${v.toFixed(decimals)}%`
}

function alphaColor(alpha) {
  // Gradient: deep red at -35, neutral at 0, deep green at +5
  const clamped = Math.max(-35, Math.min(5, alpha))
  if (clamped >= 0) {
    const t = clamped / 5
    const r = Math.round(30 + (34 - 30) * t)
    const g = Math.round(60 + (197 - 60) * t)
    const b = Math.round(30 + (94 - 30) * t)
    return `rgba(${r}, ${g}, ${b}, ${0.25 + t * 0.45})`
  } else {
    const t = Math.abs(clamped) / 35
    const r = Math.round(60 + (220 - 60) * t)
    const g = Math.round(30)
    const b = Math.round(30)
    return `rgba(${r}, ${g}, ${b}, ${0.15 + t * 0.5})`
  }
}

// ─── Resilience Ranking Cards ──────────────────────────────────────

function RankingCards({ ranking }) {
  return (
    <div className={styles.section}>
      <h3 className={styles.sectionTitle}>Resilience Ranking</h3>
      <div className={styles.rankingGrid}>
        {ranking.map(item => {
          const color = STRATEGY_COLORS[item.strategy] || '#888'
          const alphaClass = item.avg_alpha >= 0 ? styles.positive : styles.negative
          return (
            <div
              key={item.strategy}
              className={styles.rankCard}
              style={{ borderTopColor: color }}
            >
              <div className={styles.rankBadge}>#{item.rank}</div>
              <div className={styles.rankStrategy} style={{ color }}>
                {item.strategy}
              </div>
              <div className={`${styles.rankAlpha} ${alphaClass}`}>
                {fmt(item.avg_alpha)}
              </div>
              <div className={styles.rankRange}>
                worst {fmt(item.worst)} / best {fmt(item.best)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Scenario × Strategy Heatmap ───────────────────────────────────

function ScenarioHeatmap({ scenarios }) {
  return (
    <div className={styles.section}>
      <h3 className={styles.sectionTitle}>Scenario × Strategy Heatmap (Alpha %)</h3>
      <div style={{ overflowX: 'auto' }}>
        <table className={styles.heatmapTable}>
          <thead>
            <tr>
              <th>Scenario</th>
              {STRATEGY_ORDER.map(s => (
                <th key={s} style={{ color: STRATEGY_COLORS[s] }}>{s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SCENARIO_ORDER.map(scenario => {
              const row = scenarios[scenario]
              if (!row) return null
              return (
                <tr key={scenario}>
                  <td>{scenario}</td>
                  {STRATEGY_ORDER.map(strat => {
                    const cell = row[strat]
                    if (!cell) return <td key={strat}>—</td>
                    const bg = alphaColor(cell.alpha)
                    const textColor = cell.alpha >= 0 ? '#4ade80' : '#f87171'
                    return (
                      <td
                        key={strat}
                        className={styles.heatmapCell}
                        style={{ backgroundColor: bg, color: textColor }}
                      >
                        {fmt(cell.alpha)}
                        <span className={styles.heatmapRebalances}>
                          {cell.rebalances} reb
                        </span>
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Scenario Details (Collapsible) ────────────────────────────────

function ScenarioDetails({ scenarios }) {
  const [openScenarios, setOpenScenarios] = useState(new Set())

  function toggle(scenario) {
    setOpenScenarios(prev => {
      const next = new Set(prev)
      if (next.has(scenario)) next.delete(scenario)
      else next.add(scenario)
      return next
    })
  }

  return (
    <div className={styles.section}>
      <h3 className={styles.sectionTitle}>Scenario Details</h3>
      {SCENARIO_ORDER.map(scenario => {
        const isOpen = openScenarios.has(scenario)
        const row = scenarios[scenario]
        if (!row) return null
        return (
          <div key={scenario}>
            <div className={styles.scenarioHeader} onClick={() => toggle(scenario)}>
              <span className={`${styles.scenarioChevron} ${isOpen ? styles.scenarioChevronOpen : ''}`}>
                &#9654;
              </span>
              <span className={styles.scenarioName}>{scenario}</span>
            </div>
            {isOpen && (
              <div className={styles.scenarioBody}>
                <div className={styles.scenarioDescription}>
                  {SCENARIO_DESCRIPTIONS[scenario]}
                </div>
                <table className={styles.detailsTable}>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th>Alpha</th>
                      <th>Vault Return</th>
                      <th>HODL Return</th>
                      <th>Rebalances</th>
                      <th>Fee (bps)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {STRATEGY_ORDER.map(strat => {
                      const cell = row[strat]
                      if (!cell) return null
                      const alphaClass = cell.alpha >= 0 ? styles.positive : styles.negative
                      return (
                        <tr key={strat}>
                          <td>
                            <span className={styles.stratName} style={{ color: STRATEGY_COLORS[strat] }}>
                              {strat}
                            </span>
                          </td>
                          <td className={alphaClass}>{fmt(cell.alpha)}</td>
                          <td className={cell.vault_return >= 0 ? styles.positive : styles.negative}>
                            {fmt(cell.vault_return)}
                          </td>
                          <td className={cell.hodl_return >= 0 ? styles.positive : styles.negative}>
                            {fmt(cell.hodl_return)}
                          </td>
                          <td>{cell.rebalances}</td>
                          <td>{cell.fee_bps.toFixed(1)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Key Takeaways ─────────────────────────────────────────────────

function KeyTakeaways() {
  return (
    <div className={styles.section}>
      <h3 className={styles.sectionTitle}>Key Takeaways</h3>
      <ul className={styles.takeawayList}>
        <li className={styles.takeawayItem}>
          <strong>ML 3-Layer ranked #1</strong> across all stress scenarios, confirming structural robustness
        </li>
        <li className={styles.takeawayItem}>
          <strong>V-Shape is the critical differentiator:</strong> ML and Astro are the only strategies with positive alpha, avoiding IL lock-in at the bottom
        </li>
        <li className={styles.takeawayItem}>
          <strong>Whipsaw exposes single-range weakness:</strong> frequent rebalancing destroys value. ML's 3-layer structure absorbs oscillations
        </li>
        <li className={styles.takeawayItem}>
          <strong>Black Swan:</strong> all strategies lose heavily, but ML loses least (-32% vs -35% for single-range)
        </li>
      </ul>
    </div>
  )
}

// ─── Main Component ────────────────────────────────────────────────

export default function StressTestTab() {
  const [data, setData] = useState(null)

  useEffect(() => {
    loadStressData().then(setData)
  }, [])

  if (!data) {
    return (
      <div style={{ padding: 20, color: 'var(--text-secondary)' }}>
        Loading stress test data...
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <RankingCards ranking={data.resilience_ranking} />
      <ScenarioHeatmap scenarios={data.scenarios} />
      <ScenarioDetails scenarios={data.scenarios} />
      <KeyTakeaways />
    </div>
  )
}
