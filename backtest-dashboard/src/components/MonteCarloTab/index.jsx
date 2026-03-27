import { useState, useEffect, useRef, useCallback } from 'react'
import * as d3 from 'd3'
import styles from './styles.module.css'
import useDashboardStore from '../../store/dashboard'

const STRATEGY_META = {
  omnis:        { label: 'Omnis',        color: '#e67e22' },
  charm:        { label: 'Charm',        color: '#3498db' },
  ml:           { label: 'Multi-Layer',  color: '#2ecc71' },
  single_range: { label: 'Single-Range', color: '#9b59b6' },
}

const POOL_MAP = { 'WBTC-USDC': 'wbtc-usdc', 'USDC-ETH': 'usdc-eth' }

let _mcData = null
async function loadMCData() {
  if (!_mcData) {
    _mcData = (await import('../../../data/mc_results.json')).default
  }
  return _mcData
}

function fmt(v, decimals = 1) {
  const s = v >= 0 ? '+' : ''
  return `${s}${v.toFixed(decimals)}%`
}

// ─── Histogram component using D3 ───────────────────────────────────

function Histogram({ data, strategies, mode, poolKey }) {
  const svgRef = useRef()
  const tooltipRef = useRef()
  const [tooltip, setTooltip] = useState(null)

  useEffect(() => {
    if (!data || !svgRef.current) return
    const poolData = data[poolKey]
    if (!poolData) return

    const svg = d3.select(svgRef.current)
    const { width, height } = svgRef.current.getBoundingClientRect()
    if (width === 0 || height === 0) return

    svg.selectAll('*').remove()

    const margin = { top: 10, right: 15, bottom: 35, left: 45 }
    const w = width - margin.left - margin.right
    const h = height - margin.top - margin.bottom

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    // Collect all histograms for domain
    const key = mode === 'param' ? 'param' : 'bootstrap'
    const allVals = []
    strategies.forEach(s => {
      const hist = poolData[s]?.[key]?.histogram
      if (hist) allVals.push(...hist)
    })

    if (allVals.length === 0) return

    // Clamp extremes for better visualization
    const p2 = d3.quantile(allVals.sort(d3.ascending), 0.02)
    const p98 = d3.quantile(allVals, 0.98)
    const domainPad = (p98 - p2) * 0.1
    const xMin = Math.min(p2 - domainPad, -5)
    const xMax = Math.max(p98 + domainPad, 5)

    const x = d3.scaleLinear().domain([xMin, xMax]).range([0, w])

    const nBins = 50
    const binGen = d3.bin().domain(x.domain()).thresholds(nBins)

    // For each strategy, compute bins
    const stratBins = {}
    let maxCount = 0
    strategies.forEach(s => {
      const hist = poolData[s]?.[key]?.histogram || []
      const bins = binGen(hist)
      stratBins[s] = bins
      bins.forEach(b => { if (b.length > maxCount) maxCount = b.length })
    })

    const y = d3.scaleLinear().domain([0, maxCount * 1.1]).range([h, 0])

    // Draw histograms (stacked/overlaid with transparency)
    strategies.forEach((s, si) => {
      const bins = stratBins[s]
      const color = STRATEGY_META[s]?.color || '#888'

      g.selectAll(`.bar-${s}`)
        .data(bins)
        .join('rect')
        .attr('class', `bar-${s}`)
        .attr('x', d => x(d.x0) + si * 1)
        .attr('y', d => y(d.length))
        .attr('width', d => Math.max(0, x(d.x1) - x(d.x0) - strategies.length))
        .attr('height', d => h - y(d.length))
        .attr('fill', color)
        .attr('opacity', strategies.length > 1 ? 0.5 : 0.7)
        .on('mousemove', (event, d) => {
          setTooltip({
            x: event.clientX + 10,
            y: event.clientY - 40,
            strategy: STRATEGY_META[s]?.label,
            range: `${d.x0.toFixed(1)}% to ${d.x1.toFixed(1)}%`,
            count: d.length,
            color,
          })
        })
        .on('mouseleave', () => setTooltip(null))
    })

    // Zero line
    if (x.domain()[0] < 0 && x.domain()[1] > 0) {
      g.append('line')
        .attr('x1', x(0)).attr('x2', x(0))
        .attr('y1', 0).attr('y2', h)
        .attr('stroke', '#e74c3c')
        .attr('stroke-width', 2)
        .attr('stroke-dasharray', '4,3')
    }

    // Baseline markers
    strategies.forEach(s => {
      const baseline = poolData[s]?.baseline_alpha
      if (baseline != null && x(baseline) >= 0 && x(baseline) <= w) {
        const color = STRATEGY_META[s]?.color || '#888'
        g.append('line')
          .attr('x1', x(baseline)).attr('x2', x(baseline))
          .attr('y1', 0).attr('y2', h)
          .attr('stroke', color)
          .attr('stroke-width', 2)
      }
    })

    // Axes
    g.append('g')
      .attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).ticks(8).tickFormat(v => `${v}%`))
      .selectAll('text').style('fill', 'var(--text-secondary)').style('font-size', '0.65rem')

    g.append('g')
      .call(d3.axisLeft(y).ticks(5))
      .selectAll('text').style('fill', 'var(--text-secondary)').style('font-size', '0.65rem')

    // Axis labels
    g.append('text')
      .attr('x', w / 2).attr('y', h + 30)
      .attr('text-anchor', 'middle')
      .style('fill', 'var(--text-secondary)')
      .style('font-size', '0.7rem')
      .text('Net Alpha (%)')

    // Grid
    g.selectAll('.grid-line')
      .data(y.ticks(5))
      .join('line')
      .attr('x1', 0).attr('x2', w)
      .attr('y1', d => y(d)).attr('y2', d => y(d))
      .attr('stroke', 'var(--border)')
      .attr('stroke-dasharray', '2,2')
      .attr('opacity', 0.5)

  }, [data, strategies, mode, poolKey])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
      {tooltip && (
        <div className={styles.tooltip} style={{ left: tooltip.x, top: tooltip.y }}>
          <div style={{ color: tooltip.color, fontWeight: 600 }}>{tooltip.strategy}</div>
          <div className={styles.tooltipLabel}>Range</div>
          <div className={styles.tooltipValue}>{tooltip.range}</div>
          <div className={styles.tooltipLabel}>Count</div>
          <div className={styles.tooltipValue}>{tooltip.count}</div>
        </div>
      )}
    </div>
  )
}

