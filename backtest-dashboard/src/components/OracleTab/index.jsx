import { useState, useEffect, useMemo } from 'react'
import styles from './styles.module.css'
import useDashboardStore from '../../store/dashboard'

const POOL_MAP = { 'WBTC-USDC': 'wbtc-usdc', 'USDC-ETH': 'usdc-eth' }

// ─── Planetary ephemeris (simplified linear) ──────────────────────
const J2000_UNIX = 946728000
const PLANETS = {
  sun:     { lon0: 280.46, daily: 0.9856,  symbol: '\u2609', color: '#FFD700', name: 'Sun' },
  moon:    { lon0: 218.32, daily: 13.1764, symbol: '\u263D', color: '#C0C0C0', name: 'Moon' },
  mercury: { lon0: 252.25, daily: 4.0923,  symbol: '\u263F', color: '#87CEEB', name: 'Mercury' },
  venus:   { lon0: 181.98, daily: 1.6021,  symbol: '\u2640', color: '#FF69B4', name: 'Venus' },
  mars:    { lon0: 355.45, daily: 0.5240,  symbol: '\u2642', color: '#FF4444', name: 'Mars' },
  jupiter: { lon0: 34.40,  daily: 0.0831,  symbol: '\u2643', color: '#4169E1', name: 'Jupiter' },
  saturn:  { lon0: 49.94,  daily: 0.0335,  symbol: '\u2644', color: '#8B7355', name: 'Saturn' },
}

function planetLon(planet, unixTs) {
  const p = PLANETS[planet]
  const days = (unixTs - J2000_UNIX) / 86400
  return ((p.lon0 + p.daily * days) % 360 + 360) % 360
}

// ─── Moon phase ───────────────────────────────────────────────────
const SYNODIC = 29.53059
const REF_NEW_MOON = 946922040

function moonPhase(unixTs) {
  const days = (unixTs - REF_NEW_MOON) / 86400
  return ((days % SYNODIC) + SYNODIC) % SYNODIC / SYNODIC
}

function moonPhaseName(phase) {
  if (phase < 0.0625) return 'New Moon'
  if (phase < 0.1875) return 'Waxing Crescent'
  if (phase < 0.3125) return 'First Quarter'
  if (phase < 0.4375) return 'Waxing Gibbous'
  if (phase < 0.5625) return 'Full Moon'
  if (phase < 0.6875) return 'Waning Gibbous'
  if (phase < 0.8125) return 'Last Quarter'
  if (phase < 0.9375) return 'Waning Crescent'
  return 'New Moon'
}

// ─── Mercury retrograde check ─────────────────────────────────────
function isMercuryRetrograde(unixTs) {
  const mercLon = planetLon('mercury', unixTs)
  const sunLon = planetLon('sun', unixTs)
  let diff = ((mercLon - sunLon) % 360 + 360) % 360
  // inferior conjunction = 0 degrees; retrograde when within 18 degrees
  return diff < 18 || diff > 342
}

// ─── Zodiac signs ─────────────────────────────────────────────────
const ZODIAC = [
  { name: 'Aries',       symbol: '\u2648' },
  { name: 'Taurus',      symbol: '\u2649' },
  { name: 'Gemini',      symbol: '\u264A' },
  { name: 'Cancer',      symbol: '\u264B' },
  { name: 'Leo',         symbol: '\u264C' },
  { name: 'Virgo',       symbol: '\u264D' },
  { name: 'Libra',       symbol: '\u264E' },
  { name: 'Scorpio',     symbol: '\u264F' },
  { name: 'Sagittarius', symbol: '\u2650' },
  { name: 'Capricorn',   symbol: '\u2651' },
  { name: 'Aquarius',    symbol: '\u2652' },
  { name: 'Pisces',      symbol: '\u2653' },
]

function lonToSign(lon) {
  const idx = Math.floor(((lon % 360) + 360) % 360 / 30)
  return ZODIAC[idx]
}

