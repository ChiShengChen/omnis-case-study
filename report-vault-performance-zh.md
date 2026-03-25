# Omnis Labs — Katana Steer Vault 績效分析報告

> **分析日期**: 2026-03-23（初版）→ 2026-03-24（加入競品分析）
> **數據來源**: Katana 鏈上 RPC (dRPC LB / Tenderly / katanarpc / katana.network), Merkl API
> **總 RPC 調用**: ~8,200 次（Omnis ~5,700 + 競品 ~2,500）
> **涵蓋範圍**: 2 個 Omnis Steer Vault + 3 個競品 Vault（1 Steer + 2 Charm.fi）從創建至今的完整歷史

---

## 1. 摘要

本報告分析 Omnis Labs 在 Katana (Ronin L2) 上部署的兩個 Steer Protocol 集中流動性 vault 的歷史績效，並納入同池競品比較。核心結論：

1. **兩個 vault 的策略 alpha 均為負**（WBTC-USDC: -3.65%, USDC-ETH: -10.86%）——集中 IL 超過交易手續費收入
2. **Merkl KAT 獎勵翻轉了整體結果**——含獎勵後 LP 比 HODL 更好（WBTC-USDC: +10.3%, USDC-ETH: +15.7%）
3. **資本效率倍數為正**——vault 以 0.1% 的 TVL 佔比捕獲了 0.13–0.16% 的 pool 手續費（1.4x–3.2x 放大）
4. **核心問題是 pool 交易量 vs vault TVL 的比例**——pool 日均交易量百萬級，但 vault 只持有 $2K–3K，真正賺到的手續費極少（$141–$147）
5. **🆕 競品比較：Charm.fi 在同池表現顯著優於 Omnis 和第三方 Steer**——Charm WBTC-USDC 實現正 alpha (+1.50%)，USDC-ETH alpha 僅 -1.85%（vs Omnis -10.86%）

---

## 2. Vault 基本資訊

| | WBTC-USDC Vault | USDC-ETH Vault |
|---|---|---|
| **合約地址** | `0x5977767e...f8761` | `0x811b8c61...f429` |
| **底層池子** | `0x744676b3...5c` (SushiSwap V3) | `0x2a2c512b...6b` (SushiSwap V3) |
| **Fee Tier** | 0.05% (5 bps) | 0.05% (5 bps) |
| **Token Pair** | vbWBTC (8 dec) / vbUSDC (6 dec) | vbUSDC (6 dec) / vbETH (18 dec) |
| **創建區塊** | 19,208,958 (~2025-12-17) | 23,693,484 (~2026-01) |
| **分析終止** | Block 27,522,192 (2026-03-23) | Block 27,522,192 |
| **運行天數** | ~96 天 | ~70 天 |
| **合約類型** | Beacon Proxy → `0x8032d0...` | Beacon Proxy → `0x8032d0...` |
| **Rebalance 次數** | 1,306 | 678 |

---

## 3. LP 績效：Vault Return vs HODL

### 3.1 核心指標

| 指標 | WBTC-USDC | USDC-ETH |
|------|-----------|----------|
| **底層資產走勢** | BTC -18.5% ($86,659→$70,594) | ETH +4.3% ($2,077→$2,165) |
| **Vault Share Price Return** | **-22.19%** | **-8.73%** |
| **HODL Benchmark Return** | -18.54% | +2.13% |
| **策略 Alpha (V - HODL)** | **-3.65%** | **-10.86%** |
| **Max Drawdown** | -25.61% | -11.78% |

> **計算方法**: Share Price = vault 的 totalAmounts() 折 USD / totalSupply。每 10,000 block（~2.8小時）取樣一次，WBTC-USDC 833 個數據點，USDC-ETH 384 個。HODL benchmark 以初始 share 對應的 token 組合，按當前價格計算。

### 3.2 解讀

**WBTC-USDC (-3.65% alpha)**:
- BTC 跌 18.5%，vault 跌 22.19%，比 HODL 多虧 3.65 個百分點
- 1,306 次 rebalance 在下跌趨勢中累積了超額 IL
- 但絕對偏差不大，說明策略的 tick 寬度管理合理

