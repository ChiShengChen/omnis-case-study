#!/usr/bin/env python3
"""
CLAMM Vault Backtest v2 — 用真實鏈上數據回測
=============================================
改進：
  - Omnis 實際操作重放（1,287 次 rebalance）
  - Charm 實際操作重放（101 次 × 3 positions）
  - 校準 IL 模型：用 share-price 方法而非 position-value 方法
  - 多層策略模擬（對應 atr_strategy.py 的 generate_multi_layer_prediction）

數據來源：case_study/data/ (由 defi-onchain-analytics skill 收集)
  - price_series.csv: 4,157 個價格採樣點 (每 2000 block)
  - swaps.csv: 187,975 筆 swap 事件
  - burns.csv: 14,482 筆 Burn 事件
  - mints.csv: 15,427 筆 Mint 事件
"""

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import numpy as np

DATA_DIR = Path(__file__).parent / "data"

TOKEN0_DECIMALS = 8   # vbWBTC
TOKEN1_DECIMALS = 6   # vbUSDC
POOL_FEE_RATE = 0.0005
TICK_SPACING = 10

OMNIS_VAULT = "0x5977767ef6324864f170318681eccb82315f8761"
CHARM_VAULT = "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff"

# 報告校準值
REPORT_OMNIS_ALPHA = -3.65
REPORT_CHARM_ALPHA = 1.50
REPORT_OMNIS_FEE = 142.81
INITIAL_CAPITAL = 2600.0


# ─── 工具函數 ────────────────────────────────────────────────────────────────

def tick_to_price(tick: int) -> float:
    if tick <= -887270:
        return 0.01
    if tick >= 887270:
        return 1e12
    return (1.0001 ** tick) * (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))

def price_to_tick(price: float) -> int:
    raw = price / (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))
    if raw <= 0:
        return -887270
    return int(math.floor(math.log(raw) / math.log(1.0001)))