// ─── Aspects ──────────────────────────────────────────────────────
const ASPECTS = [
  { name: 'Conjunction', symbol: '\u260C', angle: 0,   maxOrb: 8 },
  { name: 'Sextile',    symbol: '\u26B9', angle: 60,  maxOrb: 4 },
  { name: 'Square',     symbol: '\u25A1', angle: 90,  maxOrb: 6 },
  { name: 'Trine',      symbol: '\u25B3', angle: 120, maxOrb: 6 },
  { name: 'Opposition', symbol: '\u260D', angle: 180, maxOrb: 8 },
]

function findAspects(unixTs) {
  const planetKeys = Object.keys(PLANETS)
  const lons = {}
  planetKeys.forEach(k => { lons[k] = planetLon(k, unixTs) })

  const results = []
  for (let i = 0; i < planetKeys.length; i++) {
    for (let j = i + 1; j < planetKeys.length; j++) {
      const a = planetKeys[i], b = planetKeys[j]
      let diff = Math.abs(lons[a] - lons[b])
      if (diff > 180) diff = 360 - diff

      for (const asp of ASPECTS) {
        const orb = Math.abs(diff - asp.angle)
        if (orb <= asp.maxOrb) {
          const strength = +(1 - orb / asp.maxOrb).toFixed(2)
          const isBullish = classifyAspect(asp.name, a, b)
          results.push({
            pair: `${PLANETS[a].symbol} ${PLANETS[a].name} - ${PLANETS[b].symbol} ${PLANETS[b].name}`,
            aspect: asp.name,
            aspectSymbol: asp.symbol,
            orb: +orb.toFixed(1),
            strength,
            tag: isBullish,
          })
        }
      }
    }
  }
  return results
}

function classifyAspect(aspectName, planetA, planetB) {
  // Bearish: square, opposition, Saturn conjunction/square, Mars square
  if (aspectName === 'Square') {
    if (planetA === 'saturn' || planetB === 'saturn') return 'Bearish'
    if (planetA === 'mars' || planetB === 'mars') return 'Bearish'
    return 'Bearish'
  }
  if (aspectName === 'Opposition') return 'Bearish'
  if (aspectName === 'Conjunction') {
    if (planetA === 'saturn' || planetB === 'saturn') return 'Bearish'
    if (planetA === 'jupiter' || planetB === 'jupiter') return 'Bullish'
    return 'Neutral'
  }
  // Bullish: trine, sextile
  if (aspectName === 'Trine') return 'Bullish'
  if (aspectName === 'Sextile') return 'Bullish'
  return 'Neutral'
}

// ─── Meihua relation to score mapping ─────────────────────────────
function meihuaRelationScore(relation) {
  if (!relation) return 0
  if (relation.includes('生體') || relation.includes('(吉)')) return 2
  if (relation.includes('體克用')) return 1
  if (relation.includes('比和')) return 0
  if (relation.includes('體生用') || relation.includes('洩')) return -1
  if (relation.includes('克體') || relation.includes('凶')) return -2
  return 0
}

function fmt(v, decimals = 1) {
  const s = v >= 0 ? '+' : ''
  return `${s}${v.toFixed(decimals)}%`
}

// ─── Data loaders ─────────────────────────────────────────────────
let _mhData = null
async function loadMeihuaData() {
  if (!_mhData) {
    _mhData = (await import('../../../data/meihua_results.json')).default
  }
  return _mhData
}

let _asData = null
async function loadAstroData() {
  if (!_asData) {
    _asData = (await import('../../../data/astro_results.json')).default
  }
  return _asData
}

