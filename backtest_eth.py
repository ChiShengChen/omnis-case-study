#!/usr/bin/env python3
"""
USDC-ETH Backtest — 驗證多層策略對 ETH 池的效果
================================================
報告 benchmark:
  Omnis alpha: -10.86% (70 天, 678 rebalances)
  Charm alpha: -1.85%  (同池 Steer 競品: -11.95%)
  ETH: +4.3% ($2,077 → $2,165)

Pool:  0x2a2c512beaa8eb15495726c235472d82effb7a6b
Token0: vbUSDC (6 dec), Token1: vbETH (18 dec)
"""
import csv, math, json
from pathlib import Path
import numpy as np

DATA_DIR = Path(__file__).parent / "data_eth"

TOKEN0_DEC = 6   # vbUSDC
TOKEN1_DEC = 18  # vbETH
POOL_FEE = 0.0005
TICK_SPACING = 10
INITIAL_CAPITAL = 2134.0   # 報告 TVL
VAULT_FEE_SHARE = 0.00133  # 報告: 0.133% fee capture rate
DEPLOY_RATIO = 0.024       # ETH vault: ~$50 deployed / $2,134 TVL

OMNIS = "0x811b8c618716ca62b092b67c09e55361ae6df429"

REPORT_OMNIS_ALPHA = -10.86
REPORT_CHARM_ALPHA = -1.85

def t2p(tick):
    """tick → USDC per ETH"""
    if tick <= -887270: return 0.01
    if tick >= 887270: return 1e12
    raw = (1.0001 ** tick) * (10 ** (TOKEN0_DEC - TOKEN1_DEC))
    # raw = ETH per USDC → invert
    return 1.0 / raw if raw > 0 else 0

def p2t(price_usdc_per_eth):
    """USDC per ETH → tick"""
    if price_usdc_per_eth <= 0: return -887270
    # tick → price: raw = 1.0001^tick * 10^(6-18) = ETH per USDC
    # price = 1/raw → raw = 1/price
    raw = 1.0 / price_usdc_per_eth
    raw_no_dec = raw / (10 ** (TOKEN0_DEC - TOKEN1_DEC))
    if raw_no_dec <= 0: return -887270
    return int(math.floor(math.log(raw_no_dec) / math.log(1.0001)))