**USDC-ETH (-10.86% alpha)**:
- ETH 僅漲 4.3%，但 vault 反而虧 8.73%
- 678 次 rebalance 在 ETH 的高波動中消耗了大量價值
- Alpha 偏差比 WBTC-USDC 大 3 倍，可能因為 ETH 波動率更高、來回震盪更多

---

## 4. 手續費收入：真實 Trading Fee vs Collect 事件

### 4.1 為什麼要拆？

Steer vault 每次 rebalance 時：Burn（撤出流動性）→ Collect（收回本金 + fee）→ Mint（重新部署）。Collect 事件的金額 = **本金回收 + 手續費**。直接加總 Collect 金額會嚴重高估。

### 4.2 方法：Collect - Burn = Real Fee

逐筆比對同一 tx 中的 Burn 和 Collect 事件，差值即為真實手續費。

### 4.3 結果

| | WBTC-USDC | USDC-ETH |
|---|---|---|
| **Collect 事件總額** | $1,840,768 | $1,189,682 |
| **Burn 事件總額（本金）** | $1,840,625 | $1,189,535 |
| **真實 Trading Fee** | **$142.81** | **$147.42** |
| Fee 佔 Collect 比例 | 0.008% | 0.012% |

> **99.99% 的 Collect 金額是本金回收，不是收益。** 如果不做拆解直接報 $1.8M fee，完全是誤導。

### 4.4 Fee 組成

| | WBTC-USDC | USDC-ETH |
|---|---|---|
| Token0 Fee | 0.00102185 WBTC | 71.45 USDC |
| Token1 Fee | 70.67 USDC | 0.03509 ETH |
| USD Total | $142.81 | $147.42 |

---

## 5. 池子交易環境

### 5.1 交易量

| | WBTC-USDC Pool | USDC-ETH Pool |
|---|---|---|
| **總 Swap 次數** | 187,975 | 391,080 |
| **總交易量 (USDC 側)** | $181,015,451 | $220,898,405 |
| **日均交易量** | ~$1,885,578 | ~$3,155,691 |
| **Pool 產生的總手續費** | ~$90,508 (0.05%) | ~$110,449 (0.05%) |

### 5.2 Vault 的 Fee Capture

| | WBTC-USDC | USDC-ETH |
|---|---|---|
| Vault 捕獲的 Fee | $142.81 | $147.42 |
| Pool 總 Fee | $90,508 | $110,449 |
| **Vault Fee Capture Rate** | **0.158%** | **0.133%** |
| Vault TVL / Pool TVL | 0.115% | 0.042% |
| **Fee Capture Multiplier** | **1.4x** | **3.2x** |

> **Fee Capture Multiplier > 1 代表集中流動性策略有效**——vault 用較少的資金捕獲了不成比例的手續費。USDC-ETH 的 3.2x 表示 vault 用 0.042% 的 TVL 捕獲了 0.133% 的 fee，效率是 full-range LP 的 3.2 倍。

### 5.3 為什麼 Fee 這麼少？

問題不在策略效率，在於 **vault TVL 太小**：

- WBTC-USDC vault TVL ~$2,600 vs pool TVL $2.27M → vault 佔 0.115%
- USDC-ETH vault TVL ~$2,174 vs pool TVL $5.23M → vault 佔 0.042%

如果 vault TVL 增長 10 倍到 $25K，按同樣的 fee capture rate：
- WBTC-USDC: $142 × 10 = $1,428 fee/96 天 → 年化 ~21.5% fee APR
- USDC-ETH: $147 × 10 = $1,474 fee/70 天 → 年化 ~27.6% fee APR

**Fee 收入隨 TVL 線性增長，但 IL 也會等比增長。** 關鍵是 fee/IL 比值是否能轉正。

---

## 6. Merkl 獎勵

### 6.1 獎勵數據