// ─── Main component ─────────────────────────────────────────────────

export default function MonteCarloTab() {
  const selectedPool = useDashboardStore(s => s.selectedPool)
  const poolKey = POOL_MAP[selectedPool] || 'wbtc-usdc'

  const [mcData, setMcData] = useState(null)
  const [mode, setMode] = useState('param') // 'param' or 'bootstrap'
  const [visibleStrats, setVisibleStrats] = useState(new Set(['omnis', 'charm', 'ml', 'single_range']))

  useEffect(() => { loadMCData().then(setMcData) }, [])

  const toggleStrat = useCallback((s) => {
    setVisibleStrats(prev => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }, [])

  if (!mcData) return <div style={{ padding: 20, color: 'var(--text-secondary)' }}>Loading Monte Carlo data...</div>

  const poolData = mcData[poolKey]
  if (!poolData) return <div style={{ padding: 20 }}>No data for {selectedPool}</div>

  const strategies = Object.keys(STRATEGY_META).filter(s => poolData[s])
  const activeStrats = strategies.filter(s => visibleStrats.has(s))
  const key = mode === 'param' ? 'param' : 'bootstrap'

  return (
    <div className={styles.container}>
      {/* Summary comparison table */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Strategy Comparison — {selectedPool}</h3>
        <table className={styles.comparisonTable}>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Baseline α</th>
              <th>Param P(α&gt;0)</th>
              <th>Param Median</th>
              <th>Boot P(α&gt;0)</th>
              <th>Boot Median</th>
              <th>Boot 5th</th>
              <th>Boot 95th</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map(s => {
              const d = poolData[s]
              const baseClass = d.baseline_alpha >= 0 ? styles.positive : styles.negative
              return (
                <tr key={s}>
                  <td>
                    <span className={styles.stratName} style={{ color: STRATEGY_META[s].color }}>
                      {STRATEGY_META[s].label}
                    </span>
                  </td>
                  <td className={baseClass}>{fmt(d.baseline_alpha)}</td>
                  <td className={d.param.p_positive >= 50 ? styles.positive : styles.negative}>
                    {d.param.p_positive.toFixed(0)}%
                  </td>
                  <td className={d.param.median >= 0 ? styles.positive : styles.negative}>
                    {fmt(d.param.median)}
                  </td>
                  <td className={d.bootstrap.p_positive >= 50 ? styles.positive : styles.negative}>
                    {d.bootstrap.p_positive.toFixed(0)}%
                  </td>
                  <td className={d.bootstrap.median >= 0 ? styles.positive : styles.negative}>
                    {fmt(d.bootstrap.median)}
                  </td>
                  <td className={d.bootstrap.pct5 >= 0 ? styles.positive : styles.negative}>
                    {fmt(d.bootstrap.pct5)}
                  </td>
                  <td className={d.bootstrap.pct95 >= 0 ? styles.positive : styles.negative}>
                    {fmt(d.bootstrap.pct95)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Controls */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Alpha Distribution</h3>

        <div style={{ display: 'flex', gap: 'var(--spacing-4)', alignItems: 'center', flexWrap: 'wrap', marginBottom: 'var(--spacing-3)' }}>
          <div className={styles.modeToggle}>
            <button
              className={`${styles.modeBtn} ${mode === 'param' ? styles.modeBtnActive : ''}`}
              onClick={() => setMode('param')}
            >
              Parameter Sensitivity
            </button>
            <button
              className={`${styles.modeBtn} ${mode === 'bootstrap' ? styles.modeBtnActive : ''}`}
              onClick={() => setMode('bootstrap')}
            >
              Block Bootstrap
            </button>
          </div>

          <div className={styles.strategyToggle}>
            {strategies.map(s => (
              <button
                key={s}
                className={`${styles.toggleBtn} ${visibleStrats.has(s) ? styles.toggleBtnActive : ''}`}
                style={{ color: visibleStrats.has(s) ? STRATEGY_META[s].color : undefined }}
                onClick={() => toggleStrat(s)}
              >
                {STRATEGY_META[s].label}
              </button>
            ))}
          </div>
        </div>

        {/* Summary cards for active mode */}
        <div className={styles.summaryGrid}>
          {activeStrats.map(s => {
            const d = poolData[s]?.[key]
            if (!d) return null
            return (
              <div key={s} className={styles.summaryCard} style={{ borderTop: `3px solid ${STRATEGY_META[s].color}` }}>
                <div className={styles.summaryLabel}>{STRATEGY_META[s].label}</div>
                <div className={`${styles.summaryValue} ${d.p_positive >= 50 ? styles.positive : styles.negative}`}>
                  P(α&gt;0) = {d.p_positive.toFixed(0)}%
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: 4 }}>
                  Median {fmt(d.median)} &nbsp;|&nbsp; 5th {fmt(d.pct5)} &nbsp;|&nbsp; 95th {fmt(d.pct95)}
                </div>
              </div>
            )
          })}
        </div>

        {/* Histogram chart */}
        <div style={{ height: 320, position: 'relative' }}>
          <Histogram
            data={mcData}
            strategies={activeStrats}
            mode={mode}
            poolKey={poolKey}
          />
        </div>

        <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: 'var(--spacing-2)' }}>
          {mode === 'param'
            ? 'Each strategy\'s parameters randomly perturbed ±30% around their optimal values (N=1,000). Vertical lines = baseline alpha.'
            : 'Price history cut into 4-hour blocks and resampled with replacement to create 500 synthetic paths. Tests strategy robustness across different market regimes.'}
        </div>
      </div>

      {/* Interpretation */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Interpretation Guide</h3>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          <p><strong>Parameter Sensitivity</strong> — Tests how fragile a strategy is to its parameter choices.
            High P(α&gt;0) means the strategy works across a wide range of configurations, not just the
            cherry-picked optimal. Charm and ML both show &gt;99% robustness here.</p>
          <p style={{ marginTop: 8 }}><strong>Block Bootstrap</strong> — Tests how the strategy performs on randomly
            reshuffled market conditions. Low P(α&gt;0) (&lt;50%) is normal for any CLAMM strategy and means
            the strategy cannot guarantee positive alpha in all market regimes. The key comparison is
            <em> relative</em>: which strategy has the least negative downside (5th percentile) while maintaining
            reasonable upside (95th percentile).</p>
          <p style={{ marginTop: 8 }}><strong>Omnis</strong> always shows 0% P(α&gt;0) — its ±2.5% narrow range
            with frequent rebalancing locks in IL regardless of parameters or market path.</p>
        </div>
      </div>
    </div>
  )
}
