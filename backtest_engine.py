#!/usr/bin/env python3
"""
CLAMM Vault 回測引擎
====================
模擬不同的集中流動性再平衡策略，用收集到的鏈上數據回測。

策略列表：
  1. baseline_atr      — 現行 ATR 策略（ATR×2.0, 每 3 分鐘 rebalance）
  2. smart_atr         — 改良 ATR（動態 multiplier + rebalance 門檻 + 趨勢感知）
  3. regime_atr        — 波動率 regime 切換（低波動窄區間、高波動寬區間）
  4. charm_replay      — Charm.fi 實際操作重放（作為 benchmark）

核心公式（來自 defi-onchain-analytics CLAMM vault analytics pattern）：
  - Fee = Σ swap_amount × fee_rate × (vault_liquidity_in_range / total_liquidity_in_range)
  - IL  = share_price_return - hodl_return
  - Alpha = vault_return - hodl_return

輸入數據：
  data/price_series.csv  — 池子價格時間序列
  data/swaps.csv         — 所有 swap 事件
  data/burns.csv         — Burn 事件（含 Omnis + Charm owner）
  data/mints.csv         — Mint 事件
"""

import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import numpy as np

# ─── 配置 ───────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"

POOL_FEE_RATE = 0.0005       # 5 bps
TOKEN0_DECIMALS = 8           # vbWBTC
TOKEN1_DECIMALS = 6           # vbUSDC
INITIAL_CAPITAL_USD = 2600.0  # 與報告中 Omnis vault TVL 一致

OMNIS_VAULT = "0x5977767ef6324864f170318681eccb82315f8761"
CHARM_VAULT = "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff"

# Uniswap V3 tick → price
def tick_to_price(tick: int) -> float:
    """tick → human price (USDC per WBTC)"""
    raw = 1.0001 ** tick
    return raw * (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))

def price_to_tick(price: float) -> int:
    """human price → tick"""
    raw = price / (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))
    if raw <= 0:
        return -887272
    return int(math.floor(math.log(raw) / math.log(1.0001)))

TICK_SPACING = 10  # 5 bps pool


# ─── 數據結構 ────────────────────────────────────────────────────────────────

@dataclass
class PricePoint:
    block: int
    tick: int
    price: float  # USDC per WBTC

@dataclass
class SwapEvent:
    block: int
    amount0: int   # vbWBTC raw (8 dec)
    amount1: int   # vbUSDC raw (6 dec)
    liquidity: int
    tick: int
    price: float

@dataclass
class Position:
    """一個集中流動性 position"""
    tick_lower: int
    tick_upper: int
    liquidity_usd: float  # 部署的 USD 價值
    entry_block: int
    entry_price: float

@dataclass
class BacktestResult:
    strategy_name: str
    initial_capital: float
    final_value: float
    hodl_value: float
    total_fee_income: float
    total_rebalances: int
    strategy_return_pct: float
    hodl_return_pct: float
    alpha_pct: float
    max_drawdown_pct: float
    fee_capture_efficiency: float  # 相對於 full-range 的 fee 放大倍數
    # 時間序列
    value_series: List[Tuple[int, float]] = field(default_factory=list)


# ─── 數據載入 ────────────────────────────────────────────────────────────────

def load_price_series() -> List[PricePoint]:
    path = DATA_DIR / "price_series.csv"
    points = []
    with open(path) as f:
        for row in csv.DictReader(f):
            points.append(PricePoint(
                block=int(row["block"]),
                tick=int(row["tick"]),
                price=float(row["price"]),
            ))
    points.sort(key=lambda p: p.block)
    print(f"  Loaded {len(points)} price points")
    return points

def load_swaps() -> List[SwapEvent]:
    path = DATA_DIR / "swaps.csv"
    swaps = []
    with open(path) as f:
        for row in csv.DictReader(f):
            swaps.append(SwapEvent(
                block=int(row["block"]),
                amount0=int(row["amount0"]),
                amount1=int(row["amount1"]),
                liquidity=int(row["liquidity"]),
                tick=int(row["tick"]),
                price=float(row["price"]),
            ))
    swaps.sort(key=lambda s: s.block)
    print(f"  Loaded {len(swaps)} swap events")
    return swaps