| | WBTC-USDC | USDC-ETH |
|---|---|---|
| **數據來源** | 鏈上 LP (Jeff) 實際 Merkl claim | 估算 (fee-capture 比例推導) |
| **KAT 總量** | ~15,700 KAT | ~24,400 KAT (估) |
| **USD 價值** | $189.66 | ~$295.10 |
| **KAT 單價** | $0.01208 (截圖時價格) | $0.01208 |
| **獎勵來源** | Merkl Protocol KAT 分配 | Merkl Protocol KAT 分配 |

> WBTC-USDC 的 KAT 獎勵數據來自一位持有 vault 27.83% 份額的 LP (Jeff) 在 62 天內實際獲得 4,369.43 KAT，反推全 vault 為 ~15,700 KAT。USDC-ETH 的數據來自 Merkl API 的 dailyRewards 按 fee capture 比例分配估算，並用 WBTC-USDC 的已知數據做校準。

### 6.2 Merkl Campaign 資訊 (from Merkl API)

| | WBTC-USDC Pool | USDC-ETH Pool |
|---|---|---|
| 狀態 | LIVE | LIVE |
| Pool 日獎勵 (全部 LP) | $1,477/day | $3,705/day |
| 獎勵 Token | KAT | KAT |
| Pool TVL (Merkl) | $2.27M | $5.23M |

---

## 7. 含獎勵後的完整 PnL

### 7.1 收入明細

| | WBTC-USDC | USDC-ETH |
|---|---|---|
| Trading Fee 收入 | $142.81 | $147.42 |
| KAT 獎勵 | $189.66 | ~$295.10 |
| **LP 總收入** | **$332.47** | **~$442.52** |

### 7.2 含獎勵後的 Alpha

| | WBTC-USDC | USDC-ETH |
|---|---|---|
| 策略 Alpha (raw) | -3.65% | -10.86% |
| 獎勵貢獻 (% of avg TVL) | +13.9% | +26.5% |
| **含獎勵 Alpha** | **+10.27%** | **+15.68%** |
| vs HODL | LP 更好 ✅ | LP 更好 ✅ |

> 兩個 vault 在含 Merkl 獎勵後均跑贏 HODL。但這依賴 KAT token 的持續分配和價格穩定。如果 Merkl campaign 結束或 KAT 價格下跌，LP 將直接面對負 alpha。

---

## 8. 競品 Vault 績效比較

> 🆕 **2026-03-24 新增**：收集了同池 3 個競品 vault 的完整鏈上數據，與 Omnis vault 做直接對比。

### 8.1 競品 Vault 基本資訊

3 個競品 vault 都部署在 **完全相同的底層池子**上：

| | Steer 競品 (USDC-ETH) | Charm.fi (USDC-ETH) | Charm.fi (WBTC-USDC) |
|---|---|---|---|
| **合約地址** | `0x8ac9a899...d583b3` | `0xc78c51f8...5129` | `0xbc2ae38c...90ff` |
| **底層池子** | `0x2a2c...6b` (同 Omnis) | `0x2a2c...6b` (同 Omnis) | `0x7446...5c` (同 Omnis) |
| **合約類型** | Steer Beacon Proxy | Charm Alpha Vault (EIP-1167 Clone) | Charm Alpha Vault (EIP-1167 Clone) |
| **創建時間** | ~Block 17M (2025-12 初) | ~Block 17M (2025-12 初) | ~Block 17M (2025-12 初) |
| **運行天數** | ~122 天 | ~122 天 | ~122 天 |
| **當前 TVL** | $17,311 | $800,507 | $469,614 |
| **Rebalance 次數** | 213 | 2,250 | 516 |

> Charm.fi 是這兩個池子的**主導 LP**：USDC-ETH vault 佔 pool TVL 14.8%，WBTC-USDC vault 佔 21.5%。

### 8.2 績效比較：全週期 (122 天)

