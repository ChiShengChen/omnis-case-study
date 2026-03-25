#!/usr/bin/env python3
"""
Backtest v3-full — Full V3 Liquidity Math (no deploy_ratio hack)
================================================================
正確模擬 Steer vault 的行為：
  1. 追蹤實際 token0/token1 餘額（不用 deploy_ratio）
  2. 每次 rebalance: Burn → 回收 tokens → Mint 到新 range
  3. 用 V3 liquidity math 計算精確的 token 部署量和價值

核心公式 (Uniswap V3):
  Position with liquidity L in range [pa, pb] at current price P:
    if P ≤ pa: x = L(1/√pa - 1/√pb),  y = 0        (全 token0)
    if P ≥ pb: x = 0,  y = L(√pb - √pa)             (全 token1)
    else:      x = L(1/√P - 1/√pb),  y = L(√P - √pa) (混合)

  Deploy liquidity L given tokens (x, y):
    Lx = x / (1/√P - 1/√pb)   if P < pb
    Ly = y / (√P - √pa)        if P > pa
    L = min(Lx, Ly)             if pa < P < pb
"""
import csv, math, json
from pathlib import Path
from typing import List, Tuple, Optional
import numpy as np

# ─── Pool configs ─────────────────────────────────────────────────────────

POOLS = {
    "wbtc_usdc": {
        "name": "WBTC-USDC",
        "data_dir": Path(__file__).parent / "data",
        "t0_dec": 8, "t1_dec": 6,  # token0=vbWBTC, token1=vbUSDC
        "invert_price": False,      # price from tick = USDC per WBTC ✓
        "vault": "0x5977767ef6324864f170318681eccb82315f8761",
        "initial_usd": 2600.0,
        "report_alpha": -3.65,
        "fee_share": 0.00158,
        "tick_spacing": 10,
    },
    "usdc_eth": {
        "name": "USDC-ETH",
        "data_dir": Path(__file__).parent / "data_eth",
        "t0_dec": 6, "t1_dec": 18,  # token0=vbUSDC, token1=vbETH
        "invert_price": True,       # tick price = ETH/USDC → invert to USDC/ETH
        "vault": "0x811b8c618716ca62b092b67c09e55361ae6df429",
        "initial_usd": 2134.0,
        "report_alpha": -10.86,
        "fee_share": 0.00133,
        "tick_spacing": 10,
    },
}

POOL_FEE = 0.0005


# ─── V3 Math ─────────────────────────────────────────────────────────────

def tick_to_sqrt_price(tick: int) -> float:
    return 1.0001 ** (tick / 2)

def tick_to_price(tick: int, t0_dec: int, t1_dec: int, invert: bool) -> float:
    """tick → human-readable price (USDC per base asset)"""
    raw = 1.0001 ** tick
    human = raw * (10 ** (t0_dec - t1_dec))
    if invert:
        return 1.0 / human if human > 0 else 0
    return human

def price_to_tick(price: float, t0_dec: int, t1_dec: int, invert: bool) -> int:
    if invert:
        raw_human = 1.0 / price if price > 0 else 1e-18
    else:
        raw_human = price
    raw = raw_human / (10 ** (t0_dec - t1_dec))
    if raw <= 0:
        return -887270
    return int(math.floor(math.log(raw) / math.log(1.0001)))

