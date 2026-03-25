import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import styles from './styles.module.css'
import { getVaultMetadata, POOL_VAULTS, loadWindows } from '../../utils/dataHelpers'
import useDashboardStore from '../../store/dashboard'
import { fmtPct, fmtBps, fmtDollar } from '../../utils/formatters'

export default function M3Heatmap() {
  const selectedPool = useDashboardStore(state => state.selectedPool)
  const visibleVaults = useDashboardStore(state => state.visibleVaults)
  const selectedWindow = useDashboardStore(state => state.selectedWindow)
  const setSelectedWindow = useDashboardStore(state => state.setSelectedWindow)
  const setSelectedVaultId = useDashboardStore(state => state.setSelectedVaultId)
  const setHighlightedDateRange = useDashboardStore(state => state.setHighlightedDateRange)
  const brushRange = useDashboardStore(state => state.brushRange)
  const highlightedDateRange = useDashboardStore(state => state.highlightedDateRange)
  const poolVaults = POOL_VAULTS[selectedPool]
  const containerRef = useRef(null)
  const svgRef = useRef(null)
  const tooltipRef = useRef(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [windows, setWindows] = useState(null)
  const [alignDates, setAlignDates] = useState(false)

  useEffect(() => {
    loadWindows().then(setWindows)
  }, [])

  useEffect(() => {
    if (!windows) return
    const observeTarget = containerRef.current
    if (!observeTarget) return
    const resizeObserver = new ResizeObserver(entries => {
      if (!entries[0]) return
      const { width, height } = entries[0].contentRect
      setDimensions({ width, height })
    })

    resizeObserver.observe(observeTarget)

    return () => {
      resizeObserver.unobserve(observeTarget)
    }
  }, [windows])

  useEffect(() => {
    const { width, height } = dimensions
    if (width === 0 || height === 0 || !windows) return

    const activeRange = brushRange || highlightedDateRange
    const hasActiveRange = activeRange !== null

    const isWindowInRange = (windowDates, ei, xi, range) => {
      if (!range) return false
      const entryDate = new Date(windowDates[ei])
      const exitDate = new Date(windowDates[xi])
      const rangeStart = new Date(range.startDate)
      const rangeEnd = new Date(range.endDate)
      return entryDate <= rangeEnd && exitDate >= rangeStart
    }

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const displayVaults = poolVaults.filter(v => visibleVaults.includes(v)).slice(0, 4)

    let canonicalDates = []
    if (alignDates && displayVaults.length > 1) {
      const dateSets = displayVaults.map(v => new Set(windows[v]?.dates || []))
      const intersection = [...dateSets[0]].filter(d => dateSets.every(s => s.has(d)))
      canonicalDates = intersection.sort()
    } else {
      displayVaults.forEach(vaultId => {
        const vaultDates = windows[vaultId]?.dates || []
        if (vaultDates.length > canonicalDates.length) {
          canonicalDates = vaultDates
        }
      })
    }
    const n = canonicalDates.length

    const canonDateToIdx = {}
    canonicalDates.forEach((d, i) => { canonDateToIdx[d] = i })
    if (displayVaults.length === 0) {
      svg.selectAll('*').remove()
      svg.append('text')
        .attr('x', width / 2)
        .attr('y', height / 2)
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', 'var(--text-faint)')
        .attr('font-size', 'var(--text-sm)')
        .attr('font-family', 'var(--font-body)')
        .text('Select a vault to view data')
      return
    }

    const margin = { top: 30, right: 20, bottom: 40, left: 50 }
    
    const innerWidth = width - margin.left - margin.right
    const panelGap = displayVaults.length > 1 ? 20 : 0
    const panelWidth = displayVaults.length === 1
      ? innerWidth
      : (innerWidth - panelGap * (displayVaults.length - 1)) / displayVaults.length
    const innerHeight = height - margin.top - margin.bottom

    const colorScale = d3.scaleLinear()
      .domain([-0.15, 0, 0.05])
      .range(['oklch(50% 0.18 250)', 'oklch(97% 0.005 250)', 'oklch(62% 0.16 55)'])
      .clamp(true)

    const tooltip = d3.select(tooltipRef.current)

    displayVaults.forEach((vaultId, index) => {
      const data = windows[vaultId]
      if (!data) return
      const meta = getVaultMetadata(vaultId)

      const dates = data.dates
      const vaultToCanon = dates.map(d => canonDateToIdx[d] ?? -1)

      const g = svg.append('g')
        .attr('transform', `translate(${margin.left + index * (panelWidth + panelGap)},${margin.top})`)

      g.append('text')
        .attr('x', panelWidth / 2 - 20)
        .attr('y', -10)
        .attr('text-anchor', 'middle')
        .attr('font-family', 'var(--font-body)')
        .attr('font-size', 'var(--text-base)')
        .attr('font-weight', '500')
        .attr('fill', meta.color)
        .text(meta.label)

      const chartWidth = panelWidth - 40
      
      const xScale = d3.scaleLinear()
        .domain([0, n - 1])
        .range([0, chartWidth])
      
      const yScale = d3.scaleLinear()
        .domain([0, n - 1])
        .range([innerHeight, 0])

      const cellWidth = chartWidth / n
      const cellHeight = innerHeight / n

      g.selectAll('rect')
        .data(data.windows)
        .enter()
        .append('rect')
        .filter(d => vaultToCanon[d.ei] >= 0 && vaultToCanon[d.xi] >= 0)
        .attr('x', d => xScale(vaultToCanon[d.ei]))
        .attr('y', d => yScale(vaultToCanon[d.xi]))
        .attr('width', cellWidth + 0.5)
        .attr('height', cellHeight + 0.5)
        .attr('fill', d => colorScale(d.alpha))
        .attr('opacity', d => {
          if (!hasActiveRange) return 0.85
          return isWindowInRange(dates, d.ei, d.xi, activeRange) ? 1.0 : 0.25
        })
        .attr('stroke', d => {
          if (selectedWindow && selectedWindow.ei === d.ei && selectedWindow.xi === d.xi) {
            return 'var(--text-main)'
          }
          if (hasActiveRange && isWindowInRange(dates, d.ei, d.xi, activeRange)) {
            return 'var(--accent-main)'
          }
          return 'none'
        })
        .attr('stroke-width', d => {
          if (selectedWindow && selectedWindow.ei === d.ei && selectedWindow.xi === d.xi) {
            return 2
          }
          if (hasActiveRange && isWindowInRange(dates, d.ei, d.xi, activeRange)) {
            return 0.5
          }
          return 0
        })
        .on('mouseover', function(event, d) {
          d3.select(this).attr('stroke', 'var(--text-main)').attr('stroke-width', 1).attr('opacity', 1)
          tooltip.style('display', 'block')
            .html(`
              <div style="font-weight: 500; color: ${meta.color}; margin-bottom: 4px;">${meta.label}</div>
              <div style="color: var(--text-muted); font-size: 11px; margin-bottom: 8px;">
                ${dates[d.ei]} &rarr; ${dates[d.xi]} (${d.days} days)
              </div>
              <div style="display: flex; justify-content: space-between; gap: 16px;">
                <span>Alpha:</span>
                <span style="font-family: var(--font-mono);">${d.alpha >= 0 ? '+' : ''}${(d.alpha * 100).toFixed(2)}%</span>
              </div>
              <div style="display: flex; justify-content: space-between; gap: 16px;">
                <span>Vault Return:</span>
                <span style="font-family: var(--font-mono);">${d.vault_return >= 0 ? '+' : ''}${(d.vault_return * 100).toFixed(2)}%</span>
              </div>
              <div style="display: flex; justify-content: space-between; gap: 16px;">
                <span>HODL Return:</span>
                <span style="font-family: var(--font-mono);">${d.hodl_return >= 0 ? '+' : ''}${(d.hodl_return * 100).toFixed(2)}%</span>
              </div>
              <div style="display: flex; justify-content: space-between; gap: 16px;">
                <span>Fee:</span>
                <span style="font-family: var(--font-mono);">${fmtBps(d.fee_bps)}</span>
              </div>
              <div style="display: flex; justify-content: space-between; gap: 16px;">
                <span>Realized Vol:</span>
                <span style="font-family: var(--font-mono);">${fmtPct(d.realized_vol)}</span>
              </div>
              <div style="display: flex; justify-content: space-between; gap: 16px;">
                <span>Avg Daily Vol:</span>
                <span style="font-family: var(--font-mono);">${fmtDollar(d.avg_daily_vol_usdc)}</span>
              </div>
              <div style="display: flex; justify-content: space-between; gap: 16px;">
                <span>Price Change:</span>
                <span style="font-family: var(--font-mono); color: ${d.price_change >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'};">${fmtPct(d.price_change)}</span>
              </div>
            `)
          const ttEl = tooltipRef.current
          const ttW = ttEl.offsetWidth || 200
          const ttH = ttEl.offsetHeight || 120
          const ttM = 12
          let ttLeft = event.pageX + ttM
          let ttTop = event.pageY - ttM
          if (ttLeft + ttW > window.innerWidth) ttLeft = event.pageX - ttW - ttM
          if (ttTop + ttH > window.innerHeight) ttTop = event.pageY - ttH - ttM
          if (ttLeft < 0) ttLeft = ttM
          if (ttTop < 0) ttTop = ttM
          tooltip.style('left', `${ttLeft}px`).style('top', `${ttTop}px`)
        })
        .on('mousemove', function(event) {
          const ttEl = tooltipRef.current
          const ttW = ttEl.offsetWidth || 200
          const ttH = ttEl.offsetHeight || 120
          const ttM = 12
          let ttLeft = event.pageX + ttM
          let ttTop = event.pageY - ttM
          if (ttLeft + ttW > window.innerWidth) ttLeft = event.pageX - ttW - ttM
          if (ttTop + ttH > window.innerHeight) ttTop = event.pageY - ttH - ttM
          if (ttLeft < 0) ttLeft = ttM
          if (ttTop < 0) ttTop = ttM
          tooltip.style('left', `${ttLeft}px`).style('top', `${ttTop}px`)
        })
        .on('mouseout', function(event, d) {
          const isSelected = selectedWindow && selectedWindow.ei === d.ei && selectedWindow.xi === d.xi
          const isInRange = hasActiveRange && isWindowInRange(dates, d.ei, d.xi, activeRange)
          
          if (isSelected) {
            d3.select(this).attr('stroke', 'var(--text-main)').attr('stroke-width', 2)
          } else if (isInRange) {
            d3.select(this).attr('stroke', 'var(--accent-main)').attr('stroke-width', 0.5)
          } else {
            d3.select(this).attr('stroke', 'none').attr('stroke-width', 0)
          }
          
          const expectedOpacity = !hasActiveRange ? 0.85 : (isInRange ? 1.0 : 0.25)
          d3.select(this).attr('opacity', expectedOpacity)

          tooltip.style('display', 'none')
        })
          .on('click', function(event, d) {
            setSelectedWindow({
              ei: d.ei,
              xi: d.xi,
              ei_date: dates[d.ei],
              xi_date: dates[d.xi]
            })
            setSelectedVaultId(vaultId)
            setHighlightedDateRange({ startDate: new Date(dates[d.ei]), endDate: new Date(dates[d.xi]) })
          })

      const xTickData = canonicalDates.map((d, i) => ({d, i})).filter((_, i) => i % Math.ceil(n / 6) === 0)
      
      const xAxisG = g.append('g')
        .attr('class', styles.axis)
        .attr('transform', `translate(0,${innerHeight})`)

      xAxisG.selectAll('.tick')
        .data(xTickData)
        .enter()
        .append('text')
        .attr('x', d => xScale(d.i))
        .attr('y', 15)
        .attr('text-anchor', 'end')
        .attr('transform', d => `rotate(-45, ${xScale(d.i)}, 15)`)
        .attr('fill', 'var(--text-muted)')
        .attr('font-size', 'var(--text-xs)')
        .attr('font-family', 'var(--font-mono)')
        .text(d => {
          const dt = new Date(d.d)
          return dt.toLocaleDateString('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'})
        })
        
      if (index === 0) {
        xAxisG.append('text')
          .attr('x', chartWidth / 2)
          .attr('y', 35)
          .attr('text-anchor', 'middle')
          .attr('fill', 'var(--text-main)')
          .text('Entry Date')

        const yAxisG = g.append('g')
          .attr('class', styles.axis)
        
        yAxisG.selectAll('.tick')
          .data(xTickData)
          .enter()
          .append('text')
          .attr('x', -10)
          .attr('y', d => yScale(d.i))
          .attr('dy', '0.32em')
          .attr('text-anchor', 'end')
          .attr('fill', 'var(--text-muted)')
          .attr('font-size', 'var(--text-xs)')
          .attr('font-family', 'var(--font-mono)')
          .text(d => {
            const dt = new Date(d.d)
            return dt.toLocaleDateString('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'})
          })

        yAxisG.append('text')
          .attr('transform', 'rotate(-90)')
          .attr('x', -innerHeight / 2)
          .attr('y', -40)
          .attr('text-anchor', 'middle')
          .attr('fill', 'var(--text-main)')
          .text('Exit Date')
      }
    })

    const legendWidth = 120
    const legendHeight = 8
    const legendX = innerWidth - legendWidth
    const legendY = innerHeight + 12

    const legendG = svg.append('g')
      .attr('transform', `translate(${margin.left + legendX}, ${margin.top + legendY})`)

    const gradientId = `heatmap-gradient-${Math.random().toString(36).slice(2)}`
    const defs = svg.append('defs')
    const gradient = defs.append('linearGradient')
      .attr('id', gradientId)
      .attr('x1', '0%').attr('x2', '100%')

    const colorStops = [
      { offset: '0%', color: colorScale(colorScale.domain()[0]) },
      { offset: '50%', color: colorScale(0) },
      { offset: '100%', color: colorScale(colorScale.domain()[colorScale.domain().length - 1]) }
    ]
    colorStops.forEach(s => { gradient.append('stop').attr('offset', s.offset).attr('stop-color', s.color) })

    legendG.append('rect')
      .attr('width', legendWidth).attr('height', legendHeight)
      .attr('fill', `url(#${gradientId})`)
      .attr('rx', 2)

    legendG.append('text').attr('x', 0).attr('y', legendHeight + 10)
      .attr('fill', 'var(--text-muted)').attr('font-size', '9px').attr('font-family', 'var(--font-mono)')
      .text(`${(colorScale.domain()[0] * 100).toFixed(0)}%`)

    legendG.append('text').attr('x', legendWidth).attr('y', legendHeight + 10)
      .attr('text-anchor', 'end')
      .attr('fill', 'var(--text-muted)').attr('font-size', '9px').attr('font-family', 'var(--font-mono)')
      .text(`+${(colorScale.domain()[colorScale.domain().length - 1] * 100).toFixed(0)}%`)

    legendG.append('text').attr('x', legendWidth / 2).attr('y', -4)
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-muted)').attr('font-size', '9px').attr('font-family', 'var(--font-mono)')
      .text('Alpha')

  }, [dimensions, selectedPool, visibleVaults, selectedWindow, setSelectedWindow, poolVaults, windows, brushRange, highlightedDateRange, alignDates])

  if (!windows) return <div className={styles.loading}>Loading data…</div>

  const intersectionCount = (() => {
    const vaults = poolVaults.filter(v => visibleVaults.includes(v)).slice(0, 4)
    if (vaults.length < 2) return 0
    const dateSets = vaults.map(v => new Set(windows[v]?.dates || []))
    return [...dateSets[0]].filter(d => dateSets.every(s => s.has(d))).length
  })()

  const longestCount = (() => {
    const vaults = poolVaults.filter(v => visibleVaults.includes(v)).slice(0, 4)
    return Math.max(...vaults.map(v => windows[v]?.dates?.length || 0), 0)
  })()

  return (
    <div className={styles.wrapper}>
      <div className={styles.toggleRow}>
        <button
          type="button"
          className={`${styles.alignToggle} ${alignDates ? styles.alignActive : ''}`}
          onClick={() => setAlignDates(!alignDates)}
        >
          {alignDates ? 'Aligned' : 'Align'} Date Range
        </button>
        <span className={styles.toggleHint}>
          {alignDates
            ? `Intersection: ${intersectionCount} days`
            : `Full range: ${longestCount} days`}
        </span>
      </div>
      <div className={styles.container} ref={containerRef}>
        <svg ref={svgRef} width="100%" height="100%" />
        <div ref={tooltipRef} className={styles.tooltip} style={{ display: 'none' }} />
      </div>
    </div>
  )
}