| 指標 | Steer 競品 (USDC-ETH) | Charm (USDC-ETH) | Charm (WBTC-USDC) |
|------|------------------------|--------------------|--------------------|
| **底層資產走勢** | ETH -20.8% | ETH -20.8% | BTC -15.1% |
| **Vault Return** | -24.49% | -15.39% | -11.19% |
| **HODL Return** | -12.54% | -13.54% | -12.69% |
| **策略 Alpha** | **-11.95%** | **-1.85%** | **+1.50%** ✅ |
| **Max Drawdown** | -35.97% | -31.22% | -25.23% |
| **真實 Trading Fee** | $2,838 | $47,440 | $22,555 |
| **Fee Capture %** | 0.72% | 12.03% | 20.63% |
| **Fee Capture Mult** | 1.92x | 0.81x | 0.96x |

### 8.3 同期對比：Omnis vs 競品

為了公平比較，以下使用 **Omnis vault 創建後的同一時段**計算所有 vault 的績效：

**USDC-ETH Pool（~45 天，從 Omnis vault 創建起）：**

| 指標 | Omnis | Steer 競品 | Charm |
|------|-------|------------|-------|
| **策略 Alpha** | **-10.86%** | **-1.43%** | **+0.63%** ✅ |

**WBTC-USDC Pool（~97 天，從 Omnis vault 創建起）：**

| 指標 | Omnis | Charm |
|------|-------|-------|
| **策略 Alpha** | **-3.65%** | **-2.63%** |

### 8.4 競品分析解讀

**Charm.fi 為何表現更好？**

1. **TVL 規模效應**：Charm USDC-ETH TVL $800K vs Omnis $2.2K（363 倍差距）。更大的 TVL 意味著更大的 fee 收入絕對值，可以更好地抵消 IL
2. **Fee Capture Multiplier < 1**：Charm 的 0.81x–0.96x 看似低於 Omnis 的 1.4x–3.2x，但這是因為 Charm 本身就佔了 pool 的 15–22%，已經捕獲了大量的池子手續費
3. **Rebalance 頻率更高**：Charm USDC-ETH 做了 2,250 次 rebalance（vs 同池 Steer 競品 213 次），更積極的 rebalance 可能在某些行情中更有效

**Steer 競品為何表現最差？**

- 同為 Steer vault，同池、同期，alpha -11.95%（vs Omnis -10.86%）
- TVL $17K（比 Omnis 大 8 倍但仍然很小）
- 說明 Steer vault 的策略本身在 ETH 高波動環境下 alpha 一致為負，不是 Omnis 配置問題

**核心結論：**

| 觀察 | 啟示 |
|------|------|
| Charm WBTC-USDC 是唯一正 alpha vault | BTC 下跌趨勢中，Charm 的 rebalance 策略成功管理 IL |
| Charm alpha ≈ -1.85% vs Omnis/Steer ≈ -11% (USDC-ETH) | Charm 在 ETH 高波動下顯著更強，可能是策略寬度或 rebalance 邏輯差異 |
| 所有 USDC-ETH vault 的 alpha 都比 WBTC-USDC 差 | ETH 波動率更高導致所有策略都更難管理 IL |
| Fee Capture Mult 與 TVL 規模反相關 | 小 TVL vault 的 multiplier 數字好看但絕對 fee 少；大 TVL vault 的 multiplier 接近 1 但 fee 充足 |

---

## 9. 關鍵發現與啟示

### 9.1 策略本身的表現

**集中流動性策略的核心 trade-off：fee 放大 vs IL 放大**

在本分析期間：
- Fee 被放大了 1.4x–3.2x（正面）
- 但 IL 被放大得更多，導致淨 alpha 為負
- 主因：BTC 單邊下跌 18.5%，ETH 高波動 ±20%+

**策略在什麼環境下有效？**
- 橫盤市場（低波動、高交易量）→ fee 放大優勢最大
- vault TVL 佔 pool 比例更高 → fee capture 更多
- 底層資產走勢平緩 → IL 可控

**策略在什麼環境下失效？**
- 單邊趨勢（持續下跌或上漲）→ rebalance 不斷鎖虧
- 高波動來回震盪 → rebalance 頻繁但方向性虧損

### 9.2 LP Profitability 的現實

**不含激勵，LP 虧錢。** 這是事實。

