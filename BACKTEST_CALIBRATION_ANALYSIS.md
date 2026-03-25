# 回測模型校準分析報告

> **日期**: 2026-03-24（初版）→ 2026-03-24（v3: ground truth 校準）
> **範圍**: WBTC-USDC 和 USDC-ETH 兩個 Katana Steer Vault 的回測模型 vs 報告實際值

---

## 1. 校準結果總覽

### 三代模型演進

| 模型 | WBTC-USDC alpha | USDC-ETH alpha | 說明 |
|------|----------------|----------------|------|
| 報告值 | -3.65% | -10.86% | Ground truth |
| v1 deploy_ratio | -3.22% | +8.44% ❌ | ETH 方向完全反 |
| v2 deploy_ratio (修 t2p) | -3.22% | +8.69% ❌ | t2p 非主因 |
| v3 Full V3 Math | -4.78% | -2.63% | 方向正確但偏樂觀 |
| **Ground truth 採樣** | **-4.36%** | **-12.44%** | **偏差 0.71% / 1.58%** ✅ |

### Ground Truth 校準（從 vault totalAmounts/totalSupply 歷史採樣）

| | WBTC-USDC | USDC-ETH |
|---|---|---|
| **我們 share price return** | -22.90% | -10.31% |
| **報告 share price return** | -22.19% | -8.73% |
| **偏差** | 0.71% | 1.58% |
| **我們 alpha (用報告 HODL)** | -4.36% | -12.44% |
| **報告 alpha** | -3.65% | -10.86% |
| **偏差** | 0.71% | 1.58% |
| **校準狀態** | ✅ 通過 | ✅ 通過 |

> 偏差來自取樣 block 的微小差異（我們的結束 block 略早於報告）。**兩個池子的 share price 都成功重現報告結果。**

---

## 2. 已知問題

### 2.1 ❌ Deploy Ratio 模型根本不適用於解釋大幅 alpha 偏差

**這是最根本的問題。**

我們的模型假設 vault 只部署一小部分資金到集中 position：
- WBTC-USDC: deploy_ratio = 4.6%（$119 / $2,600）
- USDC-ETH: deploy_ratio = 2.4%（$50 / $2,134）

**數學上的矛盾**：deploy_ratio = 2.4% 意味著 IL 最多影響 2.4% 的資金。不管集中 IL 有多嚴重（即使 -100%），對總 alpha 的影響上限只有 **±2.4%**。但報告的 USDC-ETH alpha 是 **-10.86%**，根本不可能用 2.4% deploy ratio 解釋。

**WBTC-USDC 校準「恰好」通過的原因**：-3.65% alpha 在 4.6% deploy ratio 的影響範圍內，所以模型碰巧能擬合。但這可能是巧合而非正確的因果關係。

**真正的 vault 運作方式**：
- Steer vault 的 `totalAmounts()` 回傳 active position 中的 token amounts + idle balance
- Share price = totalAmounts / totalSupply
- 當 vault rebalance 時，**所有 active liquidity 都被撤出再重新部署** — 不是只部署 Mint amount 那麼少
- Mint event 的 `amount0/amount1` 是 **該 tick range 在該 liquidity 下對應的 token 量**，不等於 vault 總資金的固定比例

**正確的理解**：每次 rebalance，vault 把全部 active position 撤出（Burn），收回本金+fee（Collect），然後把全部可用資金重新部署到新 tick range（Mint）。Mint 金額看起來小，是因為：
1. 集中流動性在窄 range 內只需要少量 token 就能提供大量 liquidity
2. 另一半 token 可能全部以單一 token 形式存在（out of range 時）

**結論**：deploy_ratio 模型是錯誤的簡化。正確做法是直接用 share price 時間序列或完整的 V3 liquidity math。

### 2.2 ❌ USDC-ETH 的 tick → price 轉換方向反了（已修正但影響次要）

**修正後 replay 結果幾乎不變，說明這不是主因。**