def load_vault_rebalances(vault_address: str) -> List[Dict]:
    """從 burns.csv + mints.csv 重建 vault 的 rebalance 歷史"""
    vault = vault_address.lower()
    burns_path = DATA_DIR / "burns.csv"
    mints_path = DATA_DIR / "mints.csv"

    # 按 tx_hash 分組
    tx_burns = {}
    tx_mints = {}

    if burns_path.exists():
        with open(burns_path) as f:
            for row in csv.DictReader(f):
                if row["owner"] == vault:
                    tx = row["tx_hash"]
                    if tx not in tx_burns:
                        tx_burns[tx] = []
                    tx_burns[tx].append(row)

    if mints_path.exists():
        with open(mints_path) as f:
            for row in csv.DictReader(f):
                if row["owner"] == vault:
                    tx = row["tx_hash"]
                    if tx not in tx_mints:
                        tx_mints[tx] = []
                    tx_mints[tx].append(row)

    # 找出同一 tx 有 burn + mint 的 = rebalance
    rebalances = []
    all_tx = set(tx_burns.keys()) | set(tx_mints.keys())
    for tx in all_tx:
        burns = tx_burns.get(tx, [])
        mints = tx_mints.get(tx, [])
        if burns and mints:
            # 這是一次 rebalance
            # 取 mint 的新 tick range 作為 rebalance 後的 position
            mint = mints[0]
            burn = burns[0]
            rebalances.append({
                "block": int(mint["block"]),
                "tx_hash": tx,
                "old_tickLower": int(burn["tickLower"]),
                "old_tickUpper": int(burn["tickUpper"]),
                "new_tickLower": int(mint["tickLower"]),
                "new_tickUpper": int(mint["tickUpper"]),
            })

    rebalances.sort(key=lambda r: r["block"])
    print(f"  Loaded {len(rebalances)} rebalances for {vault[:10]}...")
    return rebalances


# ─── 回測核心 ────────────────────────────────────────────────────────────────

def compute_fee_in_range(swap: SwapEvent, tick_lower: int, tick_upper: int,
                         vault_liquidity_share: float) -> float:
    """
    計算一筆 swap 對某個 position 產生的手續費

    模型：
    1. 如果 swap 時 tick 在 position range 內，vault 按佔比分得 fee
    2. 集中流動性的 fee 放大效應：range 越窄，每單位流動性分到的 fee 越多
       放大倍數 ≈ sqrt(p_upper/p_lower) / (sqrt(p_upper/p_lower) - 1) × vault_share
       但因為我們用的是 pool-level vault_share，已經隱含了 TVL 比例，
       所以只需檢查 in-range 即可。
    """
    if swap.tick < tick_lower or swap.tick >= tick_upper:
        return 0.0  # swap 不在 range 內

    # swap 的 USD volume
    volume_usd = abs(swap.amount1) / (10 ** TOKEN1_DECIMALS)  # USDC side

    # 報告校準：
    # Omnis 實際 fee = $142.81 / 96 天
    # Pool 總 fee = $90,508 / 96 天
    # Vault fee capture rate = 0.158%
    # 所以 vault_share ≈ 0.00158
    #
    # 但不同策略的區間寬度會影響 in-range 比例，
    # 進而影響 fee capture。我們用 vault_liquidity_share 作為 base，
    # 不再乘 concentration（因為報告的 0.158% 已經包含了 concentration 效果）
    fee = volume_usd * POOL_FEE_RATE * vault_liquidity_share
    return fee


