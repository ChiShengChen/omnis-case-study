import styles from './styles.module.css'
import useDashboardStore from '../../store/dashboard'
import { POOL_VAULTS, getVaultMetadata } from '../../utils/dataHelpers'

export default function GlobalControls() {
  const selectedPool = useDashboardStore(state => state.selectedPool)
  const setSelectedPool = useDashboardStore(state => state.setSelectedPool)
  const visibleVaults = useDashboardStore(state => state.visibleVaults)
  const toggleVault = useDashboardStore(state => state.toggleVault)
  const selectedVaultId = useDashboardStore(state => state.selectedVaultId)
  const setSelectedVaultId = useDashboardStore(state => state.setSelectedVaultId)
  const poolVaults = POOL_VAULTS[selectedPool]

  return (
    <div className={styles.controls}>
      <div className={styles.topRow}>
        <div className={styles.poolSelector}>
          <button
            type="button"
            className={`${styles.tab} ${selectedPool === 'WBTC-USDC' ? styles.active : ''}`}
            onClick={() => setSelectedPool('WBTC-USDC')}
          >
            WBTC-USDC
          </button>
          <button
            type="button"
            className={`${styles.tab} ${selectedPool === 'USDC-ETH' ? styles.active : ''}`}
            onClick={() => setSelectedPool('USDC-ETH')}
          >
            USDC-ETH
          </button>
        </div>
        <div className={styles.vaultSelector}>
          {poolVaults.map(vaultId => {
            const meta = getVaultMetadata(vaultId)
            const isChecked = visibleVaults.includes(vaultId)
            const vaultColor = meta?.color || 'var(--text-muted)'
            const shortName = vaultId.replace('-wbtc-usdc', '').replace('-usdc-eth', '').toUpperCase()
            const isFocused = selectedVaultId === vaultId
            
            return (
              <label key={vaultId} className={`${styles.checkboxLabel} ${!isChecked ? styles.unchecked : ''}`}>
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggleVault(vaultId)}
                  className={styles.hiddenCheckbox}
                />
                <span
                  className={styles.colorDot}
                  style={{ backgroundColor: vaultColor, opacity: isChecked ? 1 : 0.3 }}
                />
                <span className={styles.vaultName} style={{ textDecoration: isFocused ? "underline" : "none", cursor: "pointer" }} onClick={(e) => { e.preventDefault(); setSelectedVaultId(vaultId) }}>{shortName}{isFocused ? " ◄" : ""}</span>
              </label>
            )
          })}
        </div>
      </div>
    </div>
  )
}