// ─── Zodiac Wheel SVG ─────────────────────────────────────────────
function ZodiacWheel({ unixTs }) {
  const cx = 200, cy = 200, outerR = 180, innerR = 140, planetR = 110

  const planetPositions = useMemo(() => {
    return Object.entries(PLANETS).map(([key, p]) => {
      const lon = planetLon(key, unixTs)
      // Zodiac wheel: 0 Aries at top, going clockwise
      const angle = (lon - 90) * Math.PI / 180
      return {
        key,
        ...p,
        lon,
        x: cx + planetR * Math.cos(angle),
        y: cy + planetR * Math.sin(angle),
        sign: lonToSign(lon),
      }
    })
  }, [unixTs])

  return (
    <svg viewBox="0 0 400 400" className={styles.wheelSvg} width="380" height="380">
      {/* Outer ring */}
      <circle cx={cx} cy={cy} r={outerR} fill="none" stroke="var(--border-color)" strokeWidth="1" />
      <circle cx={cx} cy={cy} r={innerR} fill="none" stroke="var(--border-color)" strokeWidth="1" />

      {/* Zodiac sign sectors */}
      {ZODIAC.map((z, i) => {
        const startAngle = (i * 30 - 90) * Math.PI / 180
        const endAngle = ((i + 1) * 30 - 90) * Math.PI / 180
        const midAngle = ((i * 30 + 15) - 90) * Math.PI / 180

        // Sector lines
        const x1 = cx + innerR * Math.cos(startAngle)
        const y1 = cy + innerR * Math.sin(startAngle)
        const x2 = cx + outerR * Math.cos(startAngle)
        const y2 = cy + outerR * Math.sin(startAngle)

        // Label position
        const labelR = (outerR + innerR) / 2
        const lx = cx + labelR * Math.cos(midAngle)
        const ly = cy + labelR * Math.sin(midAngle)

        return (
          <g key={z.name}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--border-color)" strokeWidth="0.5" />
            <text
              x={lx} y={ly}
              textAnchor="middle" dominantBaseline="central"
              fontSize="14" fill="var(--text-muted)"
            >
              {z.symbol}
            </text>
          </g>
        )
      })}

      {/* Inner circle background */}
      <circle cx={cx} cy={cy} r={innerR - 2} fill="var(--bg-card, #fff)" opacity="0.5" />

      {/* Planet dots */}
      {planetPositions.map(p => (
        <g key={p.key}>
          <circle cx={p.x} cy={p.y} r={12} fill={p.color} opacity="0.2" />
          <circle cx={p.x} cy={p.y} r={6} fill={p.color} />
          <text
            x={p.x} y={p.y - 16}
            textAnchor="middle" fontSize="14" fill={p.color}
          >
            {p.symbol}
          </text>
          <text
            x={p.x} y={p.y + 20}
            textAnchor="middle" fontSize="8" fill="var(--text-muted)"
          >
            {p.lon.toFixed(0)}&deg;
          </text>
        </g>
      ))}

      {/* Center label */}
      <text x={cx} y={cy - 8} textAnchor="middle" fontSize="10" fill="var(--text-muted)" fontWeight="600">
        ECLIPTIC
      </text>
      <text x={cx} y={cy + 8} textAnchor="middle" fontSize="8" fill="var(--text-faint, #aaa)">
        {new Date(unixTs * 1000).toISOString().slice(0, 10)}
      </text>
    </svg>
  )
}