def compute_position_value(tick_lower: int, tick_upper: int,
                           liquidity_usd: float, entry_price: float,
                           current_price: float) -> float:
    """
    計算集中流動性 position 的當前價值

    使用集中流動性 IL 公式：
    value_ratio = value_now / value_entry

    對於在 [p_a, p_b] 區間內以 entry_price 進場的 position：
    - 在區間內：用 V3 IL 公式
    - 價格 < p_a：全部是 token0，跟隨 token0 價格
    - 價格 > p_b：全部是 token1（USDC），價值不變
    """
    p_a = tick_to_price(tick_lower)
    p_b = tick_to_price(tick_upper)

    if p_a <= 0 or p_b <= 0 or p_a >= p_b:
        return liquidity_usd

    # Clamp entry_price to range (如果 entry 在區間外，按區間邊界計算)
    p_entry = max(p_a, min(p_b, entry_price))
    p_now = current_price

    sqrt_a = math.sqrt(p_a)
    sqrt_b = math.sqrt(p_b)
    sqrt_entry = math.sqrt(p_entry)

    # 計算入場時的 token amounts (以 L=1 歸一化)
    # x_entry = L * (1/sqrt(p_entry) - 1/sqrt(p_b))
    # y_entry = L * (sqrt(p_entry) - sqrt(p_a))
    x_entry = 1.0 / sqrt_entry - 1.0 / sqrt_b
    y_entry = sqrt_entry - sqrt_a
    value_entry = x_entry * p_entry + y_entry

    if value_entry <= 0:
        return liquidity_usd

    # 計算當前的 token amounts
    if p_now <= p_a:
        # 全部是 token0
        x_now = 1.0 / sqrt_a - 1.0 / sqrt_b
        y_now = 0.0
    elif p_now >= p_b:
        # 全部是 token1
        x_now = 0.0
        y_now = sqrt_b - sqrt_a
    else:
        sqrt_now = math.sqrt(p_now)
        x_now = 1.0 / sqrt_now - 1.0 / sqrt_b
        y_now = sqrt_now - sqrt_a

    value_now = x_now * p_now + y_now

    ratio = value_now / value_entry if value_entry > 0 else 1.0
    return liquidity_usd * ratio