def align_tick(tick: int, spacing: int = 10) -> int:
    return (tick // spacing) * spacing


class V3Position:
    """一個 V3 集中流動性 position"""

    def __init__(self, tick_lower: int, tick_upper: int, liquidity: float,
                 t0_dec: int, t1_dec: int, invert: bool):
        self.tl = tick_lower
        self.tu = tick_upper
        self.L = liquidity
        self.t0_dec = t0_dec
        self.t1_dec = t1_dec
        self.invert = invert

    @property
    def pa(self):
        """lower price (USDC per base)"""
        p1 = tick_to_price(self.tl, self.t0_dec, self.t1_dec, self.invert)
        p2 = tick_to_price(self.tu, self.t0_dec, self.t1_dec, self.invert)
        return min(p1, p2)

    @property
    def pb(self):
        """upper price"""
        p1 = tick_to_price(self.tl, self.t0_dec, self.t1_dec, self.invert)
        p2 = tick_to_price(self.tu, self.t0_dec, self.t1_dec, self.invert)
        return max(p1, p2)

    def amounts_at_price(self, price: float) -> Tuple[float, float]:
        """
        回傳 (base_amount, usdc_amount) at given price
        base = WBTC or ETH, usdc = USDC
        """
        pa, pb = self.pa, self.pb
        if pa <= 0 or pb <= pa or self.L <= 0:
            return 0, 0

        sqrt_a = math.sqrt(pa)
        sqrt_b = math.sqrt(pb)

        if price <= pa:
            # All base token
            x = self.L * (1/sqrt_a - 1/sqrt_b)
            return x, 0
        elif price >= pb:
            # All USDC
            y = self.L * (sqrt_b - sqrt_a)
            return 0, y
        else:
            sqrt_p = math.sqrt(price)
            x = self.L * (1/sqrt_p - 1/sqrt_b)
            y = self.L * (sqrt_p - sqrt_a)
            return x, y

    def value_at_price(self, price: float) -> float:
        """USD value at given price"""
        base, usdc = self.amounts_at_price(price)
        return base * price + usdc

    @classmethod
    def from_amounts(cls, tick_lower, tick_upper, base_amount, usdc_amount,
                     price, t0_dec, t1_dec, invert):
        """
        從可用的 token 量計算最大 liquidity 並建立 position
        回傳 (position, unused_base, unused_usdc)
        """
        p1 = tick_to_price(tick_lower, t0_dec, t1_dec, invert)
        p2 = tick_to_price(tick_upper, t0_dec, t1_dec, invert)
        pa, pb = min(p1, p2), max(p1, p2)

        if pa <= 0 or pb <= pa:
            return cls(tick_lower, tick_upper, 0, t0_dec, t1_dec, invert), base_amount, usdc_amount

        sqrt_a = math.sqrt(pa)
        sqrt_b = math.sqrt(pb)

        if price <= pa:
            # Need only base token
            denom = 1/sqrt_a - 1/sqrt_b
            L = base_amount / denom if denom > 0 else 0
            used_base = L * denom if L > 0 else 0
            return cls(tick_lower, tick_upper, L, t0_dec, t1_dec, invert), base_amount - used_base, usdc_amount

        elif price >= pb:
            # Need only USDC
            denom = sqrt_b - sqrt_a
            L = usdc_amount / denom if denom > 0 else 0
            used_usdc = L * denom if L > 0 else 0
            return cls(tick_lower, tick_upper, L, t0_dec, t1_dec, invert), base_amount, usdc_amount - used_usdc

        else:
            # Need both tokens
            sqrt_p = math.sqrt(price)
            dx = 1/sqrt_p - 1/sqrt_b
            dy = sqrt_p - sqrt_a
            Lx = base_amount / dx if dx > 0 else float('inf')
            Ly = usdc_amount / dy if dy > 0 else float('inf')
            L = min(Lx, Ly)
            if L <= 0 or L == float('inf'):
                return cls(tick_lower, tick_upper, 0, t0_dec, t1_dec, invert), base_amount, usdc_amount
            used_base = L * dx
            used_usdc = L * dy
            return cls(tick_lower, tick_upper, L, t0_dec, t1_dec, invert), base_amount - used_base, usdc_amount - used_usdc


# ─── Data Loading ─────────────────────────────────────────────────────────

def load_data(cfg):
    data_dir = cfg["data_dir"]
    t0_dec, t1_dec, invert = cfg["t0_dec"], cfg["t1_dec"], cfg["invert_price"]

    prices = []
    with open(data_dir / "price_series.csv") as f:
        for row in csv.DictReader(f):
            prices.append((int(row["block"]), int(row["tick"]), float(row["price"])))
    prices.sort()

    swaps = []
    with open(data_dir / "swaps.csv") as f:
        for row in csv.DictReader(f):
            swaps.append((int(row["block"]), int(row["tick"]),
                          abs(int(row["amount0"])) / (10**t0_dec),
                          abs(int(row["amount1"])) / (10**t1_dec)))
    swaps.sort()

    vault = cfg["vault"].lower()
    tx_burns, tx_mints = {}, {}
    with open(data_dir / "burns.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == vault:
                tx_burns.setdefault(row["tx_hash"], []).append(row)
    with open(data_dir / "mints.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == vault:
                tx_mints.setdefault(row["tx_hash"], []).append(row)

    rbs = []
    for tx in sorted(set(tx_burns) & set(tx_mints), key=lambda t: int(tx_mints[t][0]["block"])):
        mints = sorted(tx_mints[tx], key=lambda m: int(m["tickLower"]))
        rbs.append({
            "block": int(mints[0]["block"]),
            "positions": [(int(m["tickLower"]), int(m["tickUpper"])) for m in mints],
        })

    return prices, swaps, rbs


# ─── Backtest Engine ──────────────────────────────────────────────────────

def run_backtest(name: str, cfg: dict, prices, swaps,
                 make_ranges_fn, should_rebalance_fn) -> dict:
    """
    Full V3 liquidity math backtest.

    追蹤: base_balance (WBTC/ETH) + usdc_balance + positions (V3Position list)
    """
    t0_dec = cfg["t0_dec"]
    t1_dec = cfg["t1_dec"]
    invert = cfg["invert_price"]
    fee_share = cfg["fee_share"]
    ts = cfg["tick_spacing"]
    init_usd = cfg["initial_usd"]

    # 初始 token 餘額 (50/50 split)
    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0  # half in base token
    usdc_bal = init_usd / 2          # half in USDC

    positions: List[V3Position] = []
    fee_base = 0.0
    fee_usdc = 0.0
    si = 0
    n_rb = 0
    history = []
    vals = []
    mx = init_usd
    mdd = 0

    for block, tick, price in prices:
        history.append((block, tick, price))

        # Check rebalance
        if should_rebalance_fn(block, price, positions, history):
            # Burn all positions → recover tokens
            for pos in positions:
                b, u = pos.amounts_at_price(price)
                base_bal += b
                usdc_bal += u
            # Add accrued fees
            base_bal += fee_base
            usdc_bal += fee_usdc
            fee_base = 0
            fee_usdc = 0

            # Rebalance cost: swap slippage on narrow portion
            # swap_vol ≈ 16.9% of TVL × 50% (half needs swapping)
            # cost = swap_vol × 0.15% (pool fee 0.05% + price impact 0.1%)
            if n_rb > 0:
                total_val = base_bal * price + usdc_bal
                narrow_swap_vol = total_val * 0.169 * 0.5
                slippage_cost = narrow_swap_vol * 0.0015
                usdc_bal -= slippage_cost

            # Get new tick ranges with weights
            ranges = make_ranges_fn(price, history)  # [(tl, tu, weight), ...]

            # Mint new positions
            positions = []
            total_base = base_bal
            total_usdc = usdc_bal
            for tl, tu, w in ranges:
                # Allocate proportional tokens
                alloc_base = total_base * w
                alloc_usdc = total_usdc * w
                pos, leftover_base, leftover_usdc = V3Position.from_amounts(
                    tl, tu, alloc_base, alloc_usdc, price, t0_dec, t1_dec, invert)
                positions.append(pos)
                # Leftover goes back to idle (but we pre-allocated, so track net)
                base_bal -= (alloc_base - leftover_base)
                usdc_bal -= (alloc_usdc - leftover_usdc)

            n_rb += 1

        # Accumulate fees from swaps
        if positions:
            while si < len(swaps) and swaps[si][0] <= block:
                _, stk, vol_base, vol_usdc = swaps[si]
                for pos in positions:
                    if pos.tl <= stk < pos.tu and pos.L > 0:
                        # Simplified: fee proportional to vault's share
                        fee_usdc += vol_usdc * POOL_FEE * fee_share
                si += 1

        # Current total value
        pos_value = sum(p.value_at_price(price) for p in positions)
        idle_value = base_bal * price + usdc_bal
        fee_value = fee_base * price + fee_usdc
        total_value = pos_value + idle_value + fee_value

        vals.append((block, total_value))
        mx = max(mx, total_value)
        mdd = max(mdd, (mx - total_value) / mx if mx > 0 else 0)

    final = vals[-1][1] if vals else init_usd
    hodl_val = init_usd * (0.5 * prices[-1][2] / p0 + 0.5)
    ret = (final / init_usd - 1) * 100
    hodl_ret = (hodl_val / init_usd - 1) * 100

    return {
        "name": name, "return": ret, "hodl_return": hodl_ret,
        "alpha": ret - hodl_ret, "fee_usdc": fee_usdc, "fee_base": fee_base,
        "rebalances": n_rb, "max_dd": mdd * 100, "final": final,
    }


# ─── Strategy definitions ────────────────────────────────────────────────

def atr_calc(history, period=14):
    if len(history) < period + 1:
        return history[-1][2] * 0.05
    recent = history[-(period+1):]
    trs = []
    for i in range(1, len(recent)):
        h = max(recent[i][2], recent[i-1][2]) * 1.005
        l = min(recent[i][2], recent[i-1][2]) * 0.995
        trs.append(max(h-l, abs(h-recent[i-1][2]), abs(l-recent[i-1][2])))
    return sum(trs[-period:]) / period

def trend_calc(history, lookback=20):
    if len(history) < lookback: return 0
    r = (history[-1][2] - history[-lookback][2]) / history[-lookback][2]
    return max(-1, min(1, r / 0.2))


def make_strategies(cfg):
    t0_dec, t1_dec = cfg["t0_dec"], cfg["t1_dec"]
    invert = cfg["invert_price"]
    ts = cfg["tick_spacing"]

    def _p2t(price):
        return align_tick(price_to_tick(price, t0_dec, t1_dec, invert), ts)

    # 1. Omnis replay
    def make_omnis_replay(rebalances):
        ri = [0]
        def make(price, hist):
            if ri[0] >= len(rebalances):
                return [(_p2t(0.01), _p2t(1e12), 1.0)]
            return [(tl, tu, 1.0 / len(rebalances[ri[0]]["positions"]))
                    for tl, tu in rebalances[ri[0]]["positions"]]
        def should(block, price, pos, hist):
            if ri[0] >= len(rebalances): return False
            if rebalances[ri[0]]["block"] <= block:
                ri[0] += 1
                return True
            return False
        return make, should

    # 2. Baseline ATR (single position)
    def make_baseline():
        lb = [0]
        def make(price, hist):
            a = atr_calc(hist)
            if a <= 0: a = price * 0.05
            return [(_p2t(max(0.01, price - a*2)), _p2t(price + a*2), 1.0)]
        def should(block, price, pos, hist):
            if not pos:
                lb[0] = block; return True
            if block - lb[0] >= 6000:
                lb[0] = block; return True
            return False
        return make, should

    # 3. Multi-layer ATR (Charm-verified 8.3/74.8/16.9 + trend)
    def make_multi_layer():
        lb = [0]
        def make(price, hist):
            t_dir = trend_calc(hist)
            wide_half = price * 0.1785
            nh = price * 0.039
            if t_dir < -0.2: n_lo, n_hi = price-nh*1.4, price+nh*0.6
            elif t_dir > 0.2: n_lo, n_hi = price-nh*0.6, price+nh*1.4
            else: n_lo, n_hi = price-nh, price+nh
            return [
                (align_tick(-887270, ts), align_tick(887270, ts), 0.083),
                (_p2t(max(0.01, price-wide_half)), _p2t(price+wide_half), 0.748),
                (_p2t(max(0.01, n_lo)), _p2t(n_hi), 0.169),
            ]
        def should(block, price, pos, hist):
            if not pos:
                lb[0] = block; return True
            if block - lb[0] < 5000: return False
            # Check if narrow (last position) is out of range
            if pos:
                narrow = pos[-1]
                pa, pb = narrow.pa, narrow.pb
                if price < pa or price > pb:
                    lb[0] = block; return True
                rng = pb - pa
                if rng > 0:
                    pct = (price - pa) / rng
                    if pct < 0.1 or pct > 0.9:
                        lb[0] = block; return True
            return False
        return make, should

    # 4. Charm-style (fixed widths, no trend)
    def make_charm_style():
        lb = [0]
        def make(price, hist):
            return [
                (align_tick(-887270, ts), align_tick(887270, ts), 0.083),
                (_p2t(max(0.01, price*0.8215)), _p2t(price*1.1785), 0.748),
                (_p2t(max(0.01, price*0.961)), _p2t(price*1.039), 0.169),
            ]
        def should(block, price, pos, hist):
            if not pos:
                lb[0] = block; return True
            if block - lb[0] < 80000: return False
            if pos:
                narrow = pos[-1]
                pa, pb = narrow.pa, narrow.pb
                if price < pa or price > pb:
                    lb[0] = block; return True
                if block - lb[0] >= 120000:
                    lb[0] = block; return True
            return False
        return make, should

    return make_omnis_replay, make_baseline, make_multi_layer, make_charm_style


# ─── Main ─────────────────────────────────────────────────────────────────

def run_pool(pool_key):
    cfg = POOLS[pool_key]
    print(f"\n{'='*75}")
    print(f"  {cfg['name']} — Full V3 Liquidity Math Backtest")
    print(f"{'='*75}")

    prices, swaps, omnis_rbs = load_data(cfg)
    p0, pf = prices[0][2], prices[-1][2]
    print(f"  Data: {len(prices)} prices, {len(swaps)} swaps")
    print(f"  Price: ${p0:,.0f} → ${pf:,.0f} ({(pf/p0-1)*100:+.1f}%)")
    print(f"  Omnis rebalances: {len(omnis_rbs)}")

    make_omnis, make_baseline, make_ml, make_charm = make_strategies(cfg)

    results = []

    # 1. Omnis replay
    make_fn, should_fn = make_omnis(omnis_rbs)
    r = run_backtest("omnis_replay", cfg, prices, swaps, make_fn, should_fn)
    results.append(r)

    # 2. Baseline ATR
    make_fn, should_fn = make_baseline()
    r = run_backtest("baseline_atr", cfg, prices, swaps, make_fn, should_fn)
    results.append(r)

    # 3. Multi-layer ATR
    make_fn, should_fn = make_ml()
    r = run_backtest("multi_layer_atr", cfg, prices, swaps, make_fn, should_fn)
    results.append(r)

    # 4. Charm-style
    make_fn, should_fn = make_charm()
    r = run_backtest("charm_style", cfg, prices, swaps, make_fn, should_fn)
    results.append(r)

    # Print results
    hodl = results[0]["hodl_return"]
    print(f"\n  {'Strategy':<22} {'Return':>8} {'Alpha':>8} {'Fee$':>8} {'Rebal':>7} {'MaxDD':>7}")
    print(f"  {'-'*70}")
    for r in results:
        print(f"  {r['name']:<22} {r['return']:>+7.2f}% {r['alpha']:>+7.2f}% "
              f"${r['fee_usdc']:>6.2f} {r['rebalances']:>7} {r['max_dd']:>6.2f}%")
    print(f"  {'-'*70}")
    print(f"  {'report_omnis':<22} {'':>8} {cfg['report_alpha']:>+7.2f}%")
    print(f"  HODL: {hodl:+.2f}%")

    om = next(r for r in results if r["name"] == "omnis_replay")
    ml = next(r for r in results if r["name"] == "multi_layer_atr")
    print(f"\n  📈 Multi-layer vs Omnis: {om['alpha']:+.2f}% → {ml['alpha']:+.2f}% (Δ{ml['alpha']-om['alpha']:+.2f}%)")

    return results


def main():
    print("=" * 75)
    print("Backtest v3-full — Full V3 Liquidity Math (no deploy_ratio)")
    print("=" * 75)

    all_results = {}
    for pool_key in POOLS:
        all_results[pool_key] = run_pool(pool_key)

    # Save
    out = Path(__file__).parent / "data" / "backtest_v3_full_results.json"
    serializable = {k: [{kk: vv for kk, vv in r.items()} for r in v]
                    for k, v in all_results.items()}
    out.write_text(json.dumps(serializable, indent=2))
    print(f"\n💾 {out}")


if __name__ == "__main__":
    main()