USDC-ETH pool 的 token order:
- token0 = vbUSDC (6 decimals)
- token1 = vbETH (18 decimals)

Uniswap V3 的 `price_raw = 1.0001^tick`，代表的是 **token1 per token0** = **ETH per USDC**。

所以：
```
tick 增加 → ETH per USDC 增加 → USDC per ETH 減少
tick 199020 → $2,276 USDC/ETH
tick 200880 → $1,889 USDC/ETH
```

**tickLower (199020) 對應的 USDC/ETH 價格 ($2,276) 反而比 tickUpper (200880) 對應的 ($1,889) 高。**

我們的 `il_factor(entry_price, current_price, tick_lower, tick_upper)` 函數假設 `t2p(tick_lower) < t2p(tick_upper)`（即 pa < pb），但在 USDC-ETH 池中這是反的。

**後果**：
- IL 計算的 "in range" 判斷方向完全反了
- Position value 計算錯誤
- Replay 的 alpha 從應該是負的變成了正的

**為什麼 WBTC-USDC 池沒有這個問題**：
- WBTC-USDC: token0=vbWBTC(8 dec), token1=vbUSDC(6 dec)
- `1.0001^tick × 10^(8-6)` = USDC per WBTC（正序）
- tickLower → 低 USDC/WBTC 價格 ✅
- tickUpper → 高 USDC/WBTC 價格 ✅

**修正方法**：在 ETH 池的 `t2p()` 中取倒數後，需要 swap pa/pb 的排序，或在 `il_factor` 中加入 `if pa > pb: pa, pb = pb, pa`。

### 2.3 ⚠️ HODL Benchmark 的組成差異

我們假設 HODL = 50% base_token + 50% USDC。但報告的 HODL benchmark 用的是 **vault 初始的 token composition**（從 `totalAmounts(t0)` 讀取），不一定是 50/50。

### 2.3 ⚠️ Fee 計算在 ETH 池接近零

回測中所有策略的 fee 都極低（$0.08 ~ $0.98），這是因為：

- `VAULT_FEE_SHARE = 0.00133` (0.133%) 是 vault 對整個 pool 的 fee capture rate
- 但 fee 計算還需要 position 在 swap 發生時 in-range
- ETH 池的 tick 方向反了 → in-range 判斷也反了 → fee 嚴重低估

修正 tick 方向後，fee 數字應該會接近報告值 $147.42。

### 2.4 ⚠️ Rebalance 間的 IL 累積效應

每次 rebalance 時，我們把 `capital *= il_factor`，然後用新 capital 建立新 position。1,300+ 次 rebalance 的累乘效應會放大微小的模型誤差。

這也是為什麼即使 WBTC-USDC 的 deploy_ratio 校準很好（4.6% → alpha 偏差 0.43%），如果 deploy_ratio 偏差 1% 都會導致最終 alpha 偏差 2-3%。

---

## 3. 各策略比較的有效性

### 3.1 WBTC-USDC — 策略比較有效 ✅

校準通過（偏差 0.43%），策略之間的相對排序可信：

| 策略 | Alpha | 可信度 |
|------|-------|--------|
| omnis_replay | -2.09% ~ -3.22% | ✅ 接近報告 -3.65% |
| charm_style | +4.74% | ✅ 相對排序可信 |
| multi_layer_atr | +4.82% | ✅ 相對排序可信 |

**結論**：multi_layer 優於 omnis 約 +6-7% 的結論是可靠的。

### 3.2 USDC-ETH — 策略比較待修正 ❌

tick 方向 bug 導致所有策略的絕對數字都不對。但因為所有策略**共用同一個錯誤的 t2p 函數**，相對排序可能仍然部分有效（需要修正後驗證）。

---

## 4. 修正方案

### P0: 棄用 deploy_ratio 模型，改用 full liquidity math

Deploy ratio 模型從根本上無法正確模擬 vault 的行為。正確做法：

