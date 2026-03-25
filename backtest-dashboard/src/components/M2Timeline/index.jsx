import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import styles from './styles.module.css'
import { getVaultMetadata, loadIntervals, loadWindows, getWindowData } from '../../utils/dataHelpers'
import useDashboardStore from '../../store/dashboard'
import metadata from '../../../data/metadata.json'

export default function M2Timeline() {
  const visibleVaults = useDashboardStore(state => state.visibleVaults)
  const selectedWindow = useDashboardStore(state => state.selectedWindow)
  const highlightedDateRange = useDashboardStore(state => state.highlightedDateRange)
  const brushRange = useDashboardStore(state => state.brushRange)
  const containerRef = useRef(null)
  const svgRef = useRef(null)
  const tooltipRef = useRef(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [intervals, setIntervals] = useState(null)
  const [windows, setWindows] = useState(null)

  useEffect(() => {
    loadIntervals().then(setIntervals)
    loadWindows().then(setWindows)
  }, [])

  useEffect(() => {
    if (!intervals || !windows) return
    const observeTarget = containerRef.current
    if (!observeTarget) return
    const resizeObserver = new ResizeObserver(entries => {
      if (!entries[0]) return
      const { width, height } = entries[0].contentRect
      setDimensions({ width, height })
    })
    resizeObserver.observe(observeTarget)
    return () => resizeObserver.unobserve(observeTarget)
  }, [intervals, windows])

  useEffect(() => {
    const { width, height } = dimensions
    if (width === 0 || height === 0 || !intervals || !windows) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const margin = { top: 10, right: 20, bottom: 25, left: 55 }
    const innerWidth = width - margin.left - margin.right
    const mainHeight = height - margin.top - margin.bottom

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    let plotData = visibleVaults.map(vaultId => {
      const data = intervals[vaultId]
      const meta = getVaultMetadata(vaultId)
      const pts = []
      if (data) {
        for (let i = 0; i < data.timestamps.length; i++) {
          pts.push({
            date: new Date(data.timestamps[i] * 1000),
            ts: data.timestamps[i],
            vr: data.vault_return[i],
            hr: data.hodl_return[i],
            vol: data.pool_volume_usdc[i]
          })
        }
      }
      return { vaultId, meta, pts }
    }).filter(d => d.pts.length > 0)

    if (plotData.length === 0) {
      svg.append('text')
        .attr('x', width / 2).attr('y', height / 2)
        .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
        .attr('fill', 'var(--text-faint)').attr('font-size', 'var(--text-sm)')
        .text('Select a vault to view data')
      return
    }

    const activeRange = brushRange
      ? {
          start: new Date(brushRange.startDate).toISOString().slice(0, 10),
          end: new Date(brushRange.endDate).toISOString().slice(0, 10)
        }
      : selectedWindow
        ? { start: selectedWindow.ei_date, end: selectedWindow.xi_date }
        : null

    if (activeRange) {
      plotData = plotData.map(d => {
        const vaultDates = windows[d.vaultId]?.dates || []
        const startTs = new Date(activeRange.start).getTime()
        const endTs = new Date(activeRange.end).getTime()

        let ei = vaultDates.findIndex(x => new Date(x).getTime() >= startTs)
        if (ei === -1) ei = 0

        let xiEnd = -1
        for (let i = vaultDates.length - 1; i >= 0; i--) {
          if (new Date(vaultDates[i]).getTime() <= endTs) {
            xiEnd = i
            break
          }
        }
        if (xiEnd <= ei) {
          return { ...d, pts: [] }
        }

        const pts = [{ date: new Date(vaultDates[ei]), ts: 0, vr: 0, hr: 0, vol: 0 }]
        for (let xi = ei + 1; xi <= xiEnd; xi++) {
          const w = getWindowData(d.vaultId, ei, xi)
          if (!w) continue
          pts.push({
            date: new Date(vaultDates[xi]),
            ts: 0,
            vr: w.vault_return,
            hr: w.hodl_return,
            vol: 0
          })
        }
        return { ...d, pts }
      }).filter(d => d.pts.length > 0)

      if (plotData.length === 0) return
    }

    const allDates = plotData.flatMap(d => d.pts.map(p => p.date))
    const xDomain = d3.extent(allDates)

    let yMin = 0, yMax = 0
    plotData.forEach(d => {
      d.pts.forEach(p => {
        if (p.vr < yMin) yMin = p.vr
        if (p.vr > yMax) yMax = p.vr
        if (p.hr < yMin) yMin = p.hr
        if (p.hr > yMax) yMax = p.hr
      })
    })
    yMin = Math.min(yMin * 1.1, -0.001)
    yMax = Math.max(yMax * 1.1, 0.001)

    const xScale = d3.scaleTime().domain(xDomain).range([0, innerWidth])
    const yScale = d3.scaleLinear().domain([yMin, yMax]).range([mainHeight, 0])

    g.append('g').attr('class', 'gridlines')
      .call(d3.axisLeft(yScale).tickSize(-innerWidth).tickFormat(''))
      .call(el => el.select('.domain').remove())
      .call(el => el.selectAll('.tick line')
        .attr('stroke', 'var(--border-color)').attr('stroke-width', 0.5)
        .attr('stroke-dasharray', '2,4').attr('opacity', 0.6))

    g.append('g').attr('class', styles.axis)
      .call(d3.axisLeft(yScale).ticks(5).tickFormat(d => `${d >= 0 ? '+' : ''}${(d * 100).toFixed(1)}%`))
      .call(el => el.select('.domain').remove())
      .call(el => el.selectAll('.tick line').attr('stroke', 'var(--border-color)'))
      .call(el => el.selectAll('.tick text').attr('fill', 'var(--text-muted)'))

    g.append('g').attr('class', styles.axis)
      .attr('transform', `translate(0,${mainHeight})`)
      .call(d3.axisBottom(xScale).ticks(8).tickFormat(d3.timeFormat('%b %d')))
      .call(el => el.select('.domain').remove())
      .call(el => el.selectAll('.tick line').attr('stroke', 'var(--border-color)'))
      .call(el => el.selectAll('.tick text').attr('fill', 'var(--text-muted)'))

    g.append('line')
      .attr('x1', 0).attr('x2', innerWidth)
      .attr('y1', yScale(0)).attr('y2', yScale(0))
      .attr('stroke', 'var(--border-color)').attr('stroke-width', 1).attr('stroke-dasharray', '4,4')

    const lineVR = d3.line().defined(d => d.vr != null && !isNaN(d.vr))
      .x(d => xScale(d.date)).y(d => yScale(d.vr))
    const lineHR = d3.line().defined(d => d.hr != null && !isNaN(d.hr))
      .x(d => xScale(d.date)).y(d => yScale(d.hr))

    plotData.forEach(d => {
      g.append('path').datum(d.pts)
        .attr('fill', 'none').attr('stroke', d.meta.color)
        .attr('stroke-width', 1.5).attr('d', lineVR)
      g.append('path').datum(d.pts)
        .attr('fill', 'none').attr('stroke', d.meta.color)
        .attr('stroke-width', 1).attr('stroke-dasharray', '4,3')
        .attr('opacity', 0.45).attr('d', lineHR)
    })

    const omnisVaultMeta = metadata.vaults.find(v => v.id === visibleVaults.find(id => id.startsWith('omnis')))
    const omnisInceptionDate = omnisVaultMeta?.inception_date ? new Date(omnisVaultMeta.inception_date) : null

    if (!activeRange && omnisInceptionDate && omnisInceptionDate > xScale.domain()[0]) {
      const inceptionX = xScale(omnisInceptionDate)
      g.append('rect').attr('x', 0).attr('y', 0)
        .attr('width', inceptionX).attr('height', mainHeight)
        .attr('fill', 'var(--border-color)').attr('opacity', 0.25).attr('pointer-events', 'none')
      if (inceptionX > 60) {
        g.append('text').attr('x', inceptionX - 4).attr('y', 14)
          .attr('text-anchor', 'end').attr('fill', 'var(--text-muted)')
          .attr('font-size', '10px').attr('font-family', 'var(--font-mono)')
          .attr('pointer-events', 'none').text('Omnis not deployed')
      }
    }

    const crosshair = g.append('g').style('display', 'none')
    crosshair.append('line').attr('class', 'v-line')
      .attr('y1', 0).attr('y2', mainHeight)
      .attr('stroke', 'var(--text-muted)').attr('stroke-dasharray', '2,2')

    const tooltip = d3.select(tooltipRef.current)
    const hoverRect = g.append('rect')
      .attr('width', innerWidth).attr('height', mainHeight)
      .attr('fill', 'none').attr('pointer-events', 'all')

    hoverRect.on('mouseover', () => {
      crosshair.style('display', null)
      tooltip.style('display', 'block')
    })
    .on('mousemove', (event) => {
      const [mx] = d3.pointer(event)
      const date = xScale.invert(mx)
      crosshair.select('.v-line').attr('x1', mx).attr('x2', mx)

      const ttHtml = [`<div style="color:var(--text-muted);font-size:11px;margin-bottom:4px">${date.toLocaleDateString('en-US', {month:'short',day:'numeric',timeZone:'UTC'})}</div>`]
      plotData.forEach(d => {
        const idx = d3.bisector(p => p.date).left(d.pts, date)
        const pt = d.pts[Math.min(idx, d.pts.length - 1)]
        if (pt) {
          ttHtml.push(`<div style="display:flex;justify-content:space-between;gap:16px;margin-bottom:2px">
            <span style="color:${d.meta.color}">${d.meta.label.split(' ')[0]}</span>
            <div style="text-align:right;font-family:var(--font-mono);font-size:11px">
              <div>Vault: ${pt.vr >= 0 ? '+' : ''}${(pt.vr * 100).toFixed(2)}%</div>
              <div style="color:var(--text-faint)">HODL: ${pt.hr >= 0 ? '+' : ''}${(pt.hr * 100).toFixed(2)}%</div>
            </div></div>`)
        }
      })
      tooltip.html(ttHtml.join(''))
      const ttEl = tooltipRef.current
      const ttW = ttEl.offsetWidth || 200
      const ttH = ttEl.offsetHeight || 100
      let ttLeft = event.clientX + 12
      let ttTop = event.clientY - ttH - 12
      if (ttLeft + ttW > window.innerWidth) ttLeft = event.clientX - ttW - 12
      if (ttTop < 10) ttTop = event.clientY + 12
      if (ttLeft < 0) ttLeft = 12
      tooltip.style('left', `${ttLeft}px`).style('top', `${ttTop}px`)
    })
    .on('mouseout', () => {
      crosshair.style('display', 'none')
      tooltip.style('display', 'none')
    })

    if (!activeRange && selectedWindow) {
      const xStart = xScale(new Date(selectedWindow.ei_date))
      const xEnd = xScale(new Date(selectedWindow.xi_date))
      g.append('rect').attr('x', xStart).attr('width', xEnd - xStart)
        .attr('y', 0).attr('height', mainHeight)
        .attr('fill', 'var(--accent-main)').attr('opacity', 0.1).attr('pointer-events', 'none')
    }

    if (!activeRange && highlightedDateRange) {
      const hx0 = xScale(new Date(highlightedDateRange.startDate))
      const hx1 = xScale(new Date(highlightedDateRange.endDate))
      if (hx0 < innerWidth && hx1 > 0) {
        g.append('rect').attr('x', Math.max(0, hx0)).attr('y', 0)
          .attr('width', Math.min(innerWidth, hx1) - Math.max(0, hx0)).attr('height', mainHeight)
          .attr('fill', 'var(--accent-green)').attr('opacity', 0.12).attr('pointer-events', 'none')
      }
    }

  }, [dimensions, visibleVaults, selectedWindow, highlightedDateRange, brushRange, intervals, windows])

  if (!intervals || !windows) return <div className={styles.loading}>Loading data…</div>

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        {visibleVaults.length > 0 && (
          <div className={styles.legend}>
            {visibleVaults.map(vaultId => {
              const meta = getVaultMetadata(vaultId)
              return (
                <div key={vaultId} className={styles.legendItem}>
                  <div className={styles.legendColor} style={{ backgroundColor: meta.color }} />
                  <span>{meta.label}</span>
                  <div className={styles.legendLine} style={{ borderColor: meta.color }} />
                  <span style={{ color: 'var(--text-faint)' }}>HODL</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
      <div className={styles.chartArea} ref={containerRef}>
        <svg ref={svgRef} width="100%" height="100%" />
        <div ref={tooltipRef} className={styles.tooltip} style={{ display: 'none' }} />
      </div>
    </div>
  )
}
