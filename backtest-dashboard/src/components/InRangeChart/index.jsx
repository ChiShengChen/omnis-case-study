import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import rebalanceData from '../../../data/rebalance-data.json'
import useDashboardStore from '../../store/dashboard'
const POOL_MAP = { 'WBTC-USDC': 'WBTC-USDC', 'USDC-ETH': 'USDC-ETH' }
export default function InRangeChart() {
  const selectedPool = useDashboardStore(state => state.selectedPool)
  const containerRef = useRef(null), svgRef = useRef(null)
  const [dims, setDims] = useState({ width: 0, height: 0 })
  useEffect(() => { const el = containerRef.current; if (!el) return; const ro = new ResizeObserver(e => { setDims(e[0].contentRect) }); ro.observe(el); return () => ro.unobserve(el) }, [])
  useEffect(() => {
    const { width, height } = dims; if (!width || !height) return
    const svg = d3.select(svgRef.current); svg.selectAll('*').remove()
    const poolData = rebalanceData.pools[POOL_MAP[selectedPool]]; if (!poolData) return
    const margin = { top: 20, right: 90, bottom: 25, left: 55 }
    const w = width-margin.left-margin.right, h = height-margin.top-margin.bottom
    const g = svg.append('g').attr('transform',`translate(${margin.left},${margin.top})`)
    const vcs = [{key:'omnis',color:'#F7931A',label:'Omnis'},{key:'ml',color:'#22C55E',label:'Multi-Layer'}]
    let allPts = []; const seriesMap = {}
    for (const vc of vcs) { const s = poolData.in_range[vc.key]; if (!s||!s.length) continue; seriesMap[vc.key]=s; allPts=allPts.concat(s) }
    if (!allPts.length) return
    const xScale = d3.scaleTime().domain(d3.extent(allPts,d=>new Date(d.ts*1000))).range([0,w])
    const yScale = d3.scaleLinear().domain([0,105]).range([h,0])
    g.append('g').call(d3.axisLeft(yScale).tickSize(-w).tickFormat('')).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)').attr('stroke-width',0.5).attr('stroke-dasharray','2,4'))
    const line = d3.line().x(d=>xScale(new Date(d.ts*1000))).y(d=>yScale(d.pct))
    for (const vc of vcs) { const s=seriesMap[vc.key]; if(!s) continue; g.append('path').datum(s).attr('fill','none').attr('stroke',vc.color).attr('stroke-width',2).attr('d',line); const last=s[s.length-1]; if(last){g.append('text').attr('x',xScale(new Date(last.ts*1000))+6).attr('y',yScale(last.pct)).attr('fill',vc.color).attr('font-size','11px').attr('font-weight','bold').attr('dominant-baseline','middle').text(`${vc.label}: ${last.pct.toFixed(1)}%`)} }
    g.append('g').attr('transform',`translate(0,${h})`).call(d3.axisBottom(xScale).ticks(8).tickFormat(d3.timeFormat('%b %d'))).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('text').attr('fill','var(--text-muted)')).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)'))
    g.append('g').call(d3.axisLeft(yScale).ticks(5).tickFormat(d=>`${d}%`)).call(g=>g.select('.domain').remove()).call(g=>g.selectAll('text').attr('fill','var(--text-muted)')).call(g=>g.selectAll('.tick line').attr('stroke','var(--border-color)'))
  }, [dims, selectedPool])
  return (<div ref={containerRef} style={{width:'100%',height:'260px',position:'relative',overflow:'hidden'}}><svg ref={svgRef} width={dims.width} height={dims.height} style={{position:'absolute',top:0,left:0}}/></div>)
}
