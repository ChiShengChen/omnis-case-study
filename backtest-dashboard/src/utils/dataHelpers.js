import metadata from '../../data/metadata.json'

export const POOL_VAULTS = {
  'WBTC-USDC': ['omnis-wbtc-usdc', 'charm-wbtc-usdc', 'ml-wbtc-usdc'],
  'USDC-ETH': ['omnis-usdc-eth', 'charm-usdc-eth', 'steer-usdc-eth', 'ml-usdc-eth']
}

export const getVaultMetadata = (vaultId) => {
  const base = metadata.vaults.find(v => v.id === vaultId)
  if (!base) return null

  if (vaultId.startsWith('omnis')) return { ...base, color: '#F7931A' }
  if (vaultId.startsWith('charm')) return { ...base, color: '#00A3FF' }
  if (vaultId.startsWith('steer')) return { ...base, color: '#FF6B6B' }
  if (vaultId.startsWith('ml-')) return { ...base, color: '#22C55E' }
  return base
}

let _windows = null
let _intervals = null
export const windowMap = {}

export async function loadWindows() {
  if (!_windows) {
    _windows = (await import('../../data/windows.json')).default
    for (const vault of Object.keys(_windows)) {
      windowMap[vault] = {}
      for (const w of _windows[vault].windows) {
        if (!windowMap[vault][w.ei]) windowMap[vault][w.ei] = {}
        windowMap[vault][w.ei][w.xi] = w
      }
    }
  }
  return _windows
}

export async function loadIntervals() {
  if (!_intervals) {
    _intervals = (await import('../../data/intervals.json')).default
  }
  return _intervals
}

export const getWindowData = (vaultId, ei, xi) => {
  return windowMap[vaultId]?.[ei]?.[xi] || null
}

export const sliceIntervals = (vaultId, startDateStr, endDateStr) => {
  if (!_intervals) return null
  const data = _intervals[vaultId]
  if (!data) return null

  const sliced = {
    timestamps: [],
    vault_return: [],
    hodl_return: [],
    net_alpha: [],
    realized_fee_return: [],
    residual_drag: [],
    asset_price: [],
    pool_volume_usdc: []
  }

  for (let i = 0; i < data.timestamps.length; i++) {
    const ts = data.timestamps[i]
    const day = new Date(ts * 1000).toISOString().slice(0, 10)
    if (day >= startDateStr && day <= endDateStr) {
      sliced.timestamps.push(ts)
      sliced.vault_return.push(data.vault_return[i])
      sliced.hodl_return.push(data.hodl_return[i])
      sliced.net_alpha.push(data.net_alpha[i])
      sliced.realized_fee_return.push(data.realized_fee_return[i])
      sliced.residual_drag.push(data.residual_drag[i])
      sliced.asset_price.push(data.asset_price[i])
      sliced.pool_volume_usdc.push(data.pool_volume_usdc[i])
    }
  }

  return sliced
}