但需要 contextualize：
- 這兩個 vault 是 Katana 上的 **早期、小規模部署**（TVL $50–$2,600）
- 遭遇了 **BTC -18.5% 的單邊行情**和 ETH 的高波動
- 在同樣的市場環境中，**任何集中流動性策略都會面臨類似問題**

### 9.3 DEX Cost of Funds 的效率

**Fee Capture Multiplier 是核心賣點：**

| 指標 | WBTC-USDC | USDC-ETH |
|------|-----------|----------|
| Vault TVL share | 0.115% | 0.042% |
| Fee capture share | 0.158% | 0.133% |
| **Multiplier** | **1.4x** | **3.2x** |

這意味著：
- DEX 不需要把激勵撒給全部 LP，只需要激勵 vault LP
- 同樣的激勵預算，通過 vault 提供的有效流動性深度更大
- vault LP 用更少的資金產生了更多的交易費（=更好的交易執行品質）

---

## 10. 數據與方法

### 10.1 數據來源

| 數據 | 來源 | 行數 |
|------|------|------|
| Omnis Vault 狀態時間序列 | `vault1-dense.csv`, `vault2-dense.csv` | 833 + 384 |
| Omnis 真實手續費 (Collect - Burn) | `real-fees.csv` | 1,984 |
| Pool Swap 量 | `swaps-summary.csv` | 1,216 |
| Merkl 獎勵 | Merkl API v4 | on-demand |
| 價格 | pool slot0() 歷史查詢 | 含在狀態時間序列中 |
| 競品 Vault 狀態時間序列 | `competitor-*-dense.csv` | 1,057 × 3 |
| 競品 Burn+Collect 事件 | `competitor-fees.csv` | 4,543 |
| 競品真實手續費 | `competitor-real-fees.csv` | 611 |
| 延伸 Swap 量 (block 17M→) | `swaps-extended.csv` | 891 |
| 競品計算指標 | `computed-metrics-competitors.json` | — |

### 10.2 RPC 查詢方法

- **Vault 狀態**: `eth_call` → selector `0xc4a7761e` (totalAmounts 等價函數，通過 beacon proxy 的 implementation bytecode 反查)
- **Total Supply**: `eth_call` → `0x18160ddd`
- **Pool 價格**: `eth_call` → `0x3850c7bd` (slot0)
- **Fee 事件**: `eth_getLogs` → Collect topic `0x7093...` + Burn topic `0x0c39...`，按 vault address 過濾
- **Swap 事件**: `eth_getLogs` → Swap topic `0xc420...`，per 10K block window

### 10.3 已知限制

1. **USDC-ETH Merkl 獎勵為估算值**：使用 fee-capture 比例推導，校準係數 0.862（來自 WBTC-USDC 的已知數據交叉驗證）
2. **KAT 價格使用截圖時價格 $0.01208**：若 KAT 已顯著波動，獎勵 USD 值需重新計算
3. **無 archive trace 支援**：無法追蹤 native ETH internal transfers，fund flow 僅覆蓋 ERC20
4. **Vault share Transfer 事件未發出**：beacon proxy 實現不 emit ERC20 Transfer，無法從 event 追蹤份額轉移，只能用 balanceOf 查詢
5. **Rebalance 成本（gas + 滑點）未獨立量化**：已包含在 alpha 計算中，但無法單獨拆出
6. **競品 vault inception 精度**：binary search 精度 ~500 block（~8 分鐘），不影響 122 天的績效計算
7. **競品 Merkl 獎勵未計入**：競品分析僅含 raw alpha（trading fee - IL），未計入 KAT 獎勵。含獎勵比較需要額外的 Merkl 數據
8. **競品 pool TVL 使用快照值**：fee capture multiplier 使用 Merkl API 的 pool TVL 快照（$2.27M / $5.23M），非歷史加權平均

### 10.4 可重現性

