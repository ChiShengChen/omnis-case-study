import { useState } from 'react'
import styles from './App.module.css'
import GlobalControls from './components/GlobalControls'
import TimeRangeChart from './components/TimeRangeChart'
import M2Timeline from './components/M2Timeline'
import SummaryCard from './components/SummaryCard'
import DecompositionChart from './components/DecompositionChart'
import VolumeChart from './components/VolumeChart'
import RebalanceTimingChart from './components/RebalanceTimingChart'
import PositionWidthChart from './components/PositionWidthChart'
import InRangeChart from './components/InRangeChart'
import M3Heatmap from './components/M3Heatmap'
import Methodology from './components/Methodology'
import useDashboardStore from './store/dashboard'

function Card({ title, minHeight, children, style }) {
  return (
    <div className={styles.moduleRow} style={{ minHeight: minHeight || 'auto', ...style }}>
      <div className={styles.module} style={{ flex: 1, width: '100%' }}>
        {title && <h2 className={styles.moduleTitle}>{title}</h2>}
        {children}
      </div>
    </div>
  )
}

function App() {
  useDashboardStore(state => state.selectedPool)
  const [activeTab, setActiveTab] = useState('performance')

  return (
    <div className={styles.appContainer}>
      <header className={styles.header}>
        <h1 className={styles.title}>Omnis Labs {"//"} CLAMM Vault Performance</h1>
        <p className={styles.subtitle}>Katana vs Charm vs Steer • Profitability Analysis</p>
      </header>

      <GlobalControls />

      <div className={styles.tabsContainer}>
        <button 
          type="button"
          className={`${styles.tabButton} ${activeTab === 'performance' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('performance')}
        >
          Performance
        </button>
        <button 
          type="button"
          className={`${styles.tabButton} ${activeTab === 'heatmap' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('heatmap')}
        >
          X-Ray Heatmap
        </button>
        <button 
          type="button"
          className={`${styles.tabButton} ${activeTab === 'methodology' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('methodology')}
        >
          Methodology
        </button>
      </div>

      <div className={styles.dashboardGrid}>
        <div style={{ display: activeTab === 'performance' ? 'flex' : 'none', flexDirection: 'column', gap: 'var(--spacing-4)' }}>
          <Card title="TIME RANGE // PRICE & VOLUME" minHeight="200px">
            <TimeRangeChart />
          </Card>

          <Card title="CUMULATIVE RETURN" minHeight="380px">
            <M2Timeline />
          </Card>

          <Card minHeight="auto">
            <SummaryCard />
          </Card>

          <Card title="RETURN DECOMPOSITION" minHeight="320px">
            <DecompositionChart />
          </Card>

          <Card title="TRADING VOLUME" minHeight="180px">
            <VolumeChart />
          </Card>

          <Card title="REBALANCE TIMING" minHeight="320px">
            <RebalanceTimingChart />
          </Card>

          <Card title="ML POSITION RANGES & TREND SIGNAL" minHeight="420px">
            <PositionWidthChart />
          </Card>

          <Card title="IN-RANGE PERCENTAGE" minHeight="280px">
            <InRangeChart />
          </Card>
        </div>

        <div style={{ display: activeTab === 'heatmap' ? 'flex' : 'none', flexDirection: 'column', gap: 'var(--spacing-4)' }}>
          <Card title="ENTRY/EXIT HEATMAP (X-RAY)" minHeight="650px">
            <M3Heatmap />
          </Card>
        </div>

        <div style={{ display: activeTab === 'methodology' ? 'block' : 'none' }}>
          <Methodology />
        </div>
      </div>
    </div>
  )
}

export default App