// ─── Moon Phase Visual ────────────────────────────────────────────
function MoonPhaseVisual({ phase }) {
  // phase: 0=new, 0.5=full
  const r = 24
  const cx = 28, cy = 28

  // illumination fraction: 0 at new, 1 at full, 0 at next new
  const illum = phase <= 0.5 ? phase * 2 : (1 - phase) * 2

  // Terminator curve: use an ellipse approach
  // When waxing (phase < 0.5), right side is lit
  // When waning (phase > 0.5), left side is lit
  const isWaxing = phase < 0.5
  const k = Math.abs(illum * 2 - 1) * r // semi-axis of terminator ellipse

  // Build the lit area as a path
  // Right semicircle arc from top to bottom
  const rightArc = `A ${r} ${r} 0 0 1 ${cx} ${cy + r}`
  // Left semicircle arc from bottom to top
  const leftArc = `A ${r} ${r} 0 0 1 ${cx} ${cy - r}`

  let terminatorArc
  if (illum < 0.5) {
    // Less than half lit: terminator curves inward (concave on lit side)
    terminatorArc = `A ${k} ${r} 0 0 ${isWaxing ? 0 : 1} ${cx} ${cy + r}`
  } else {
    // More than half lit: terminator curves outward
    terminatorArc = `A ${k} ${r} 0 0 ${isWaxing ? 1 : 0} ${cx} ${cy + r}`
  }

  let litPath
  if (isWaxing) {
    // right side lit
    litPath = `M ${cx} ${cy - r} ${rightArc} L ${cx} ${cy + r} ${terminatorArc.replace(cy + r, cy - r).replace(`${cx} ${cy + r}`, `${cx} ${cy - r}`)} Z`
    // Simpler approach: draw right half circle + terminator
    litPath = `M ${cx} ${cy - r} A ${r} ${r} 0 0 1 ${cx} ${cy + r} A ${k || 0.1} ${r} 0 0 ${illum >= 0.5 ? 1 : 0} ${cx} ${cy - r} Z`
  } else {
    // left side lit
    litPath = `M ${cx} ${cy - r} A ${r} ${r} 0 0 0 ${cx} ${cy + r} A ${k || 0.1} ${r} 0 0 ${illum >= 0.5 ? 0 : 1} ${cx} ${cy - r} Z`
  }

  return (
    <svg width="56" height="56" className={styles.moonSvg}>
      {/* Dark moon background */}
      <circle cx={cx} cy={cy} r={r} fill="#2c2c3e" />
      {/* Lit portion */}
      <path d={litPath} fill="#e8e8d0" />
      {/* Outline */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--border-color)" strokeWidth="0.5" />
    </svg>
  )
}

// ─── Signal Meter ─────────────────────────────────────────────────
function SignalMeter({ value, label }) {
  // value from -4 (strong bear) to +4 (strong bull), normalize to 0-100%
  const pct = Math.max(0, Math.min(100, ((value + 4) / 8) * 100))

  return (
    <div>
      {label && <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>}
      <div className={styles.meterContainer}>
        <div className={styles.meterNeedle} style={{ left: `${pct}%` }} />
      </div>
      <div className={styles.meterLabels}>
        <span>Strong Bear</span>
        <span>Neutral</span>
        <span>Strong Bull</span>
      </div>
    </div>
  )
}

// ─── Cross Validation Tag ─────────────────────────────────────────
function crossValidationTag(meihuaScore, astroScore) {
  const both = meihuaScore + astroScore
  if (meihuaScore > 0 && astroScore > 0) return { text: '\u96D9\u591A (Both Bullish)', cls: styles.tagBullish }
  if (meihuaScore < 0 && astroScore < 0) return { text: '\u96D9\u7A7A (Both Bearish)', cls: styles.tagBearish }
  return { text: '\u8A0A\u865F\u5206\u6B67 (Disagreement)', cls: styles.tagMixed }
}