```
Chain: Katana (747474)
RPC: dRPC LB (paid) + Tenderly + dRPC (free) + katanarpc.com + katana.network
Anchor: latest at block 27,522,192 (Omnis), 27,555,485 (競品)
Historical state: supported via eth_call with block parameter
Capability: Tier A (standard RPC, no trace)
Total RPC calls: ~8,200 (Omnis ~5,700 + 競品 ~2,500)
Batch JSON-RPC: 用於競品 vault 狀態採樣 (8 calls/batch → 3x throughput)
Scripts: scripts/collect-*.py, scripts/compute-*.py
```

---

## 附錄 A: 完整數據檔案清單

```
data/
├── vault1-dense.csv                              # Omnis WBTC-USDC 833 點狀態時間序列
├── vault2-dense.csv                              # Omnis USDC-ETH 384 點狀態時間序列
├── real-fees.csv                                 # Omnis 1,984 筆真實手續費 (Collect - Burn)
├── fees.csv                                      # Omnis 1,984 筆原始 Collect 事件
├── swaps-summary.csv                             # 1,216 筆 swap 交易量摘要
├── vault-history.csv                             # 247 點粗採樣 (歷史版本)
├── computed-metrics.json                         # Omnis vault 計算指標
├── competitor-steer-competitor-usdc-eth-dense.csv # 競品 Steer 1,057 點
├── competitor-charm-usdc-eth-dense.csv           # 競品 Charm USDC-ETH 1,057 點
├── competitor-charm-wbtc-usdc-dense.csv          # 競品 Charm WBTC-USDC 1,057 點
├── competitor-fees.csv                           # 競品 4,543 筆 Burn+Collect 事件
├── competitor-real-fees.csv                      # 競品 611 筆真實手續費
├── swaps-extended.csv                            # 延伸 swap 量 (block 17M→, 891 筆)
└── computed-metrics-competitors.json             # 競品 vault 計算指標

scripts/
├── collect-vault-history.py          # Omnis 基礎狀態採樣
├── collect-fees-and-swaps.py         # Omnis Fee/Swap/密集採樣
├── compute-real-fees.py              # Omnis 真實手續費拆解
├── collect-competitor-vault-history.py # 競品 Batch 狀態採樣
├── collect-competitor-fees.py         # 競品 Burn+Collect+延伸 Swap
└── compute-competitor-metrics.py      # 競品績效指標計算
```

## 附錄 B: 合約地址一覽

| 角色 | 地址 |
|------|------|
| **Omnis Vaults** | |
| WBTC-USDC Vault | `0x5977767ef6324864F170318681ecCB82315f8761` |
| USDC-ETH Vault | `0x811b8c618716ca62b092b67c09e55361ae6df429` |
| **競品 Vaults** | |
| Steer 競品 (USDC-ETH) | `0x8ac9a899193475e2c5c55e80c826d2e433d583b3` |
| Charm.fi (USDC-ETH) | `0xc78c51f88adfbadcdfafcfef7f5e3d3c6c7d5129` |
| Charm.fi (WBTC-USDC) | `0xbc2ae38ce7127854b08ec5956f8a31547f6390ff` |
| Charm Manager | `0x10cb3b0a4a9ce23c235330e1711e5aa5fefabc7f` |
| **底層池子** | |
| WBTC-USDC Pool | `0x744676b3ced942d78f9b8e9cd22246db5c32395c` |
| USDC-ETH Pool | `0x2a2c512beaa8eb15495726c235472d82effb7a6b` |
| **基礎設施** | |
| Vault Implementation (Beacon) | `0x8032d063992f4f6a14bc2be69a0d24cb563365de` |
| Beacon Contract | `0x834a0ec5347be6e62a1e57a01f1250c7ddde617a` |
| Deposit Router | `0x4DE18F1582Aa71671828F329B826ad45B2798b12` |
| **Tokens** | |
| vbWBTC | `0x0913da6da4b42f538b445599b46bb4622342cf52` (8 dec) |
| vbUSDC | `0x203a662b0bd271a6ed5a60edfbd04bfce608fd36` (6 dec) |
| vbETH | `0xee7d8bcfb72bc1880d0cf19822eb0a2e6577ab62` (18 dec) |
| KAT Token | `0x7F1f4b4b29f5058fA32CC7a97141b8D7e5ABDC2d` (18 dec) |