def align_tick(tick: int) -> int:
    return (tick // TICK_SPACING) * TICK_SPACING


# ─── 數據結構 ────────────────────────────────────────────────────────────────

@dataclass
class PricePoint:
    block: int
    tick: int
    price: float

@dataclass
class SwapEvent:
    block: int
    amount0: int
    amount1: int
    liquidity: int
    tick: int
    price: float

@dataclass
class VaultPosition:
    """一個或多個集中流動性 position 的集合"""
    ranges: List[Tuple[int, int, float]]  # [(tickLower, tickUpper, weight), ...]
    entry_block: int
    entry_price: float
    capital: float


# ─── 數據載入 ────────────────────────────────────────────────────────────────

def load_prices() -> List[PricePoint]:
    pts = []
    with open(DATA_DIR / "price_series.csv") as f:
        for row in csv.DictReader(f):
            pts.append(PricePoint(int(row["block"]), int(row["tick"]), float(row["price"])))
    pts.sort(key=lambda p: p.block)
    return pts

def load_swaps() -> List[SwapEvent]:
    swaps = []
    with open(DATA_DIR / "swaps.csv") as f:
        for row in csv.DictReader(f):
            swaps.append(SwapEvent(
                int(row["block"]), int(row["amount0"]), int(row["amount1"]),
                int(row["liquidity"]), int(row["tick"]), float(row["price"])))
    swaps.sort(key=lambda s: s.block)
    return swaps

def load_rebalance_history(vault: str) -> List[Dict]:
    """從 burns + mints 重建 vault 的 rebalance 歷史（支持多 position）"""
    vault = vault.lower()
    tx_burns, tx_mints = {}, {}

    with open(DATA_DIR / "burns.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == vault:
                tx_burns.setdefault(row["tx_hash"], []).append(row)
    with open(DATA_DIR / "mints.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == vault:
                tx_mints.setdefault(row["tx_hash"], []).append(row)

    rebalances = []
    for tx in sorted(set(tx_burns) & set(tx_mints), key=lambda t: int(tx_mints[t][0]["block"])):
        mints = tx_mints[tx]
        block = int(mints[0]["block"])
        positions = []
        for m in mints:
            positions.append((int(m["tickLower"]), int(m["tickUpper"])))
        rebalances.append({"block": block, "tx": tx, "positions": positions})

    return rebalances


# ─── IL 模型（改進版）────────────────────────────────────────────────────────

def concentrated_il_factor(entry_price: float, current_price: float,
                            tick_lower: int, tick_upper: int) -> float:
    """
    計算集中流動性的 value ratio: current_value / entry_value

    使用 Uniswap V3 公式：
    - 在區間內：混合 token0 + token1
    - 低於下界：全部 token0（跟隨價格下跌）
    - 高於上界：全部 token1（保持 USDC 面值）
    """
    p_a = tick_to_price(tick_lower)
    p_b = tick_to_price(tick_upper)

    if p_a <= 0 or p_b <= p_a:
        return 1.0  # 無效區間

    # clamp entry price 到區間
    pe = max(p_a, min(p_b, entry_price))
    pc = current_price

    sqrt_a, sqrt_b, sqrt_e = math.sqrt(p_a), math.sqrt(p_b), math.sqrt(pe)

    # 入場時的虛擬 token 量（L=1 歸一化）
    x_e = 1.0 / sqrt_e - 1.0 / sqrt_b
    y_e = sqrt_e - sqrt_a
    val_entry = x_e * pe + y_e

    if val_entry <= 0:
        return 1.0

    # 當前的虛擬 token 量
    if pc <= p_a:
        x_c = 1.0 / sqrt_a - 1.0 / sqrt_b
        y_c = 0.0
    elif pc >= p_b:
        x_c = 0.0
        y_c = sqrt_b - sqrt_a
    else:
        sqrt_c = math.sqrt(pc)
        x_c = 1.0 / sqrt_c - 1.0 / sqrt_b
        y_c = sqrt_c - sqrt_a

    val_now = x_c * pc + y_c
    return val_now / val_entry


def multi_position_value(positions: List[Tuple[int, int, float]],
                          entry_price: float, current_price: float,
                          capital: float) -> float:
    """計算多個 position（帶 weight）的加權價值"""
    total = 0.0
    for tick_lower, tick_upper, weight in positions:
        ratio = concentrated_il_factor(entry_price, current_price, tick_lower, tick_upper)
        total += capital * weight * ratio
    return total


# ─── Fee 計算 ────────────────────────────────────────────────────────────────

def fee_for_swap(swap: SwapEvent, positions: List[Tuple[int, int, float]],
                 vault_fee_share: float) -> float:
    """計算一筆 swap 對多 position 組合的 fee 收入"""
    volume_usd = abs(swap.amount1) / (10 ** TOKEN1_DECIMALS)
    total_fee = 0.0
    for tick_lower, tick_upper, weight in positions:
        if tick_lower <= swap.tick < tick_upper:
            total_fee += volume_usd * POOL_FEE_RATE * vault_fee_share * weight
    return total_fee


# ─── 回測主迴圈 ──────────────────────────────────────────────────────────────

def run_replay(name: str, rebalances: List[Dict], prices: List[PricePoint],
               swaps: List[SwapEvent], vault_fee_share: float,
               deploy_ratio: float = 1.0,
               default_weight: float = 1.0) -> Dict:
    """
    重放實際 vault 操作

    deploy_ratio: vault 部署到集中區間的資金比例
      - Omnis: 只部署 ~$119/$2600 ≈ 4.6% 到集中區間
      - Charm: 部署比例更高（三層合計覆蓋大部分資金）
      - 未部署的部分以 50/50 WBTC/USDC idle balance 保持（跟 HODL 同等 IL）
    """
    capital = INITIAL_CAPITAL
    init_price = prices[0].price
    fee_total = 0.0
    rb_idx = 0
    swap_idx = 0
    pos = None
    values = []
    max_val = capital
    max_dd = 0.0

    for pp in prices:
        while rb_idx < len(rebalances) and rebalances[rb_idx]["block"] <= pp.block:
            rb = rebalances[rb_idx]
            if pos:
                # 部署部分的價值 = IL affected
                deployed_val = multi_position_value(
                    pos.ranges, pos.entry_price, pp.price,
                    pos.capital * deploy_ratio)
                # 未部署部分 = HODL (50/50 BTC/USDC)
                idle_val = pos.capital * (1 - deploy_ratio) * (
                    0.5 * (pp.price / pos.entry_price) + 0.5)
                capital = deployed_val + idle_val + fee_total
                fee_total = 0.0

            tick_positions = rb["positions"]
            n = len(tick_positions)
            if n == 1:
                ranges = [(tick_positions[0][0], tick_positions[0][1], default_weight)]
            else:
                weights = [0.30, 0.35, 0.35] if n == 3 else [1.0 / n] * n
                ranges = [(tp[0], tp[1], w) for tp, w in zip(tick_positions, weights)]

            pos = VaultPosition(ranges=ranges, entry_block=pp.block,
                                entry_price=pp.price, capital=capital)
            rb_idx += 1

        if pos:
            while swap_idx < len(swaps) and swaps[swap_idx].block <= pp.block:
                fee_total += fee_for_swap(swaps[swap_idx], pos.ranges, vault_fee_share)
                swap_idx += 1

        if pos:
            deployed_val = multi_position_value(
                pos.ranges, pos.entry_price, pp.price,
                pos.capital * deploy_ratio)
            idle_val = pos.capital * (1 - deploy_ratio) * (
                0.5 * (pp.price / pos.entry_price) + 0.5)
            cur_val = deployed_val + idle_val + fee_total
        else:
            cur_val = capital

        values.append((pp.block, cur_val))
        max_val = max(max_val, cur_val)
        dd = (max_val - cur_val) / max_val if max_val > 0 else 0
        max_dd = max(max_dd, dd)

    final = values[-1][1] if values else capital
    hodl = INITIAL_CAPITAL * (0.5 * (prices[-1].price / init_price) + 0.5)
    ret = (final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    hodl_ret = (hodl - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    return {
        "name": name,
        "return": ret,
        "hodl_return": hodl_ret,
        "alpha": ret - hodl_ret,
        "fee": fee_total,
        "rebalances": len(rebalances),
        "max_dd": max_dd * 100,
        "final_value": final,
        "values": values,
        "deploy_ratio": deploy_ratio,
    }


def run_simulated(name: str, prices: List[PricePoint], swaps: List[SwapEvent],
                  vault_fee_share: float,
                  make_ranges_fn, should_rebalance_fn,
                  deploy_ratio: float = 1.0) -> Dict:
    """模擬策略回測"""
    capital = INITIAL_CAPITAL
    init_price = prices[0].price
    fee_total = 0.0
    swap_idx = 0
    pos = None
    rebalance_count = 0
    values = []
    max_val = capital
    max_dd = 0.0
    price_history = []

    for pp in prices:
        price_history.append(pp)

        if should_rebalance_fn(pp, pos, price_history):
            if pos:
                deployed_val = multi_position_value(
                    pos.ranges, pos.entry_price, pp.price,
                    pos.capital * deploy_ratio)
                idle_val = pos.capital * (1 - deploy_ratio) * (
                    0.5 * (pp.price / pos.entry_price) + 0.5)
                capital = deployed_val + idle_val + fee_total
                fee_total = 0.0

            ranges = make_ranges_fn(pp, price_history)
            pos = VaultPosition(ranges=ranges, entry_block=pp.block,
                                entry_price=pp.price, capital=capital)
            rebalance_count += 1

        if pos:
            while swap_idx < len(swaps) and swaps[swap_idx].block <= pp.block:
                fee_total += fee_for_swap(swaps[swap_idx], pos.ranges, vault_fee_share)
                swap_idx += 1

        if pos:
            deployed_val = multi_position_value(
                pos.ranges, pos.entry_price, pp.price,
                pos.capital * deploy_ratio)
            idle_val = pos.capital * (1 - deploy_ratio) * (
                0.5 * (pp.price / pos.entry_price) + 0.5)
            cur_val = deployed_val + idle_val + fee_total
        else:
            cur_val = capital

        values.append((pp.block, cur_val))
        max_val = max(max_val, cur_val)
        dd = (max_val - cur_val) / max_val if max_val > 0 else 0
        max_dd = max(max_dd, dd)

    final = values[-1][1] if values else capital
    hodl = INITIAL_CAPITAL * (0.5 * (prices[-1].price / init_price) + 0.5)
    ret = (final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    hodl_ret = (hodl - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    return {
        "name": name,
        "return": ret,
        "hodl_return": hodl_ret,
        "alpha": ret - hodl_ret,
        "fee": fee_total,
        "rebalances": rebalance_count,
        "max_dd": max_dd * 100,
        "final_value": final,
        "values": values,
        "deploy_ratio": deploy_ratio,
    }


# ─── 策略定義 ────────────────────────────────────────────────────────────────

def compute_atr(price_history: List[PricePoint], period: int = 14) -> float:
    if len(price_history) < period + 1:
        return price_history[-1].price * 0.05
    recent = price_history[-(period + 1):]
    trs = []
    for i in range(1, len(recent)):
        h = max(recent[i].price, recent[i-1].price) * 1.005
        l = min(recent[i].price, recent[i-1].price) * 0.995
        tr = max(h - l, abs(h - recent[i-1].price), abs(l - recent[i-1].price))
        trs.append(tr)
    return sum(trs[-period:]) / period if trs else recent[-1].price * 0.05

def compute_trend(price_history: List[PricePoint], lookback: int = 20) -> float:
    """回傳 -1 ~ +1 的趨勢方向"""
    if len(price_history) < lookback:
        return 0.0
    ret = (price_history[-1].price - price_history[-lookback].price) / price_history[-lookback].price
    return max(-1.0, min(1.0, ret / 0.20))


# 策略 1: baseline ATR（模擬現行 Omnis 策略）
def baseline_ranges(pp, history):
    atr = compute_atr(history)
    if atr <= 0: atr = pp.price * 0.05
    lo = pp.price - atr * 2.0
    hi = pp.price + atr * 2.0
    return [(align_tick(price_to_tick(max(1, lo))), align_tick(price_to_tick(hi)), 1.0)]

def baseline_should_rebalance(pp, pos, history):
    if pos is None: return True
    return (pp.block - pos.entry_block) >= 6000  # ~每 6000 block


# 策略 2: 多層 ATR（對應 generate_multi_layer_prediction）
def multi_layer_ranges(pp, history):
    atr = compute_atr(history)
    if atr <= 0: atr = pp.price * 0.05
    trend = compute_trend(history)

    # Layer 1: full-range
    l1 = (align_tick(-887270), align_tick(887270), 0.30)

    # Layer 2: 寬區間 ATR×4
    lo2 = max(1, pp.price - atr * 4.0)
    hi2 = pp.price + atr * 4.0
    l2 = (align_tick(price_to_tick(lo2)), align_tick(price_to_tick(hi2)), 0.35)

    # Layer 3: 窄區間 ATR×1.5 + 趨勢偏移
    if trend < -0.2:
        lo3 = pp.price - atr * 1.5 * 1.4
        hi3 = pp.price + atr * 1.5 * 0.6
    elif trend > 0.2:
        lo3 = pp.price - atr * 1.5 * 0.6
        hi3 = pp.price + atr * 1.5 * 1.4
    else:
        lo3 = pp.price - atr * 1.5
        hi3 = pp.price + atr * 1.5
    l3 = (align_tick(price_to_tick(max(1, lo3))), align_tick(price_to_tick(hi3)), 0.35)

    return [l1, l2, l3]

def multi_layer_should_rebalance(pp, pos, history):
    if pos is None: return True
    if (pp.block - pos.entry_block) < 5000: return False
    # 只看 Layer 3 (窄區間) 是否出界
    if len(pos.ranges) >= 3:
        tl, tu, _ = pos.ranges[2]  # Layer 3
    else:
        tl, tu, _ = pos.ranges[0]
    p_lo = tick_to_price(tl)
    p_hi = tick_to_price(tu)
    if pp.price < p_lo or pp.price > p_hi:
        return True
    rng = p_hi - p_lo
    if rng > 0:
        pct = (pp.price - p_lo) / rng
        if pct < 0.1 or pct > 0.9:
            return True
    return False


# ─── 主程序 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 75)
    print("CLAMM Vault Backtest v2 — Real On-Chain Data (Katana WBTC-USDC)")
    print("=" * 75)

    # 載入數據
    print("\n📂 Loading on-chain data...")
    prices = load_prices()
    swaps = load_swaps()
    print(f"   Price points: {len(prices)} (block {prices[0].block}→{prices[-1].block})")
    print(f"   Swaps: {len(swaps)}")
    print(f"   Price: ${prices[0].price:,.0f} → ${prices[-1].price:,.0f} ({(prices[-1].price/prices[0].price-1)*100:+.1f}%)")

    omnis_rb = load_rebalance_history(OMNIS_VAULT)
    charm_rb = load_rebalance_history(CHARM_VAULT)
    print(f"   Omnis rebalances: {len(omnis_rb)}")
    print(f"   Charm rebalances: {len(charm_rb)} (× 3 positions each)")

    # Fee share 校準
    # Pool 總 fee = $90,508，Omnis 捕獲 $142.81 = 0.158% share
    # 但 0.158% 是最終結果（含 in-range 比例），不是每筆 swap 的固定 share
    # 使用 0.158% 作為 base，模擬時 in-range 判斷會自動區分不同策略的 capture 差異
    vault_fee_share = 0.00158
    print(f"\n📐 Vault fee share: {vault_fee_share*100:.3f}% (report calibrated)")

    # ── 回測 ──
    results = []

    # Deploy ratios（從鏈上 Mint 金額 vs vault TVL 推算）
    # Omnis: ~$119 deployed / $2,600 TVL ≈ 4.6%
    # Charm: TVL $469K, fee capture 20.63% of pool → 部署比例高
    #        報告: fee $22,555 / pool fee $90,508 = 24.9% share
    OMNIS_DEPLOY = 0.046

    # Charm 的 fee share 遠高於 Omnis
    charm_fee_share = 0.2063  # 報告值：20.63% fee capture rate

    # 1. Omnis 實際操作重放
    print(f"\n🔄 Omnis replay (1,287 rebalances, deploy={OMNIS_DEPLOY*100:.1f}%)...")
    r = run_replay("omnis_replay", omnis_rb, prices, swaps, vault_fee_share,
                    deploy_ratio=OMNIS_DEPLOY)
    results.append(r)
    print(f"   Alpha: {r['alpha']:+.2f}%  (report: {REPORT_OMNIS_ALPHA:+.2f}%)")

    # 2. Charm 實際操作重放（用 Charm 自己的 fee share 和 deploy ratio）
    # Charm 三層結構的 deploy 約 5%（跟 Omnis 類似，TVL 大但集中部署比例低）
    # 報告 alpha +1.50% → 校準 deploy_ratio
    print(f"🔄 Charm replay (101 × 3 positions, fee_share=20.63%)...")
    r = run_replay("charm_replay", charm_rb, prices, swaps, charm_fee_share,
                    deploy_ratio=0.05)
    results.append(r)
    print(f"   Alpha: {r['alpha']:+.2f}%  (report: {REPORT_CHARM_ALPHA:+.2f}%)")

    # 3. Baseline ATR (模擬現行 Omnis 策略)
    print(f"🔄 Baseline ATR (single range, deploy={OMNIS_DEPLOY*100:.1f}%)...")
    r = run_simulated("baseline_atr", prices, swaps, vault_fee_share,
                       baseline_ranges, baseline_should_rebalance,
                       deploy_ratio=OMNIS_DEPLOY)
    results.append(r)

    # 4. 多層 ATR (新策略)
    # 同樣的 Omnis vault ($2,600 TVL)，改用三層架構
    # deploy_ratio 同 Omnis，但三層結構讓部署的資金分散風險
    print(f"🔄 Multi-Layer ATR (3 layers, deploy={OMNIS_DEPLOY*100:.1f}%)...")
    r = run_simulated("multi_layer_atr", prices, swaps, vault_fee_share,
                       multi_layer_ranges, multi_layer_should_rebalance,
                       deploy_ratio=OMNIS_DEPLOY)
    results.append(r)

    # ── 結果 ──
    hodl_ret = results[0]["hodl_return"]
    print("\n" + "=" * 75)
    print(f"📊 BACKTEST RESULTS  |  HODL return: {hodl_ret:+.2f}%")
    print("=" * 75)
    print(f"{'Strategy':<22} {'Return':>8} {'Alpha':>8} {'Fee':>10} {'Rebal':>7} {'MaxDD':>8}")
    print("-" * 75)
    for r in results:
        print(f"{r['name']:<22} {r['return']:>+7.2f}% {r['alpha']:>+7.2f}% "
              f"${r['fee']:>8.2f} {r['rebalances']:>7} {r['max_dd']:>7.2f}%")
    print("-" * 75)
    print(f"{'report_omnis':<22} {'—':>8} {REPORT_OMNIS_ALPHA:>+7.2f}% "
          f"${REPORT_OMNIS_FEE:>8.2f} {'1,306':>7} {'25.61%':>8}")
    print(f"{'report_charm':<22} {'—':>8} {REPORT_CHARM_ALPHA:>+7.2f}% "
          f"{'—':>10} {'516':>7} {'25.23%':>8}")
    print("=" * 75)

    # 多層 vs 其他的改善
    ml = next(r for r in results if r["name"] == "multi_layer_atr")
    om = next(r for r in results if r["name"] == "omnis_replay")
    ch = next(r for r in results if r["name"] == "charm_replay")
    print(f"\n📈 Multi-Layer ATR vs Omnis:  alpha {om['alpha']:+.2f}% → {ml['alpha']:+.2f}%  "
          f"(改善 {ml['alpha'] - om['alpha']:+.2f}%)")
    print(f"📈 Multi-Layer ATR vs Charm:  alpha {ch['alpha']:+.2f}% → {ml['alpha']:+.2f}%  "
          f"(差距 {ml['alpha'] - ch['alpha']:+.2f}%)")

    # 保存結果
    output = {
        "data_source": "defi-onchain-analytics skill — Katana RPC",
        "pool": "WBTC-USDC (0x7446...5c)",
        "blocks": f"{prices[0].block} → {prices[-1].block}",
        "price_range": f"${prices[0].price:,.0f} → ${prices[-1].price:,.0f}",
        "swap_count": len(swaps),
        "vault_fee_share": vault_fee_share,
        "results": [
            {k: v for k, v in r.items() if k != "values"}
            for r in results
        ],
        "report_benchmarks": {
            "omnis_alpha": REPORT_OMNIS_ALPHA,
            "charm_alpha": REPORT_CHARM_ALPHA,
        },
    }
    out_file = DATA_DIR / "backtest_v2_results.json"
    out_file.write_text(json.dumps(output, indent=2))
    print(f"\n💾 Saved to {out_file}")


if __name__ == "__main__":
    main()
