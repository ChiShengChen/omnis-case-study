import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import styles from './styles.module.css'
import { loadWindows, getWindowData, getVaultMetadata } from '../../utils/dataHelpers'
import useDashboardStore from '../../store/dashboard'
import { fmtPct } from '../../utils/formatters'

export default function DecompositionChart() {
  const visibleVaults = useDashboardStore(state => state.visibleVaults)
  const selectedVaultId = useDashboardStore(state => state.selectedVaultId)
  const brushRange = useDashboardStore(state => state.brushRange)
  const selectedWindow = useDashboardStore(state => state.selectedWindow)
  const containerRef = useRef(null)
  const svgRef = useRef(null)
  const tooltipRef = useRef(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [windows, setWindows] = useState(null)

  useEffect(() => { loadWindows().then(setWindows) }, [])
  useEffect(() => {
    if (!windows) return
    const el = containerRef.current; if (!el) return
    const ro = new ResizeObserver(e => { if (e[0]) setDimensions(e[0].contentRect) })
    ro.observe(el); return () => ro.unobserve(el)
  }, [windows])

  useEffect(() => {
    const { width, height } = dimensions
    if (!width || !height || !windows || !visibleVaults.length) return
    const svg = d3.select(svgRef.current); svg.selectAll('*').remove()

    let windowStart, windowEnd
    if (brushRange) {
      windowStart = new Date(brushRange.startDate).toISOString().split('T')[0]
      windowEnd = new Date(brushRange.endDate).toISOString().split('T')[0]
    } else if (selectedWindow) {
      windowStart = selectedWindow.ei_date; windowEnd = selectedWindow.xi_date
    } else {
      windowStart = '2025-12-17'; windowEnd = '2026-03-23'
    }
    const startTs = new Date(windowStart).getTime(), endTs = new Date(windowEnd).getTime()

    // Build data for ALL visible vaults
    const allVaultData = {}
    for (const vid of visibleVaults) {
      const vDates = windows[vid]?.dates || []; if (!vDates.length) continue
      let ei = vDates.findIndex(d => new Date(d).getTime() >= startTs); if (ei === -1) ei = 0
      let xiEnd = -1
      for (let i = vDates.length-1; i >= 0; i--) { if (new Date(vDates[i]).getTime() <= endTs) { xiEnd = i; break } }
      if (xiEnd <= ei) continue
      const pts = []
      for (let xi = ei+1; xi <= xiEnd; xi++) {
        const w = getWindowData(vid, ei, xi); if (!w) continue
        pts.push({ date: new Date(vDates[xi]), fee: (w.fee_bps??0)/10000, alpha: w.alpha, drag: w.alpha-(w.fee_bps??0)/10000 })
      }
      if (pts.length) allVaultData[vid] = pts
    }
    if (!Object.keys(allVaultData).length) return

    const margin = { top: 30, right: 100, bottom: 25, left: 55 }
    const innerWidth = width-margin.left-margin.right, innerHeight = height-margin.top-margin.bottom
    const g = svg.append('g').attr('transform',`translate(${margin.left},${margin.top})`)

    const allPts = Object.values(allVaultData).flat()
    const xScale = d3.scaleTime().domain(d3.extent(allPts, d => d.date)).range([0, innerWidth])
    const yMinA = d3.min(allPts, d => Math.min(d.alpha,0))*1.3
    const yMaxA = d3.max(allPts, d => Math.max(d.alpha,0))*1.3
    const alphaDomain = yMinA===yMaxA ? [-0.01,0.01] : [yMinA,yMaxA]
    const yScaleAlpha = d3.scaleLinear().domain(alphaDomain).range([innerHeight,0])

    // Grid
    g.append('g').call(d3.axisLeft(yScaleAlpha).tickSize(-innerWidth).tickFormat('')).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)').attr('stroke-width',0.5).attr('stroke-dasharray','2,4'))
    // X axis
    g.append('g').attr('transform',`translate(0,${innerHeight})`).call(d3.axisBottom(xScale).ticks(8).tickFormat(d3.timeFormat('%b %d'))).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)')).call(g=>g.selectAll('text').attr('fill','var(--text-muted)'))
    // Y axis
    g.append('g').call(d3.axisLeft(yScaleAlpha).ticks(5).tickFormat(d=>fmtPct(d))).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)')).call(g=>g.selectAll('text').attr('fill','var(--text-muted)'))
    // Zero line
    g.append('line').attr('x1',0).attr('x2',innerWidth).attr('y1',yScaleAlpha(0)).attr('y2',yScaleAlpha(0)).attr('stroke','var(--border-color)').attr('stroke-width',1).attr('stroke-dasharray','4,4')

    const lineAlpha = d3.line().x(d=>xScale(d.date)).y(d=>yScaleAlpha(d.alpha))
    const vaultIds = Object.keys(allVaultData)

    // Area fills (subtle)
    for (const vid of vaultIds) {
      const vPts = allVaultData[vid]; if (!vPts) continue
      const meta = getVaultMetadata(vid); const color = meta?.color || '#888'
      g.append('path').datum(vPts).attr('fill',color).attr('opacity',0.06)
        .attr('d', d3.area().x(d=>xScale(d.date)).y0(yScaleAlpha(0)).y1(d=>yScaleAlpha(d.fee)))
    }
    // Alpha lines + labels
    let labelYs = []
    for (const vid of vaultIds) {
      const vPts = allVaultData[vid]; if (!vPts) continue
      const meta = getVaultMetadata(vid); const color = meta?.color || '#888'
      g.append('path').datum(vPts).attr('fill','none').attr('stroke',color).attr('stroke-width',2).attr('d',lineAlpha)
      const last = vPts[vPts.length-1]
      if (last) {
        const name = vid.replace('-wbtc-usdc','').replace('-usdc-eth','').toUpperCase()
        let ly = yScaleAlpha(last.alpha)
        for (const py of labelYs) { if (Math.abs(ly-py)<14) ly = py+(ly>py?14:-14) }
        labelYs.push(ly)
        g.append('text').attr('x',innerWidth+4).attr('y',ly).attr('fill',color).attr('font-size','10px').attr('font-weight','bold').attr('font-family','var(--font-mono)').attr('dominant-baseline','middle').text(`${name} ${(last.alpha*100).toFixed(1)}%`)
      }
    }
  }, [dimensions, visibleVaults, selectedVaultId, brushRange, selectedWindow, windows])

  if (!windows) return <div className={styles.loading}>Loading data…</div>
  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <div className={styles.vaultIndicator}><span>All Vaults — Net Alpha Over Time</span></div>
        <div className={styles.legend}>
          <div className={styles.legendItem}><span className={styles.legendSwatch} style={{background:'var(--text-main)',opacity:0.8}}/><span>Net Alpha — vault return minus HODL return</span></div>
        </div>
      </div>
      <div ref={containerRef} className={styles.chartArea}><svg ref={svgRef} width={dimensions.width} height={dimensions.height}/></div>
      <div ref={tooltipRef} className={styles.tooltip} style={{display:'none'}}/>
    </div>
  )
}