def align_tick(tick: int) -> int:
    """對齊到 tick spacing"""
    return (tick // TICK_SPACING) * TICK_SPACING


# ─── 策略定義 ────────────────────────────────────────────────────────────────

class BaseStrategy:
    """策略基底類"""

    def __init__(self, name: str):
        self.name = name

    def should_rebalance(self, current_block: int, current_price: float,
                         current_tick: int, position: Optional[Position],
                         price_history: List[PricePoint]) -> bool:
        raise NotImplementedError

    def compute_new_range(self, current_price: float, current_tick: int,
                          price_history: List[PricePoint]) -> Tuple[int, int]:
        raise NotImplementedError


class BaselineATR(BaseStrategy):
    """
    現行 ATR 策略重現
    - ATR period = 14 (用 ~14 小時數據, 每小時 3600 blocks)
    - multiplier = 2.0
    - 每 ~3 分鐘 rebalance (每 180 blocks)
    """

    def __init__(self):
        super().__init__("baseline_atr")
        # 報告：1,306 rebalances / 8.3M blocks ≈ 每 ~6,400 blocks
        self.rebalance_interval = 6000
        self.atr_period = 14
        # Omnis 實際區間寬度 ~20%，ATR/price 約 5%，所以 mult ≈ 2.0
        # 但加上 price clamp 和 fallback，實際效果等效 ~2.5
        self.multiplier = 2.5

    def _compute_atr(self, price_history: List[PricePoint]) -> float:
        if len(price_history) < self.atr_period + 1:
            return price_history[-1].price * 0.05

        # 用最近 atr_period+1 個點計算 ATR
        recent = price_history[-(self.atr_period + 1):]
        trs = []
        for i in range(1, len(recent)):
            h = max(recent[i].price, recent[i-1].price) * 1.005  # 近似 high
            l = min(recent[i].price, recent[i-1].price) * 0.995  # 近似 low
            prev_c = recent[i-1].price
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        return sum(trs[-self.atr_period:]) / self.atr_period if trs else recent[-1].price * 0.05

    def should_rebalance(self, current_block, current_price, current_tick,
                         position, price_history):
        if position is None:
            return True
        return (current_block - position.entry_block) >= self.rebalance_interval

    def compute_new_range(self, current_price, current_tick, price_history):
        atr = self._compute_atr(price_history)
        if atr <= 0:
            atr = current_price * 0.05
        lower = current_price - atr * self.multiplier
        upper = current_price + atr * self.multiplier
        return align_tick(price_to_tick(max(1, lower))), align_tick(price_to_tick(upper))


class SmartATR(BaseStrategy):
    """
    改良 ATR 策略
    - 動態 multiplier：趨勢強時拉寬 (3.5-5.0)，橫盤時收窄 (1.5-2.0)
    - Rebalance 門檻：只在價格接近區間邊界 80% 時才 rebalance
    - 最小 rebalance 間隔：3600 blocks (~1 小時)
    """

    def __init__(self):
        super().__init__("smart_atr")
        self.atr_period = 14
        self.min_rebalance_interval = 3600  # ~1 小時
        self.boundary_trigger_pct = 0.80  # 80% 邊界觸發

    def _compute_atr(self, price_history: List[PricePoint]) -> float:
        if len(price_history) < self.atr_period + 1:
            return price_history[-1].price * 0.05
        recent = price_history[-(self.atr_period + 1):]
        trs = []
        for i in range(1, len(recent)):
            h = max(recent[i].price, recent[i-1].price) * 1.005
            l = min(recent[i].price, recent[i-1].price) * 0.995
            prev_c = recent[i-1].price
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        return sum(trs[-self.atr_period:]) / self.atr_period if trs else recent[-1].price * 0.05

    def _compute_trend_strength(self, price_history: List[PricePoint]) -> float:
        """趨勢強度 = |EMA_short - EMA_long| / ATR"""
        if len(price_history) < 50:
            return 0.0
        prices = [p.price for p in price_history[-50:]]
        ema_short = self._ema(prices, 10)
        ema_long = self._ema(prices, 40)
        atr = self._compute_atr(price_history)
        if atr <= 0:
            return 0.0
        return abs(ema_short - ema_long) / atr

    def _ema(self, values: list, period: int) -> float:
        if not values:
            return 0
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _dynamic_multiplier(self, trend_strength: float) -> float:
        """趨勢越強 → multiplier 越大"""
        if trend_strength > 2.0:
            return 5.0   # 強趨勢：寬區間
        elif trend_strength > 1.0:
            return 3.5   # 中等趨勢
        elif trend_strength > 0.5:
            return 2.5   # 弱趨勢
        else:
            return 1.5   # 橫盤：窄區間

    def should_rebalance(self, current_block, current_price, current_tick,
                         position, price_history):
        if position is None:
            return True

        # 最小間隔
        if (current_block - position.entry_block) < self.min_rebalance_interval:
            return False

        # 只在價格接近邊界時觸發
        p_lower = tick_to_price(position.tick_lower)
        p_upper = tick_to_price(position.tick_upper)
        range_size = p_upper - p_lower
        if range_size <= 0:
            return True

        # 價格在區間中的位置 (0=下界, 1=上界)
        position_in_range = (current_price - p_lower) / range_size
        # 超出區間 或 接近邊界 80%
        if position_in_range < (1 - self.boundary_trigger_pct) / 2:
            return True  # 接近下界
        if position_in_range > 1 - (1 - self.boundary_trigger_pct) / 2:
            return True  # 接近上界
        if current_price <= p_lower or current_price >= p_upper:
            return True  # 已出界

        return False

    def compute_new_range(self, current_price, current_tick, price_history):
        atr = self._compute_atr(price_history)
        if atr <= 0:
            atr = current_price * 0.05
        trend = self._compute_trend_strength(price_history)
        mult = self._dynamic_multiplier(trend)

        # 非對稱區間：趨勢方向多留空間
        if len(price_history) >= 20:
            recent_return = (price_history[-1].price - price_history[-20].price) / price_history[-20].price
            if recent_return < -0.05:
                # 下跌趨勢：下方多留空間
                lower = current_price - atr * mult * 1.3
                upper = current_price + atr * mult * 0.7
            elif recent_return > 0.05:
                # 上漲趨勢：上方多留空間
                lower = current_price - atr * mult * 0.7
                upper = current_price + atr * mult * 1.3
            else:
                lower = current_price - atr * mult
                upper = current_price + atr * mult
        else:
            lower = current_price - atr * mult
            upper = current_price + atr * mult

        return align_tick(price_to_tick(max(1, lower))), align_tick(price_to_tick(upper))


class MultiLayerATR(BaseStrategy):
    """
    多層 Position 策略（受 Charm.fi 啟發）
    - Layer 1 (30% 資金): full-range — 保底，永不 rebalance
    - Layer 2 (35% 資金): 寬區間 ATR×4.0 — 低頻 rebalance
    - Layer 3 (35% 資金): 窄區間 ATR×1.5 — 積極 fee capture
    結合趨勢感知動態調整 Layer 3 的區間
    """

    def __init__(self):
        super().__init__("multi_layer_atr")
        self.atr_period = 14
        self.min_rebalance_interval = 5000
        self.layer_weights = [0.30, 0.35, 0.35]  # full-range, wide, narrow

    def _compute_atr(self, price_history):
        if len(price_history) < self.atr_period + 1:
            return price_history[-1].price * 0.05
        recent = price_history[-(self.atr_period + 1):]
        trs = []
        for i in range(1, len(recent)):
            h = max(recent[i].price, recent[i-1].price) * 1.005
            l = min(recent[i].price, recent[i-1].price) * 0.995
            prev_c = recent[i-1].price
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        return sum(trs[-self.atr_period:]) / self.atr_period if trs else recent[-1].price * 0.05

    def should_rebalance(self, current_block, current_price, current_tick,
                         position, price_history):
        if position is None:
            return True
        if (current_block - position.entry_block) < self.min_rebalance_interval:
            return False
        # 只在窄區間出界時才 rebalance
        p_lower = tick_to_price(position.tick_lower)
        p_upper = tick_to_price(position.tick_upper)
        if current_price < p_lower or current_price > p_upper:
            return True
        range_size = p_upper - p_lower
        if range_size > 0:
            pos_pct = (current_price - p_lower) / range_size
            if pos_pct < 0.1 or pos_pct > 0.9:
                return True
        return False

    def compute_new_range(self, current_price, current_tick, price_history):
        # 回傳的是 Layer 3 (窄區間) 的 range
        # Layer 1 和 2 在 run_backtest 中特殊處理
        atr = self._compute_atr(price_history)
        if atr <= 0:
            atr = current_price * 0.05
        lower = current_price - atr * 1.5
        upper = current_price + atr * 1.5
        return align_tick(price_to_tick(max(1, lower))), align_tick(price_to_tick(upper))


class RegimeATR(BaseStrategy):
    """
    波動率 Regime 切換策略
    - 低波動 regime: 窄區間 (ATR×1.5), 較頻繁 rebalance
    - 高波動 regime: 寬區間 (ATR×4.0), 低頻 rebalance
    - 極端行情: 超寬區間 (ATR×6.0), 幾乎不 rebalance
    """

    def __init__(self):
        super().__init__("regime_atr")
        self.atr_period = 14
        self.vol_window = 50  # 用 50 個採樣點計算 realized vol
        self.vol_history = []  # 歷史 vol 值，用於計算分位數

    def _compute_atr(self, price_history):
        if len(price_history) < self.atr_period + 1:
            return price_history[-1].price * 0.05
        recent = price_history[-(self.atr_period + 1):]
        trs = []
        for i in range(1, len(recent)):
            h = max(recent[i].price, recent[i-1].price) * 1.005
            l = min(recent[i].price, recent[i-1].price) * 0.995
            prev_c = recent[i-1].price
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        return sum(trs[-self.atr_period:]) / self.atr_period if trs else recent[-1].price * 0.05

    def _compute_realized_vol(self, price_history: List[PricePoint]) -> float:
        """計算 realized volatility (annualized)"""
        if len(price_history) < self.vol_window + 1:
            return 0.5  # 默認中等波動
        recent = price_history[-(self.vol_window + 1):]
        returns = []
        for i in range(1, len(recent)):
            if recent[i-1].price > 0:
                r = math.log(recent[i].price / recent[i-1].price)
                returns.append(r)
        if not returns:
            return 0.5
        std = np.std(returns)
        # 年化（假設每個採樣間隔 ~33 分鐘，一年約 15,900 個間隔）
        annualized = std * math.sqrt(15900)
        return annualized

    def _get_regime(self, vol: float) -> str:
        """根據波動率判斷 regime"""
        self.vol_history.append(vol)
        if len(self.vol_history) < 20:
            return "medium"

        # 用歷史分位數
        sorted_vols = sorted(self.vol_history)
        pct = sorted_vols.index(min(sorted_vols, key=lambda v: abs(v - vol))) / len(sorted_vols)

        if pct > 0.90:
            return "extreme"
        elif pct > 0.65:
            return "high"
        elif pct < 0.35:
            return "low"
        else:
            return "medium"

    def should_rebalance(self, current_block, current_price, current_tick,
                         position, price_history):
        if position is None:
            return True

        vol = self._compute_realized_vol(price_history)
        regime = self._get_regime(vol)

        # 不同 regime 的最小 rebalance 間隔
        min_intervals = {
            "low": 1800,      # ~30 分鐘
            "medium": 3600,   # ~1 小時
            "high": 10800,    # ~3 小時
            "extreme": 21600, # ~6 小時
        }
        min_interval = min_intervals.get(regime, 3600)

        if (current_block - position.entry_block) < min_interval:
            return False

        # 價格出界才 rebalance
        p_lower = tick_to_price(position.tick_lower)
        p_upper = tick_to_price(position.tick_upper)
        if current_price < p_lower or current_price > p_upper:
            return True

        # 接近邊界 85%
        range_size = p_upper - p_lower
        if range_size > 0:
            pos_pct = (current_price - p_lower) / range_size
            if pos_pct < 0.075 or pos_pct > 0.925:
                return True

        return False

    def compute_new_range(self, current_price, current_tick, price_history):
        atr = self._compute_atr(price_history)
        if atr <= 0:
            atr = current_price * 0.05
        vol = self._compute_realized_vol(price_history)
        regime = self._get_regime(vol)

        multipliers = {
            "low": 1.5,
            "medium": 2.5,
            "high": 4.0,
            "extreme": 6.0,
        }
        mult = multipliers.get(regime, 2.5)

        lower = current_price - atr * mult
        upper = current_price + atr * mult

        return align_tick(price_to_tick(max(1, lower))), align_tick(price_to_tick(upper))


class CharmReplay(BaseStrategy):
    """
    重放 Charm.fi 的實際 rebalance 歷史
    用鏈上收集到的 Burn/Mint 事件重建
    """

    def __init__(self, rebalances: List[Dict]):
        super().__init__("charm_replay")
        self.rebalances = rebalances
        self.rebalance_idx = 0

    def should_rebalance(self, current_block, current_price, current_tick,
                         position, price_history):
        if self.rebalance_idx >= len(self.rebalances):
            return False
        return current_block >= self.rebalances[self.rebalance_idx]["block"]

    def compute_new_range(self, current_price, current_tick, price_history):
        if self.rebalance_idx >= len(self.rebalances):
            # fallback
            tick = price_to_tick(current_price)
            return align_tick(tick - 500), align_tick(tick + 500)
        rb = self.rebalances[self.rebalance_idx]
        self.rebalance_idx += 1
        return rb["new_tickLower"], rb["new_tickUpper"]


# ─── 回測主迴圈 ──────────────────────────────────────────────────────────────

def run_backtest(strategy: BaseStrategy, prices: List[PricePoint],
                 swaps: List[SwapEvent]) -> BacktestResult:
    """
    執行回測

    簡化假設：
    1. Vault TVL = INITIAL_CAPITAL_USD
    2. Fee 按 in-range 比例分配（vault 的 fee share 校準到報告值）
    3. Multi-layer 策略用加權平均 value
    """
    VAULT_POOL_SHARE = 0.00158  # 報告校準值

    initial_price = prices[0].price
    is_multi_layer = isinstance(strategy, MultiLayerATR)

    if is_multi_layer:
        # 三層 position
        FULL_RANGE_TICKS = (-887270, 887270)
        weights = strategy.layer_weights  # [0.30, 0.35, 0.35]

        # Layer 1: full-range (永不 rebalance)
        layer1_capital = INITIAL_CAPITAL_USD * weights[0]
        layer1_entry_price = initial_price

        # Layer 2: 寬區間 (初始 ATR×4)
        layer2_capital = INITIAL_CAPITAL_USD * weights[1]
        layer2_entry_price = initial_price
        atr_init = initial_price * 0.05  # 初始 ATR 估計
        layer2_lower = align_tick(price_to_tick(max(1, initial_price - atr_init * 4)))
        layer2_upper = align_tick(price_to_tick(initial_price + atr_init * 4))

        # Layer 3: 窄區間 (由策略控制)
        layer3_capital = INITIAL_CAPITAL_USD * weights[2]
        layer3_position = None
    else:
        position = None
        capital = INITIAL_CAPITAL_USD

    fee_total = 0.0
    fee_at_last_rebalance = 0.0
    rebalance_count = 0
    value_series = []
    max_value = INITIAL_CAPITAL_USD
    max_drawdown = 0.0
    swap_idx = 0
    price_history = []

    for pp in prices:
        price_history.append(pp)

        if is_multi_layer:
            # Layer 3 的 rebalance 邏輯
            if strategy.should_rebalance(pp.block, pp.price, pp.tick,
                                          layer3_position, price_history):
                tick_lower, tick_upper = strategy.compute_new_range(
                    pp.price, pp.tick, price_history)
                if layer3_position is not None:
                    pos_val = compute_position_value(
                        layer3_position.tick_lower, layer3_position.tick_upper,
                        layer3_position.liquidity_usd, layer3_position.entry_price, pp.price)
                    fee_since = fee_total * weights[2] - fee_at_last_rebalance
                    layer3_capital = pos_val + max(0, fee_since)
                layer3_position = Position(tick_lower, tick_upper, layer3_capital,
                                           pp.block, pp.price)
                fee_at_last_rebalance = fee_total * weights[2]
                rebalance_count += 1

            # Fee: 三層都在 in-range 時收 fee
            while swap_idx < len(swaps) and swaps[swap_idx].block <= pp.block:
                s = swaps[swap_idx]
                # Layer 1 (full-range): 永遠 in-range
                fee_total += compute_fee_in_range(s, FULL_RANGE_TICKS[0],
                                                  FULL_RANGE_TICKS[1], VAULT_POOL_SHARE)
                # Layer 2 (寬區間)
                fee_total += compute_fee_in_range(s, layer2_lower, layer2_upper,
                                                  VAULT_POOL_SHARE)
                # Layer 3 (窄區間)
                if layer3_position:
                    fee_total += compute_fee_in_range(s, layer3_position.tick_lower,
                                                     layer3_position.tick_upper,
                                                     VAULT_POOL_SHARE)
                swap_idx += 1

            # 計算總價值
            v1 = compute_position_value(FULL_RANGE_TICKS[0], FULL_RANGE_TICKS[1],
                                        layer1_capital, layer1_entry_price, pp.price)
            v2 = compute_position_value(layer2_lower, layer2_upper,
                                        layer2_capital, layer2_entry_price, pp.price)
            if layer3_position:
                v3 = compute_position_value(layer3_position.tick_lower,
                                            layer3_position.tick_upper,
                                            layer3_position.liquidity_usd,
                                            layer3_position.entry_price, pp.price)
            else:
                v3 = layer3_capital
            current_value = v1 + v2 + v3 + fee_total
        else:
            # 單層策略
            if strategy.should_rebalance(pp.block, pp.price, pp.tick,
                                          position, price_history):
                tick_lower, tick_upper = strategy.compute_new_range(
                    pp.price, pp.tick, price_history)
                if position is not None:
                    pos_value = compute_position_value(
                        position.tick_lower, position.tick_upper,
                        position.liquidity_usd, position.entry_price, pp.price)
                    fee_since = fee_total - fee_at_last_rebalance
                    capital = pos_value + fee_since
                position = Position(tick_lower, tick_upper, capital,
                                    pp.block, pp.price)
                fee_at_last_rebalance = fee_total
                rebalance_count += 1

            if position:
                while swap_idx < len(swaps) and swaps[swap_idx].block <= pp.block:
                    fee = compute_fee_in_range(swaps[swap_idx],
                                               position.tick_lower, position.tick_upper,
                                               VAULT_POOL_SHARE)
                    fee_total += fee
                    swap_idx += 1
                pos_value = compute_position_value(
                    position.tick_lower, position.tick_upper,
                    position.liquidity_usd, position.entry_price, pp.price)
                current_value = pos_value + (fee_total - fee_at_last_rebalance)
            else:
                current_value = capital

        value_series.append((pp.block, current_value))
        max_value = max(max_value, current_value)
        dd = (max_value - current_value) / max_value if max_value > 0 else 0
        max_drawdown = max(max_drawdown, dd)

    # HODL benchmark
    final_price = prices[-1].price
    hodl_value = INITIAL_CAPITAL_USD * (
        0.5 * (final_price / initial_price) +  # WBTC 部分
        0.5                                      # USDC 部分
    )

    final_value = value_series[-1][1] if value_series else INITIAL_CAPITAL_USD
    strategy_return = (final_value - INITIAL_CAPITAL_USD) / INITIAL_CAPITAL_USD * 100
    hodl_return = (hodl_value - INITIAL_CAPITAL_USD) / INITIAL_CAPITAL_USD * 100
    alpha = strategy_return - hodl_return

    return BacktestResult(
        strategy_name=strategy.name,
        initial_capital=INITIAL_CAPITAL_USD,
        final_value=final_value,
        hodl_value=hodl_value,
        total_fee_income=fee_total,
        total_rebalances=rebalance_count,
        strategy_return_pct=strategy_return,
        hodl_return_pct=hodl_return,
        alpha_pct=alpha,
        max_drawdown_pct=max_drawdown * 100,
        fee_capture_efficiency=fee_total / (INITIAL_CAPITAL_USD * VAULT_POOL_SHARE) if VAULT_POOL_SHARE > 0 else 0,
        value_series=value_series,
    )


# ─── 主程序 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("CLAMM Vault Backtest Engine — WBTC-USDC on Katana")
    print("=" * 70)

    # 載入數據
    print("\n📂 Loading data...")
    prices = load_price_series()
    swaps = load_swaps()

    # 載入 Charm rebalance 歷史
    print("\n📂 Loading Charm rebalances...")
    charm_rebalances = load_vault_rebalances(CHARM_VAULT)

    # 定義策略
    strategies = [
        BaselineATR(),
        SmartATR(),
        RegimeATR(),
        MultiLayerATR(),
    ]
    if charm_rebalances:
        strategies.append(CharmReplay(charm_rebalances))

    # 執行回測
    results = []
    for strategy in strategies:
        print(f"\n🔄 Running: {strategy.name}...")
        result = run_backtest(strategy, prices, swaps)
        results.append(result)
        print(f"   Return: {result.strategy_return_pct:+.2f}%  |  "
              f"HODL: {result.hodl_return_pct:+.2f}%  |  "
              f"Alpha: {result.alpha_pct:+.2f}%  |  "
              f"Fee: ${result.total_fee_income:.2f}  |  "
              f"Rebalances: {result.total_rebalances}")

    # 結果報告
    print("\n" + "=" * 70)
    print("📊 BACKTEST RESULTS COMPARISON")
    print("=" * 70)
    print(f"{'Strategy':<20} {'Return':>8} {'HODL':>8} {'Alpha':>8} "
          f"{'Fee':>10} {'Rebal':>7} {'MaxDD':>8}")
    print("-" * 70)
    for r in results:
        print(f"{r.strategy_name:<20} {r.strategy_return_pct:>+7.2f}% "
              f"{r.hodl_return_pct:>+7.2f}% {r.alpha_pct:>+7.2f}% "
              f"${r.total_fee_income:>8.2f} {r.total_rebalances:>7} "
              f"{r.max_drawdown_pct:>7.2f}%")
    print("=" * 70)

    # 報告的 benchmark
    print("\n📋 Report Benchmarks:")
    print(f"   Omnis actual alpha:  -3.65%")
    print(f"   Charm actual alpha:  +1.50%")

    # 保存結果
    output = {
        "config": {
            "pool": "WBTC-USDC",
            "chain": "Katana",
            "initial_capital": INITIAL_CAPITAL_USD,
            "price_points": len(prices),
            "swap_events": len(swaps),
            "start_block": prices[0].block,
            "end_block": prices[-1].block,
            "start_price": prices[0].price,
            "end_price": prices[-1].price,
        },
        "results": [
            {
                "strategy": r.strategy_name,
                "return_pct": round(r.strategy_return_pct, 4),
                "hodl_return_pct": round(r.hodl_return_pct, 4),
                "alpha_pct": round(r.alpha_pct, 4),
                "fee_income": round(r.total_fee_income, 2),
                "rebalances": r.total_rebalances,
                "max_drawdown_pct": round(r.max_drawdown_pct, 4),
                "final_value": round(r.final_value, 2),
            }
            for r in results
        ],
        "benchmarks": {
            "omnis_actual_alpha": -3.65,
            "charm_actual_alpha": 1.50,
        }
    }
    output_file = DATA_DIR / "backtest_results.json"
    output_file.write_text(json.dumps(output, indent=2))
    print(f"\n💾 Results saved to {output_file}")


if __name__ == "__main__":
    main()
