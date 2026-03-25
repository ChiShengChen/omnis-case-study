import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import rebalanceData from '../../../data/rebalance-data.json'
import useDashboardStore from '../../store/dashboard'
const POOL_MAP = { 'WBTC-USDC': 'WBTC-USDC', 'USDC-ETH': 'USDC-ETH' }
export default function PositionWidthChart() {
  const selectedPool = useDashboardStore(state => state.selectedPool)
  const containerRef = useRef(null), svgRef = useRef(null)
  const [dims, setDims] = useState({ width: 0, height: 0 })
  useEffect(() => { const el = containerRef.current; if (!el) return; const ro = new ResizeObserver(e => { setDims(e[0].contentRect) }); ro.observe(el); return () => ro.unobserve(el) }, [])
  useEffect(() => {
    const { width, height } = dims; if (!width || !height) return
    const svg = d3.select(svgRef.current); svg.selectAll('*').remove()
    const poolData = rebalanceData.pools[POOL_MAP[selectedPool]]; if (!poolData) return
    const mlRbs = poolData.rebalances.ml; if (!mlRbs || !mlRbs.length) return
    const prices = poolData.prices
    const margin = { top: 20, right: 20, bottom: 25, left: 65 }
    const topH = (height-margin.top-margin.bottom)*0.65, botH = (height-margin.top-margin.bottom)*0.3, gap = (height-margin.top-margin.bottom)*0.05
    const w = width - margin.left - margin.right
    const g = svg.append('g').attr('transform',`translate(${margin.left},${margin.top})`)
    const xScale = d3.scaleTime().domain(d3.extent(prices,d=>new Date(d.ts*1000))).range([0,w])
    const yScale = d3.scaleLinear().domain(d3.extent(prices,d=>d.price)).nice().range([topH,0])
    g.append('g').call(d3.axisLeft(yScale).tickSize(-w).tickFormat('')).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)').attr('stroke-width',0.5).attr('stroke-dasharray','2,4'))
    g.append('path').datum(prices).attr('fill','none').attr('stroke','#e2e8f0').attr('stroke-width',1.5).attr('d',d3.line().x(d=>xScale(new Date(d.ts*1000))).y(d=>yScale(d.price)))
    for (let i=0;i<mlRbs.length;i++) {
      const rb=mlRbs[i], x1=xScale(new Date(rb.ts*1000)), x2=i+1<mlRbs.length?xScale(new Date(mlRbs[i+1].ts*1000)):xScale(xScale.domain()[1])
      g.append('rect').attr('x',x1).attr('width',Math.max(1,x2-x1)).attr('y',yScale(rb.wide_hi)).attr('height',Math.max(0,yScale(rb.wide_lo)-yScale(rb.wide_hi))).attr('fill','#22C55E').attr('opacity',0.08)
      g.append('rect').attr('x',x1).attr('width',Math.max(1,x2-x1)).attr('y',yScale(rb.narrow_hi)).attr('height',Math.max(0,yScale(rb.narrow_lo)-yScale(rb.narrow_hi))).attr('fill','#22C55E').attr('opacity',0.25)
    }
    g.append('g').attr('transform',`translate(0,${topH})`).call(d3.axisBottom(xScale).ticks(8).tickFormat(d3.timeFormat('%b %d'))).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('text').attr('fill','var(--text-muted)')).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)'))
    g.append('g').call(d3.axisLeft(yScale).ticks(5).tickFormat(d=>`$${d3.format(',.0f')(d)}`)).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('text').attr('fill','var(--text-muted)')).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)'))
    const leg=g.append('g').attr('transform',`translate(${w-160},10)`)
    ;[{label:'Narrow ±3.9%',op:0.3},{label:'Wide ±17.85%',op:0.1}].forEach((l,i)=>{const row=leg.append('g').attr('transform',`translate(0,${i*16})`);row.append('rect').attr('width',12).attr('height',10).attr('fill','#22C55E').attr('opacity',l.op);row.append('text').attr('x',16).attr('y',9).attr('fill','var(--text-muted)').attr('font-size','10px').text(l.label)})
    const gBot=svg.append('g').attr('transform',`translate(${margin.left},${margin.top+topH+gap})`)
    const trendScale=d3.scaleLinear().domain([-1,1]).range([botH,0])
    gBot.append('line').attr('x1',0).attr('x2',w).attr('y1',trendScale(0)).attr('y2',trendScale(0)).attr('stroke','var(--border-color)').attr('stroke-width',0.5)
    gBot.append('line').attr('x1',0).attr('x2',w).attr('y1',trendScale(0.2)).attr('y2',trendScale(0.2)).attr('stroke','#22C55E').attr('stroke-width',0.5).attr('stroke-dasharray','3,3').attr('opacity',0.5)
    gBot.append('line').attr('x1',0).attr('x2',w).attr('y1',trendScale(-0.2)).attr('y2',trendScale(-0.2)).attr('stroke','#ef4444').attr('stroke-width',0.5).attr('stroke-dasharray','3,3').attr('opacity',0.5)
    mlRbs.forEach(rb=>{const x=xScale(new Date(rb.ts*1000)),color=rb.trend<-0.2?'#ef4444':rb.trend>0.2?'#22C55E':'#64748b';gBot.append('rect').attr('x',x-2).attr('width',4).attr('y',rb.trend>=0?trendScale(rb.trend):trendScale(0)).attr('height',Math.abs(trendScale(rb.trend)-trendScale(0))).attr('fill',color).attr('opacity',0.7)})
    gBot.append('g').call(d3.axisLeft(trendScale).ticks(3).tickFormat(d3.format('.1f'))).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('text').attr('fill','var(--text-muted)').attr('font-size','9px')).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)'))
    gBot.append('text').attr('x',-10).attr('y',-5).attr('fill','var(--text-muted)').attr('font-size','9px').text('Trend')
  }, [dims, selectedPool])
  return (<div ref={containerRef} style={{width:'100%',height:'400px',position:'relative',overflow:'hidden'}}><svg ref={svgRef} width={dims.width} height={dims.height} style={{position:'absolute',top:0,left:0}}/></div>)
}
