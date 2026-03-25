import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import styles from './styles.module.css'
import { loadIntervals, sliceIntervals } from '../../utils/dataHelpers'
import useDashboardStore from '../../store/dashboard'
import { fmtDollar } from '../../utils/formatters'

export default function VolumeChart() {
  const visibleVaults = useDashboardStore(state => state.visibleVaults)
  const selectedVaultId = useDashboardStore(state => state.selectedVaultId)
  const brushRange = useDashboardStore(state => state.brushRange)
  const selectedWindow = useDashboardStore(state => state.selectedWindow)
  const containerRef = useRef(null)
  const svgRef = useRef(null)
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

    const vaultId = selectedVaultId && visibleVaults.includes(selectedVaultId)
      ? selectedVaultId
      : (visibleVaults.find(v => v.startsWith('omnis')) || visibleVaults[0])

    let windowStart, windowEnd
    if (brushRange) {
      windowStart = new Date(brushRange.startDate).toISOString().split('T')[0]
      windowEnd = new Date(brushRange.endDate).toISOString().split('T')[0]
    } else if (selectedWindow) {
      windowStart = selectedWindow.ei_date
      windowEnd = selectedWindow.xi_date
    } else {
      windowStart = '2025-12-17'
      windowEnd = '2026-03-23'
    }

    const sliced = sliceIntervals(vaultId, windowStart, windowEnd)
    if (!sliced || sliced.timestamps.length === 0) return

    const margin = { top: 10, right: 20, bottom: 25, left: 55 }
    const innerWidth = width - margin.left - margin.right
    const innerHeight = height - margin.top - margin.bottom

    const pts = sliced.timestamps.map((ts, i) => ({
      date: new Date(ts * 1000),
      vol: sliced.pool_volume_usdc[i]
    }))

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    const xDomain = d3.extent(pts, d => d.date)
    const xScale = d3.scaleTime().domain(xDomain).range([0, innerWidth])

    const maxVol = d3.max(pts, d => d.vol) || 1
    const yVolScale = d3.scaleLinear().domain([0, maxVol]).range([innerHeight, 0])

    const xAxis = d3.axisBottom(xScale).ticks(8).tickFormat(d3.timeFormat('%b %d'))
    const volAxisLeft = d3.axisLeft(yVolScale).ticks(3).tickFormat(d => d >= 1000000 ? `${(d/1000000).toFixed(0)}M` : `${(d/1000).toFixed(0)}k`)

    // Draw grid
    g.append('g')
      .attr('class', 'gridlines')
      .call(d3.axisLeft(yVolScale).tickSize(-innerWidth).tickFormat(''))
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick line').attr('stroke', 'var(--border-color)').attr('stroke-width', 0.5).attr('stroke-dasharray', '2,4'))

    g.append('g')
      .attr('class', styles.axis)
      .call(volAxisLeft)
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick line').attr('stroke', 'var(--border-color)'))
      .call(g => g.selectAll('.tick text').attr('fill', 'var(--text-muted)'))

    g.append('g')
      .attr('class', styles.axis)
      .attr('transform', `translate(0,${innerHeight})`)
      .call(xAxis)
      .call(g => g.select('.domain').remove())
      .call(g => g.selectAll('.tick line').attr('stroke', 'var(--border-color)'))
      .call(g => g.selectAll('.tick text').attr('fill', 'var(--text-muted)'))

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
      .attr('fill', 'var(--text-faint)')

    g.append('text')
      .attr('x', -20)
      .attr('y', -5)
      .attr('text-anchor', 'end')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', '9px')
      .attr('font-family', 'var(--font-mono)')
      .text('Volume')

  }, [dimensions, visibleVaults, selectedVaultId, brushRange, selectedWindow, intervals])

  if (!intervals) return <div className={styles.loading}>Loading data…</div>

  return (
    <div className={styles.container}>
      <div className={styles.chartArea} ref={containerRef}>
        <svg ref={svgRef} width="100%" height="100%" />
      </div>
    </div>
  )
}