// ─── Main Component ───────────────────────────────────────────────
export default function OracleTab() {
  const selectedPool = useDashboardStore(s => s.selectedPool)
  const poolKey = POOL_MAP[selectedPool] || 'wbtc-usdc'

  const [meihuaData, setMeihuaData] = useState(null)
  const [astroData, setAstroData] = useState(null)

  useEffect(() => {
    loadMeihuaData().then(setMeihuaData)
    loadAstroData().then(setAstroData)
  }, [])

  const poolMeihua = meihuaData?.[poolKey]
  const poolAstro = astroData?.[poolKey]

  // Use latest astro log timestamp for planetary calculations
  const latestTs = useMemo(() => {
    if (!poolAstro?.astro_log?.length) return Date.now() / 1000
    const lastEntry = poolAstro.astro_log[poolAstro.astro_log.length - 1]
    // Parse the date string from astro_log
    return new Date(lastEntry.date.replace(' ', 'T') + ':00Z').getTime() / 1000
  }, [poolAstro])

  // Compute aspects
  const aspects = useMemo(() => findAspects(latestTs), [latestTs])

  // Moon info
  const phase = useMemo(() => moonPhase(latestTs), [latestTs])
  const mercRetro = useMemo(() => isMercuryRetrograde(latestTs), [latestTs])
  const moonSign = useMemo(() => lonToSign(planetLon('moon', latestTs)), [latestTs])

  // Cross-validation: match events by closest block number
  const crossEvents = useMemo(() => {
    if (!poolMeihua?.gua_log || !poolAstro?.astro_log) return []

    const events = []
    const mhLog = poolMeihua.gua_log
    const asLog = poolAstro.astro_log

    // For each meihua event, find closest astro event
    for (const mh of mhLog) {
      let bestAstro = null
      let bestDist = Infinity
      for (const as of asLog) {
        const dist = Math.abs(mh.block - as.block)
        if (dist < bestDist) {
          bestDist = dist
          bestAstro = as
        }
      }
      // Only pair if within 500k blocks (~6 days)
      if (bestAstro && bestDist < 500000) {
        const mhScore = meihuaRelationScore(mh.relation)
        const asScore = bestAstro.width_score
        events.push({
          meihua: mh,
          astro: bestAstro,
          meihuaScore: mhScore,
          astroScore: asScore,
          combined: (mhScore + asScore) / 2,
          blockDist: bestDist,
        })
      }
    }
    return events
  }, [poolMeihua, poolAstro])

  if (!meihuaData || !astroData) {
    return <div style={{ padding: 20, color: 'var(--text-muted)' }}>Loading oracle data...</div>
  }

  if (!poolMeihua || !poolAstro) {
    return <div style={{ padding: 20 }}>No oracle data for {selectedPool}</div>
  }

  const latestMh = poolMeihua.gua_log[poolMeihua.gua_log.length - 1]
  const latestAs = poolAstro.astro_log[poolAstro.astro_log.length - 1]

  return (
    <div className={styles.container}>
      {/* 1. Header */}
      <div className={styles.section} style={{ textAlign: 'center' }}>
        <div className={styles.headerTitle}>
          DUAL ORACLE &mdash; East &times; West Cross-Validation
        </div>
        <div className={styles.headerSubtitle}>
          {'\u6885\u82B1\u6613\u6578'} (Meihua Yishu) + Financial Astrology &bull; {selectedPool}
        </div>
      </div>

      {/* 2. Zodiac Wheel + 5. Meihua Panel (side by side) */}
      <div className={styles.dualPanel}>
        {/* Western: Zodiac Wheel */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>Zodiac Wheel &mdash; Planetary Positions</h3>
          <div className={styles.wheelContainer}>
            <ZodiacWheel unixTs={latestTs} />
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textAlign: 'center', marginTop: 4 }}>
            Epoch: {new Date(latestTs * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC
          </div>
        </div>

        {/* Eastern: Meihua Panel */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>{'\u6885\u82B1\u6613\u6578'} &mdash; Plum Blossom Numerology</h3>

          {/* Latest hexagram */}
          <div className={styles.guaCard}>
            <div className={styles.guaHex}>{latestMh.hexagram}</div>
            <div className={styles.guaName}>{latestMh.name}</div>
            <div className={styles.guaMeta}>
              <span className={styles.guaMetaLabel}>{'\u9AD4\u7528\u95DC\u4FC2'}</span>
              <span className={styles.guaMetaValue}>{latestMh.relation}</span>
              <span className={styles.guaMetaLabel}>{'\u5BEC\u5EA6'} Width</span>
              <span className={styles.guaMetaValue}>{latestMh.width}</span>
              <span className={styles.guaMetaLabel}>{'\u504F\u5411'} Bias</span>
              <span className={styles.guaMetaValue}>{latestMh.bias}</span>
              <span className={styles.guaMetaLabel}>Cooldown</span>
              <span className={styles.guaMetaValue}>{latestMh.cooldown} blocks</span>
            </div>
          </div>

          {/* All rebalance events */}
          <div style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Rebalance Log ({'\u5366\u8C61\u8A18\u9304'})
          </div>
          <table className={styles.guaLogTable}>
            <thead>
              <tr>
                <th>Block</th>
                <th>{'\u5366'}</th>
                <th>{'\u540D'}</th>
                <th>{'\u751F\u514B'}</th>
                <th>Width</th>
                <th>Bias</th>
              </tr>
            </thead>
            <tbody>
              {poolMeihua.gua_log.map((g, i) => (
                <tr key={i}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem' }}>{g.block.toLocaleString()}</td>
                  <td style={{ fontSize: '1rem' }}>{g.hexagram}</td>
                  <td>{g.name}</td>
                  <td>{g.relation}</td>
                  <td>{g.width}</td>
                  <td>{g.bias}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 3. Aspect Table */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Planetary Aspects &mdash; Current Configuration</h3>
        {aspects.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', padding: 'var(--spacing-3)' }}>
            No major aspects detected at current epoch.
          </div>
        ) : (
          <table className={styles.aspectTable}>
            <thead>
              <tr>
                <th>Planet Pair</th>
                <th>Aspect</th>
                <th>Orb</th>
                <th>Strength</th>
                <th>Signal</th>
              </tr>
            </thead>
            <tbody>
              {aspects.map((a, i) => (
                <tr key={i}>
                  <td style={{ textAlign: 'left' }}>{a.pair}</td>
                  <td>{a.aspectSymbol} {a.aspect}</td>
                  <td>{a.orb}&deg;</td>
                  <td>
                    <div style={{
                      display: 'inline-block',
                      width: 48,
                      height: 6,
                      background: 'var(--border-color)',
                      borderRadius: 3,
                      overflow: 'hidden',
                      verticalAlign: 'middle',
                      marginRight: 6,
                    }}>
                      <div style={{
                        width: `${a.strength * 100}%`,
                        height: '100%',
                        background: a.tag === 'Bullish' ? 'var(--accent-green, #2ecc71)' : a.tag === 'Bearish' ? 'var(--accent-red, #e74c3c)' : 'var(--text-muted)',
                        borderRadius: 3,
                      }} />
                    </div>
                    {(a.strength * 100).toFixed(0)}%
                  </td>
                  <td className={a.tag === 'Bullish' ? styles.bullish : a.tag === 'Bearish' ? styles.bearish : styles.neutral}>
                    {a.tag}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 4. Moon Phase & Mercury Retrograde */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Lunar &amp; Mercury Status</h3>
        <div className={styles.moonRow}>
          <div className={styles.moonCard}>
            <MoonPhaseVisual phase={phase} />
            <div className={styles.moonLabel}>Moon Phase</div>
            <div className={styles.moonValue}>{moonPhaseName(phase)}</div>
            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 2 }}>
              {(phase * 100).toFixed(1)}% of cycle
            </div>
          </div>
          <div className={styles.moonCard}>
            <div style={{ fontSize: '2rem', marginBottom: 8 }}>{moonSign.symbol}</div>
            <div className={styles.moonLabel}>Moon Sign</div>
            <div className={styles.moonValue}>{moonSign.name}</div>
          </div>
          <div className={styles.moonCard}>
            <div style={{ fontSize: '2rem', marginBottom: 8, color: mercRetro ? '#e74c3c' : '#2ecc71' }}>
              {'\u263F'}{mercRetro ? ' Rx' : ''}
            </div>
            <div className={styles.moonLabel}>Mercury</div>
            <div className={styles.moonValue} style={{ color: mercRetro ? '#e74c3c' : '#2ecc71' }}>
              {mercRetro ? 'RETROGRADE' : 'Direct'}
            </div>
            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 2 }}>
              {mercRetro ? 'Caution: comms/trades disrupted' : 'Normal transit'}
            </div>
          </div>
          <div className={styles.moonCard}>
            <div style={{ fontSize: '2rem', marginBottom: 8 }}>{latestAs.moon_sign === moonSign.name ? '\u2713' : '\u2605'}</div>
            <div className={styles.moonLabel}>Astro Moon Sign</div>
            <div className={styles.moonValue}>{latestAs.moon_sign}</div>
            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 2 }}>
              From latest rebalance log
            </div>
          </div>
        </div>
      </div>

      {/* 6. Signal Meter - Cross Validation Events */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Signal Meter &mdash; Cross Validation</h3>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 'var(--spacing-3)' }}>
          Combined East + West signal for each rebalance event. Meihua score: {'\u751F\u514B'} relation mapped to [-2, +2].
          Astro score: width_score from planetary aspects. Combined = average.
        </div>

        {crossEvents.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No matched events found.</div>
        ) : (
          <div className={styles.eventGrid}>
            {crossEvents.map((ev, i) => {
              const tag = crossValidationTag(ev.meihuaScore, ev.astroScore)
              return (
                <div key={i} className={styles.eventCard}>
                  <div className={styles.eventHeader}>
                    <div>
                      <div className={styles.eventDate}>
                        {ev.astro.date || `Block ${ev.meihua.block.toLocaleString()}`}
                      </div>
                      <div className={styles.eventPrice}>
                        ${ev.meihua.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </div>
                    </div>
                    <span className={`${styles.signalTag} ${tag.cls}`}>{tag.text}</span>
                  </div>
                  <div className={styles.eventScores}>
                    <div>
                      <div className={styles.scoreLabel}>{'\u6885\u82B1'} Score</div>
                      <div className={`${styles.scoreValue} ${ev.meihuaScore >= 0 ? styles.positive : styles.negative}`}>
                        {ev.meihuaScore > 0 ? '+' : ''}{ev.meihuaScore}
                      </div>
                    </div>
                    <div>
                      <div className={styles.scoreLabel}>Astro Score</div>
                      <div className={`${styles.scoreValue} ${ev.astroScore >= 0 ? styles.positive : styles.negative}`}>
                        {ev.astroScore > 0 ? '+' : ''}{ev.astroScore.toFixed(2)}
                      </div>
                    </div>
                    <div>
                      <div className={styles.scoreLabel}>Combined</div>
                      <div className={`${styles.scoreValue} ${ev.combined >= 0 ? styles.positive : styles.negative}`}>
                        {ev.combined > 0 ? '+' : ''}{ev.combined.toFixed(2)}
                      </div>
                    </div>
                  </div>
                  <SignalMeter value={ev.combined * 2} label={null} />
                  {/* Astro signals */}
                  <div className={styles.signalList}>
                    <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', marginRight: 4 }}>{'\u2609'}:</span>
                    {ev.astro.signals.map((s, j) => (
                      <span key={j} className={styles.signalChip}>{s}</span>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    {'\u5366'} {ev.meihua.hexagram} {ev.meihua.name} &bull; {ev.meihua.relation}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 7. Performance Comparison Table */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Performance Comparison &mdash; {selectedPool}</h3>
        <table className={styles.comparisonTable}>
          <thead>
            <tr>
              <th>Metric</th>
              <th style={{ color: '#8B5CF6' }}>{'\u6885\u82B1'} Meihua</th>
              <th style={{ color: '#FF6B9D' }}>Astro</th>
              <th style={{ color: 'var(--text-main)' }}>ML Baseline</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={{ textAlign: 'left', color: 'var(--text-muted)' }}>Baseline {'\u03B1'}</td>
              <td className={poolMeihua.baseline_alpha >= 0 ? styles.positive : styles.negative}>
                {fmt(poolMeihua.baseline_alpha)}
              </td>
              <td className={poolAstro.baseline_alpha >= 0 ? styles.positive : styles.negative}>
                {fmt(poolAstro.baseline_alpha)}
              </td>
              <td className={(poolMeihua.ml_baseline_alpha || 0) >= 0 ? styles.positive : styles.negative}>
                {fmt(poolMeihua.ml_baseline_alpha || 0)}
              </td>
            </tr>
            <tr>
              <td style={{ textAlign: 'left', color: 'var(--text-muted)' }}>Vault Return</td>
              <td className={poolMeihua.vault_return >= 0 ? styles.positive : styles.negative}>
                {fmt(poolMeihua.vault_return)}
              </td>
              <td className={poolAstro.vault_return >= 0 ? styles.positive : styles.negative}>
                {fmt(poolAstro.vault_return)}
              </td>
              <td style={{ color: 'var(--text-muted)' }}>&mdash;</td>
            </tr>
            <tr>
              <td style={{ textAlign: 'left', color: 'var(--text-muted)' }}>Fee Income (bps)</td>
              <td>{poolMeihua.fee_bps.toFixed(1)}</td>
              <td>{poolAstro.fee_bps.toFixed(1)}</td>
              <td style={{ color: 'var(--text-muted)' }}>&mdash;</td>
            </tr>
            <tr>
              <td style={{ textAlign: 'left', color: 'var(--text-muted)' }}>Rebalances</td>
              <td>{poolMeihua.rebalances}</td>
              <td>{poolAstro.rebalances}</td>
              <td style={{ color: 'var(--text-muted)' }}>&mdash;</td>
            </tr>
            <tr>
              <td style={{ textAlign: 'left', color: 'var(--text-muted)' }}>Bootstrap P({'\u03B1'}&gt;0)</td>
              <td className={poolMeihua.bootstrap.p_positive >= 50 ? styles.positive : styles.negative}>
                {poolMeihua.bootstrap.p_positive}%
              </td>
              <td className={poolAstro.bootstrap.p_positive >= 50 ? styles.positive : styles.negative}>
                {poolAstro.bootstrap.p_positive}%
              </td>
              <td style={{ color: 'var(--text-muted)' }}>&mdash;</td>
            </tr>
            <tr>
              <td style={{ textAlign: 'left', color: 'var(--text-muted)' }}>Bootstrap Median</td>
              <td className={poolMeihua.bootstrap.median >= 0 ? styles.positive : styles.negative}>
                {fmt(poolMeihua.bootstrap.median)}
              </td>
              <td className={poolAstro.bootstrap.median >= 0 ? styles.positive : styles.negative}>
                {fmt(poolAstro.bootstrap.median)}
              </td>
              <td style={{ color: 'var(--text-muted)' }}>&mdash;</td>
            </tr>
            <tr>
              <td style={{ textAlign: 'left', color: 'var(--text-muted)' }}>Bootstrap 5th / 95th</td>
              <td>
                <span className={styles.negative}>{fmt(poolMeihua.bootstrap.pct5)}</span>
                {' / '}
                <span className={styles.positive}>{fmt(poolMeihua.bootstrap.pct95)}</span>
              </td>
              <td>
                <span className={styles.negative}>{fmt(poolAstro.bootstrap.pct5)}</span>
                {' / '}
                <span className={styles.positive}>{fmt(poolAstro.bootstrap.pct95)}</span>
              </td>
              <td style={{ color: 'var(--text-muted)' }}>&mdash;</td>
            </tr>
          </tbody>
        </table>

        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 'var(--spacing-3)', lineHeight: 1.6 }}>
          <p><strong>{'\u6885\u82B1\u6613\u6578'}</strong> uses I-Ching hexagram casting derived from block numbers to determine
          Ti/Yong ({'\u9AD4\u7528'}) elemental relationships, mapping Five Elements generation/destruction cycles to
          position width and directional bias.</p>
          <p style={{ marginTop: 6 }}><strong>Financial Astrology</strong> computes planetary aspects, lunar phases, and
          Mercury retrograde periods to derive width_score and trend_score signals for LP positioning.</p>
          <p style={{ marginTop: 6 }}><strong>Cross-validation</strong> checks agreement between independent Eastern and Western
          oracle systems. When both signal the same direction ({'\u96D9\u591A'}/{'\u96D9\u7A7A'}), conviction is higher.
          Disagreement ({'\u8A0A\u865F\u5206\u6B67'}) suggests caution and wider ranges.</p>
        </div>
      </div>
    </div>
  )
}