def align(tick):
    return (tick // TICK_SPACING) * TICK_SPACING

def il_factor(ep, cp, tl, tu):
    pa, pb = t2p(tl), t2p(tu)
    # 修正：USDC-ETH 池中 tickLower 對應較高的 USDC/ETH 價格
    # 因為 token0=USDC → tick 增加 = ETH per USDC 增加 = USDC per ETH 減少
    # 確保 pa < pb 給 V3 公式
    if pa > pb:
        pa, pb = pb, pa
    if pa <= 0 or pb <= pa: return 1.0
    pe = max(pa, min(pb, ep))
    sa, sb, se = math.sqrt(pa), math.sqrt(pb), math.sqrt(pe)
    xe, ye = 1/se - 1/sb, se - sa
    ve = xe * pe + ye
    if ve <= 0: return 1.0
    if cp <= pa: xc, yc = 1/sa - 1/sb, 0
    elif cp >= pb: xc, yc = 0, sb - sa
    else:
        sc = math.sqrt(cp)
        xc, yc = 1/sc - 1/sb, sc - sa
    return (xc * cp + yc) / ve


def tick_in_range(swap_tick, tl, tu):
    """判斷 swap tick 是否在 position range 內（處理反向 token order）"""
    # 對於 USDC-ETH: tickLower < tickUpper 在 tick 空間中
    # swap_tick 在 [tickLower, tickUpper) 內即為 in-range
    return tl <= swap_tick < tu

def load_data():
    prices = []
    with open(DATA_DIR / "price_series.csv") as f:
        for row in csv.DictReader(f):
            prices.append((int(row["block"]), int(row["tick"]), float(row["price"])))
    prices.sort()

    swaps = []
    with open(DATA_DIR / "swaps.csv") as f:
        for row in csv.DictReader(f):
            swaps.append((int(row["block"]), int(row["tick"]),
                          abs(int(row["amount0"])) / 1e6))  # USDC volume (token0)
    swaps.sort()

    omnis_vault = OMNIS.lower()
    tx_burns, tx_mints = {}, {}
    with open(DATA_DIR / "burns.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == omnis_vault:
                tx_burns.setdefault(row["tx_hash"], []).append(row)
    with open(DATA_DIR / "mints.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == omnis_vault:
                tx_mints.setdefault(row["tx_hash"], []).append(row)

    rbs = []
    for tx in sorted(set(tx_burns) & set(tx_mints), key=lambda t: int(tx_mints[t][0]["block"])):
        m = tx_mints[tx][0]
        rbs.append({"block": int(m["block"]),
                     "positions": [(int(m["tickLower"]), int(m["tickUpper"]))]})
    return prices, swaps, rbs


def atr(history, period=14):
    if len(history) < period + 1: return history[-1][2] * 0.05
    recent = history[-(period+1):]
    trs = []
    for i in range(1, len(recent)):
        h = max(recent[i][2], recent[i-1][2]) * 1.005
        l = min(recent[i][2], recent[i-1][2]) * 0.995
        trs.append(max(h-l, abs(h-recent[i-1][2]), abs(l-recent[i-1][2])))
    return sum(trs[-period:]) / period

def trend(history, lookback=20):
    if len(history) < lookback: return 0
    r = (history[-1][2] - history[-lookback][2]) / history[-lookback][2]
    return max(-1, min(1, r / 0.2))


def run(name, prices, swaps, make_fn, should_fn, deploy_ratio):
    capital = INITIAL_CAPITAL
    p0 = prices[0][2]
    pos = None; pos_ep = p0; pos_cap = capital
    fee = 0.0; si = 0; history = []; n_rb = 0
    vals = []; mx = capital; mdd = 0

    for block, tick, price in prices:
        history.append((block, tick, price))
        if should_fn(block, price, pos, history):
            if pos:
                dep = sum(pos_cap * deploy_ratio * w * il_factor(pos_ep, price, tl, tu)
                          for tl, tu, w in pos)
                idle = pos_cap * (1-deploy_ratio) * (0.5 * price/pos_ep + 0.5)
                capital = dep + idle + fee; fee = 0
            pos = make_fn(price, history)
            pos_ep = price; pos_cap = capital; n_rb += 1

        if pos:
            while si < len(swaps) and swaps[si][0] <= block:
                _, stk, vol = swaps[si]
                for tl, tu, w in pos:
                    if tl <= stk < tu:
                        fee += vol * POOL_FEE * VAULT_FEE_SHARE * w
                si += 1

        if pos:
            dep = sum(pos_cap * deploy_ratio * w * il_factor(pos_ep, price, tl, tu)
                      for tl, tu, w in pos)
            idle = pos_cap * (1-deploy_ratio) * (0.5 * price/pos_ep + 0.5)
            cv = dep + idle + fee
        else:
            cv = capital
        vals.append((block, cv))
        mx = max(mx, cv); mdd = max(mdd, (mx-cv)/mx if mx > 0 else 0)

    final = vals[-1][1] if vals else capital
    hodl = INITIAL_CAPITAL * (0.5 * prices[-1][2]/p0 + 0.5)
    ret = (final/INITIAL_CAPITAL - 1) * 100
    hodl_ret = (hodl/INITIAL_CAPITAL - 1) * 100
    return {"name": name, "return": ret, "hodl_return": hodl_ret,
            "alpha": ret - hodl_ret, "fee": fee, "rebalances": n_rb,
            "max_dd": mdd * 100, "final": final}


def main():
    print("=" * 75)
    print("USDC-ETH Backtest — Multi-Layer Strategy Validation")
    print("=" * 75)

    prices, swaps, omnis_rbs = load_data()
    p0, pf = prices[0][2], prices[-1][2]
    print(f"Data: {len(prices)} prices, {len(swaps)} swaps")
    print(f"ETH: ${p0:,.0f} → ${pf:,.0f} ({(pf/p0-1)*100:+.1f}%)")
    print(f"Omnis rebalances: {len(omnis_rbs)}")
    print()

    results = []

    # 1. Omnis replay
    ri = [0]
    def om_make(price, hist):
        if ri[0] >= len(omnis_rbs): return [(align(-887270), align(887270), 1.0)]
        return [(omnis_rbs[ri[0]]["positions"][0][0], omnis_rbs[ri[0]]["positions"][0][1], 1.0)]
    def om_should(block, price, pos, hist):
        if ri[0] >= len(omnis_rbs): return False
        if omnis_rbs[ri[0]]["block"] <= block: ri[0] += 1; return True
        return False
    results.append(run("omnis_replay", prices, swaps, om_make, om_should, DEPLOY_RATIO))

    # 2. Baseline ATR
    lb1 = [0]
    def bl_make(price, hist):
        a = atr(hist); a = a if a > 0 else price*0.05
        return [(align(p2t(max(1, price-a*2))), align(p2t(price+a*2)), 1.0)]
    def bl_should(block, price, pos, hist):
        if pos is None: lb1[0]=block; return True
        if block-lb1[0] >= 6000: lb1[0]=block; return True
        return False
    results.append(run("baseline_atr", prices, swaps, bl_make, bl_should, DEPLOY_RATIO))

    # 3. Multi-layer ATR (Charm-verified: 8.3/74.8/16.9)
    lb2 = [0]
    def ml_make(price, hist):
        t_dir = trend(hist)
        wide_half = price * 0.1785
        nh = price * 0.039
        if t_dir < -0.2: n_lo, n_hi = price-nh*1.4, price+nh*0.6
        elif t_dir > 0.2: n_lo, n_hi = price-nh*0.6, price+nh*1.4
        else: n_lo, n_hi = price-nh, price+nh
        return [
            (align(-887270), align(887270), 0.083),
            (align(p2t(max(1, price-wide_half))), align(p2t(price+wide_half)), 0.748),
            (align(p2t(max(1, n_lo))), align(p2t(n_hi)), 0.169),
        ]
    def ml_should(block, price, pos, hist):
        if pos is None: lb2[0]=block; return True
        if block-lb2[0] < 5000: return False
        narrow = pos[2] if len(pos) >= 3 else pos[0]
        pl, pu = t2p(narrow[0]), t2p(narrow[1])
        if pl > pu: pl, pu = pu, pl  # 修正 token order
        if price < pl or price > pu: lb2[0]=block; return True
        rng = pu - pl
        if rng > 0:
            pct = (price-pl)/rng
            if pct < 0.1 or pct > 0.9: lb2[0]=block; return True
        return False
    results.append(run("multi_layer_atr", prices, swaps, ml_make, ml_should, DEPLOY_RATIO))

    # 4. Charm-style (fixed widths, no trend)
    lb3 = [0]
    def cs_make(price, hist):
        return [
            (align(-887270), align(887270), 0.083),
            (align(p2t(max(1, price*0.8215))), align(p2t(price*1.1785)), 0.748),
            (align(p2t(max(1, price*0.961))), align(p2t(price*1.039)), 0.169),
        ]
    def cs_should(block, price, pos, hist):
        if pos is None: lb3[0]=block; return True
        if block-lb3[0] < 80000: return False
        narrow = pos[2] if len(pos) >= 3 else pos[0]
        pl, pu = t2p(narrow[0]), t2p(narrow[1])
        if pl > pu: pl, pu = pu, pl  # 修正 token order
        if price < pl or price > pu: lb3[0]=block; return True
        if block-lb3[0] >= 120000: lb3[0]=block; return True
        return False
    results.append(run("charm_style", prices, swaps, cs_make, cs_should, DEPLOY_RATIO))

    # Results
    hodl_ret = results[0]["hodl_return"]
    print("=" * 75)
    print(f"RESULTS  |  HODL: {hodl_ret:+.2f}%  |  ETH {(pf/p0-1)*100:+.1f}%")
    print("=" * 75)
    print(f"{'Strategy':<22} {'Return':>8} {'Alpha':>8} {'Fee':>8} {'Rebal':>7} {'MaxDD':>7}")
    print("-" * 75)
    for r in results:
        print(f"{r['name']:<22} {r['return']:>+7.2f}% {r['alpha']:>+7.2f}% "
              f"${r['fee']:>6.2f} {r['rebalances']:>7} {r['max_dd']:>6.2f}%")
    print("-" * 75)
    print(f"{'report_omnis':<22} {'':>8} {REPORT_OMNIS_ALPHA:>+7.2f}%")
    print(f"{'report_charm':<22} {'':>8} {REPORT_CHARM_ALPHA:>+7.2f}%")
    print("=" * 75)

    om = next(r for r in results if r["name"] == "omnis_replay")
    ml = next(r for r in results if r["name"] == "multi_layer_atr")
    print(f"\n📈 Multi-layer vs Omnis: {om['alpha']:+.2f}% → {ml['alpha']:+.2f}% (Δ{ml['alpha']-om['alpha']:+.2f}%)")

    out = DATA_DIR / "backtest_eth_results.json"
    out.write_text(json.dumps({"results": results}, indent=2))
    print(f"💾 {out}")

if __name__ == "__main__":
    main()
