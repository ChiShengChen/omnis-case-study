import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import rebalanceData from '../../../data/rebalance-data.json'
import useDashboardStore from '../../store/dashboard'
const POOL_MAP = { 'WBTC-USDC': 'WBTC-USDC', 'USDC-ETH': 'USDC-ETH' }
export default function RebalanceTimingChart() {
  const selectedPool = useDashboardStore(state => state.selectedPool)
  const containerRef = useRef(null)
  const svgRef = useRef(null)
  const [dims, setDims] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const el = containerRef.current; if (!el) return
    const ro = new ResizeObserver(e => { const { width, height } = e[0].contentRect; setDims({ width, height }) })
    ro.observe(el); return () => ro.unobserve(el)
  }, [])
  useEffect(() => {
    const { width, height } = dims; if (!width || !height) return
    const svg = d3.select(svgRef.current); svg.selectAll('*').remove()
    const poolData = rebalanceData.pools[POOL_MAP[selectedPool]]; if (!poolData) return
    const margin = { top: 20, right: 20, bottom: 25, left: 65 }
    const w = width - margin.left - margin.right, h = height - margin.top - margin.bottom
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
    const prices = poolData.prices
    const xScale = d3.scaleTime().domain(d3.extent(prices, d => new Date(d.ts * 1000))).range([0, w])
    const yScale = d3.scaleLinear().domain(d3.extent(prices, d => d.price)).nice().range([h, 0])
    g.append('g').call(d3.axisLeft(yScale).tickSize(-w).tickFormat('')).call(g => g.select('.domain').remove()).call(g => g.selectAll('.tick line').attr('stroke','var(--border-color)').attr('stroke-width',0.5).attr('stroke-dasharray','2,4'))
    g.append('path').datum(prices).attr('fill','none').attr('stroke','#64748b').attr('stroke-width',1.2).attr('d', d3.line().x(d => xScale(new Date(d.ts*1000))).y(d => yScale(d.price)))
    const vcs = [
      { key:'omnis', color:'#F7931A', size:2, opacity:0.6, label:'Omnis' },
      { key:'charm', color:'#00A3FF', size:15, opacity:0.6, label:'Charm' },
      { key:'ml', color:'#22C55E', size:30, opacity:0.9, label:'Multi-Layer' },
    ]
    const legend = [], bisect = d3.bisector(d => d.ts).left
    for (const vc of vcs) {
      const rbs = poolData.rebalances[vc.key]; if (!rbs || !rbs.length) continue
      rbs.forEach(rb => { const idx = Math.min(bisect(prices, rb.ts), prices.length-1); rb.price = prices[idx].price })
      g.selectAll(`.dot-${vc.key}`).data(rbs).enter().append('circle')
        .attr('cx', d => xScale(new Date(d.ts*1000))).attr('cy', d => yScale(d.price))
        .attr('r', Math.sqrt(vc.size)).attr('fill', vc.color).attr('opacity', vc.opacity)
      legend.push({ ...vc, count: rbs.length })
    }
    g.append('g').attr('transform',`translate(0,${h})`).call(d3.axisBottom(xScale).ticks(8).tickFormat(d3.timeFormat('%b %d'))).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('text').attr('fill','var(--text-muted)')).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)'))
    g.append('g').call(d3.axisLeft(yScale).ticks(6).tickFormat(d=>`$${d3.format(',.0f')(d)}`)).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('text').attr('fill','var(--text-muted)')).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)'))
    const lg = g.append('g').attr('transform',`translate(${w-200},10)`)
    legend.forEach((l,i) => { const row=lg.append('g').attr('transform',`translate(0,${i*18})`); row.append('circle').attr('r',4).attr('fill',l.color).attr('opacity',l.opacity); row.append('text').attr('x',10).attr('y',4).attr('fill','var(--text-muted)').attr('font-size','10px').text(`${l.label} (${l.count})`) })
  }, [dims, selectedPool])
  return (<div ref={containerRef} style={{width:'100%',height:'300px',position:'relative',overflow:'hidden'}}><svg ref={svgRef} width={dims.width} height={dims.height} style={{position:'absolute',top:0,left:0}}/></div>)
}
