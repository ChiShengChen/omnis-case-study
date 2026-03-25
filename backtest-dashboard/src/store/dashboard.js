import { create } from 'zustand'
import { POOL_VAULTS } from '../utils/dataHelpers'

const useDashboardStore = create((set) => ({
  selectedPool: 'WBTC-USDC',
  visibleVaults: POOL_VAULTS['WBTC-USDC'],
  selectedWindow: null,
  selectedVaultId: null,
  brushRange: null,
  boxSelection: null,
  highlightedDateRange: null,
  alignedMode: false,
  unitMode: 'pct',

  setSelectedPool: (pool) => set({
    selectedPool: pool,
    visibleVaults: POOL_VAULTS[pool],
    selectedWindow: null,
    brushRange: null,
    boxSelection: null,
    highlightedDateRange: null
  }),
  setVisibleVaults: (vaults) => set({ visibleVaults: vaults }),
  toggleVault: (vaultId) => set((state) => ({
    visibleVaults: state.visibleVaults.includes(vaultId)
      ? state.visibleVaults.filter(v => v !== vaultId)
      : [...state.visibleVaults, vaultId]
  })),
  setSelectedWindow: (window) => set({ selectedWindow: window }),
  setSelectedVaultId: (vaultId) => set({ selectedVaultId: vaultId }),
  setBrushRange: (range) => set({ brushRange: range }),
  setBoxSelection: (selection) => set({ boxSelection: selection }),
  setHighlightedDateRange: (range) => set({ highlightedDateRange: range }),
  setAlignedMode: (mode) => set({ alignedMode: mode }),
  setUnitMode: (mode) => set({ unitMode: mode }),
  resetSelections: () => set({
    selectedWindow: null,
    brushRange: null,
    boxSelection: null,
    highlightedDateRange: null
  }),
}))

export default useDashboardStore