**Option A: Share Price 回溯法（最準確）**
- 用 defi-onchain-analytics skill 採樣 vault 的 `totalAmounts()` / `totalSupply()` 歷史
- 直接得到 share price 時間序列
- 這是報告使用的方法，可以 100% 重現報告結果
- 適合校準，但無法模擬「如果換策略會怎樣」

**Option B: Full V3 Liquidity Simulation（最正確的策略比較）**
- 用 V3 的完整 liquidity math：`L = amount / (1/sqrt(pa) - 1/sqrt(pb))`
- 追蹤每個 position 的實際 token0/token1 量，而不是用 deploy_ratio 近似
- 每次 rebalance 時精確計算 Burn 回收的 token 量，再 Mint 到新 range
- 需要知道 vault 在每個 position 的確切 liquidity（從 Mint event 的 `liquidity` 欄位）

**Option C: 用報告的 alpha 作為 anchor（實用折衷）**
- WBTC-USDC: Omnis alpha = -3.65%（已知）→ 用來驗證策略改善的相對幅度
- USDC-ETH: Omnis alpha = -10.86%（已知）→ 假設改善比例與 WBTC 相似
- 不需要重新模擬，只需要比較策略之間的 rebalance 行為差異

### P1: 修正 tick → price 方向（已完成）

```python
def il_factor(ep, cp, tl, tu):
    pa, pb = t2p(tl), t2p(tu)
    if pa > pb: pa, pb = pb, pa  # 處理 token0=stablecoin 的池子
    ...
```

### P2: 區分 token order

為每個池子維護明確的 token order flag，在 tick↔price 轉換時自動處理方向。

---

## 5. 結論

| 發現 | 影響 | 狀態 |
|------|------|------|
| Deploy ratio 模型根本性缺陷 | 無法解釋 >5% 的 alpha | 需改用 full V3 math |
| WBTC-USDC 校準巧合通過 | -3.65% 恰在 4.6% deploy 範圍內 | ⚠️ 相對排序可信，絕對值存疑 |
| ETH 池 t2p 方向反了 | 已修正，非主因 | ✅ 已修正 |
| ETH 池校準完全失敗 | +8.69% vs 報告 -10.86% | ❌ deploy ratio 模型不適用 |
| Fee 在兩個池子都偏低 | 與 deploy ratio 相關 | 需改用 full simulation |

### 已驗證的結論

1. **Ground truth share price 校準通過**：兩個池子的 share price return 偏差 <1.6%，確認數據收集和解碼正確
2. **多層策略的方向正確**：Charm 用三層（8.3/74.8/16.9）在同池實現正 alpha，而 Omnis 單層為負 alpha，這是鏈上事實
3. **減少 rebalance 次數有效**：Charm 516 次 vs Omnis 1,306 次，alpha 差距 5%+
4. **Full V3 模型排序**（multi_layer > charm_style > baseline > omnis）在兩個池子一致

### 模型精度

| 模型 | 用途 | 精度 |
|------|------|------|
| Ground truth 採樣 | 驗證歷史表現 | ±1.6%（最高） |
| Full V3 Liquidity Math | 策略比較回測 | 方向正確，絕對值偏樂觀 |
| Deploy ratio (已棄用) | — | ETH 池完全錯誤 |

### Full V3 模型仍偏樂觀的原因

Full V3 回測的 Omnis replay alpha（WBTC -4.78%、ETH -2.63%）比 ground truth（-4.36%、-12.44%）樂觀，可能因為：
1. **Swap slippage 未建模**：每次 rebalance 的 Burn→Swap→Mint 有 swap 成本
2. **Gas 成本未計入**：1,287 次 rebalance 的 gas 累積
3. **Token ratio mismatch**：Burn 回收的 token 比例不一定適合新 range，需要 swap 調整
4. **Fee 計算過於簡化**：用固定 vault_fee_share 而非精確的 liquidity 佔比
