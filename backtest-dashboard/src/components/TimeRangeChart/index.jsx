import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import styles from './styles.module.css'
import { loadIntervals } from '../../utils/dataHelpers'
import useDashboardStore from '../../store/dashboard'
import metadata from '../../../data/metadata.json'

export default function TimeRangeChart() {
  const visibleVaults = useDashboardStore(state => state.visibleVaults)
  const brushRange = useDashboardStore(state => state.brushRange)
  const setBrushRange = useDashboardStore(state => state.setBrushRange)
  const containerRef = useRef(null)
  const svgRef = useRef(null)
  const brushRef = useRef(null)
  const brushGRef = useRef(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [intervals, setIntervals] = useState(null)

  useEffect(() => {
    loadIntervals().then(setIntervals)
  }, [])

  useEffect(() => {
    if (!intervals) return
    const observeTarget = containerRef.current
    if (!observeTarget) return
    const resizeObserver = new ResizeObserver(entries => {
      if (!entries[0]) return
      const { width, height } = entries[0].contentRect
      setDimensions({ width, height })
    })
    resizeObserver.observe(observeTarget)
    return () => resizeObserver.unobserve(observeTarget)
  }, [intervals])

  useEffect(() => {
    const { width, height } = dimensions
    if (width === 0 || height === 0 || !intervals || visibleVaults.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const margin = { top: 5, right: 50, bottom: 20, left: 50 }
    const innerWidth = width - margin.left - margin.right
    const innerHeight = height - margin.top - margin.bottom

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    let longestVaultId = visibleVaults[0]
    let maxLen = 0
    visibleVaults.forEach(vid => {
      if (intervals[vid]?.timestamps?.length > maxLen) {
        maxLen = intervals[vid].timestamps.length
        longestVaultId = vid
      }
    })

    const data = intervals[longestVaultId]
    if (!data || data.timestamps.length === 0) return

    const pts = []
    for (let i = 0; i < data.timestamps.length; i++) {
      pts.push({
        date: new Date(data.timestamps[i] * 1000),
        vol: data.pool_volume_usdc[i],
        price: data.asset_price[i]
      })
    }

    const xDomain = d3.extent(pts, d => d.date)
    const xScale = d3.scaleTime().domain(xDomain).range([0, innerWidth])

    const maxVol = d3.max(pts, d => d.vol) || 1
    const yVolScale = d3.scaleLinear().domain([0, maxVol]).range([innerHeight, 0])

    // Draw volume bars
    const barWidth = Math.max(1, innerWidth / pts.length)
    g.selectAll('rect.vol')
      .data(pts)
      .enter()
      .append('rect')
      .attr('class', 'vol')
      .attr('x', d => xScale(d.date) - barWidth / 2)
      .attr('y', d => yVolScale(d.vol))
      .attr('width', barWidth)
      .attr('height', d => innerHeight - yVolScale(d.vol))
      .attr('fill', 'var(--border-color)')

    // Draw price line
    const pricePts = pts.filter(d => d.price != null)
    if (pricePts.length > 0) {
      const priceExtent = d3.extent(pricePts, d => d.price)
      const yPriceScale = d3.scaleLinear()
        .domain([priceExtent[0] * 0.99, priceExtent[1] * 1.01])
        .range([innerHeight, 0])

      const priceLine = d3.line()
        .x(d => xScale(d.date))
        .y(d => yPriceScale(d.price))

      g.append('path')
        .datum(pricePts)
        .attr('fill', 'none')
        .attr('stroke', 'var(--text-muted)')
        .attr('stroke-width', 1.5)
        .attr('opacity', 0.8)
        .attr('d', priceLine)

      // Right Y-axis for Price
      const priceAxisRight = d3.axisRight(yPriceScale)
        .ticks(3)
        .tickFormat(d => d >= 1000 ? `$${(d/1000).toFixed(0)}k` : `$${d.toFixed(0)}`)

      g.append('g')
        .attr('class', styles.axis)
        .attr('transform', `translate(${innerWidth}, 0)`)
        .call(priceAxisRight)
        .call(g => g.select('.domain').remove())
        .call(g => g.selectAll('text')
          .attr('fill', 'var(--text-muted)'))

      // Y-axis label Price
      g.append('text')
        .attr('x', innerWidth + 35)
        .attr('y', -5)
        .attr('text-anchor', 'end')
        .attr('fill', 'var(--text-muted)')
        .attr('font-size', '9px')
        .attr('font-family', 'var(--font-mono)')
        .text('Price ($)')
    }

    // Left Y-axis for Volume
    const volAxisLeft = d3.axisLeft(yVolScale)
      .ticks(3)
      .tickFormat(d => d >= 1000000 ? `${(d/1000000).toFixed(0)}M` : `${(d/1000).toFixed(0)}k`)

    g.append('g')
      .attr('class', styles.axis)
      .call(volAxisLeft)
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('text')
        .attr('fill', 'var(--text-faint)'))
        
    g.append('text')
      .attr('x', -25)
      .attr('y', -5)
      .attr('text-anchor', 'start')
      .attr('fill', 'var(--text-faint)')
      .attr('font-size', '9px')
      .attr('font-family', 'var(--font-mono)')
      .text('Vol ($)')

    // X-axis
    const xAxis = d3.axisBottom(xScale).ticks(8).tickFormat(d3.timeFormat('%b %d'))
    g.append('g')
      .attr('class', styles.axis)
      .attr('transform', `translate(0,${innerHeight})`)
      .call(xAxis)
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick line')
        .attr('stroke', 'var(--border-color)')
        .attr('stroke-width', 1))
      .call(g => g.selectAll('.tick text')
        .attr('fill', 'var(--text-muted)'))

    // Omnis not deployed overlay
    const omnisVaultMeta = metadata.vaults.find(v => v.id === visibleVaults.find(id => id.startsWith('omnis')))
    const omnisInceptionDate = omnisVaultMeta?.inception_date ? new Date(omnisVaultMeta.inception_date) : null
    if (omnisInceptionDate && omnisInceptionDate > xDomain[0]) {
      const inceptionX = xScale(omnisInceptionDate)
      g.append('rect')
        .attr('x', 0)
        .attr('y', 0)
        .attr('width', inceptionX)
        .attr('height', innerHeight)
        .attr('fill', 'var(--border-color)')
        .attr('opacity', 0.25)
        .attr('pointer-events', 'none')
    }

    // Brush
    const brush = d3.brushX()
      .extent([[0, 0], [innerWidth, innerHeight]])
      .on('end', (event) => {
        if (!event.sourceEvent) return
        if (!event.selection) {
          setBrushRange(null)
          return
        }
        const [x0, x1] = event.selection
        const startDate = xScale.invert(x0)
        const endDate = xScale.invert(x1)
        if (
          brushRange &&
          Math.abs(new Date(brushRange.startDate).getTime() - startDate.getTime()) < 1000 &&
          Math.abs(new Date(brushRange.endDate).getTime() - endDate.getTime()) < 1000
        ) return
        setBrushRange({ startDate, endDate })
      })

    brushRef.current = brush

    const brushG = g.append('g')
      .attr('class', `${styles.brush} brush`)
      .call(brush)

    brushG.select('.selection').classed(styles.brushSelection, true)
    brushG.selectAll('.handle').classed(styles.brushHandle, true)
    brushGRef.current = brushG

    brushG.on('dblclick', () => {
      brush.move(brushG, null)
      setBrushRange(null)
    })

    if (brushRange) {
      const x0 = xScale(new Date(brushRange.startDate))
      const x1 = xScale(new Date(brushRange.endDate))
      brush.move(brushG, [Math.max(0, x0), Math.min(innerWidth, x1)])
    }

  }, [dimensions, visibleVaults, brushRange, intervals, setBrushRange])

  if (!intervals) return <div className={styles.loading}>Loading data…</div>

  const daysSelected = brushRange 
    ? Math.round((brushRange.endDate - brushRange.startDate) / 86400000)
    : 0

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        {!brushRange ? (
          <span className={styles.hint}>Drag to select time range</span>
        ) : (
          <div className={styles.selectionInfo}>
            <span>
              {brushRange.startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })} 
              {' — '} 
              {brushRange.endDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })}
              <span className={styles.daysBadge}>({daysSelected} days)</span>
            </span>
            <button
              type="button"
              className={styles.resetButton}
              onClick={() => setBrushRange(null)}
            >
              Reset
            </button>
          </div>
        )}
      </div>
      <div className={styles.chartArea} ref={containerRef}>
        <svg ref={svgRef} width="100%" height="100%" />
      </div>
    </div>
  )
}
