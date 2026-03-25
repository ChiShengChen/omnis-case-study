#!/usr/bin/env python3
"""
Jeff Case Study — 如果 Jeff 用新策略，結果會如何？
==================================================
Jeff 的實際情況（from report）:
  - 入場: 2026-01-19, ~$1,000 USDC, BTC ~$93,252
  - 出場: 2026-03-23, vault 倉位 $719, KAT 獎勵 $52.77
  - 62 天, BTC 跌 ~26%
  - 虧損: $185 (-18.5%)

模擬：同樣的 $1,000、同樣的 62 天，不同策略的結果
"""
import csv, math
from pathlib import Path
import numpy as np

DATA_DIR = Path(__file__).parent / "data"

JEFF_ENTRY_BLOCK = 22_093_953
JEFF_EXIT_BLOCK = 27_522_192
JEFF_CAPITAL = 1000.0
JEFF_DAYS = 62
DEPLOY_RATIO = 0.046  # Omnis vault deploy ratio
VAULT_FEE_SHARE = 0.00158
POOL_FEE = 0.0005
TOKEN0_DEC = 8
TOKEN1_DEC = 6

# Jeff 實際的 KAT 獎勵
JEFF_KAT_REWARD = 52.77
# 報告的全 vault KAT (Jeff 佔 27.83%)
JEFF_VAULT_SHARE = 0.2783

def t2p(tick):
    if tick <= -887270: return 0.01
    if tick >= 887270: return 1e12
    return (1.0001 ** tick) * (10 ** (TOKEN0_DEC - TOKEN1_DEC))

def p2t(price):
    raw = price / (10 ** (TOKEN0_DEC - TOKEN1_DEC))
    return int(math.floor(math.log(max(1e-18, raw)) / math.log(1.0001)))

def align(tick):
    return (tick // 10) * 10

def il_factor(ep, cp, tl, tu):
    pa, pb = t2p(tl), t2p(tu)
    if pa <= 0 or pb <= pa: return 1.0
    pe = max(pa, min(pb, ep))
    sa, sb, se = math.sqrt(pa), math.sqrt(pb), math.sqrt(pe)
    xe, ye = 1/se - 1/sb, se - sa
    ve = xe * pe + ye
    if ve <= 0: return 1.0
    pc = cp
    if pc <= pa: xc, yc = 1/sa - 1/sb, 0
    elif pc >= pb: xc, yc = 0, sb - sa
    else:
        sc = math.sqrt(pc)
        xc, yc = 1/sc - 1/sb, sc - sa
    return (xc * pc + yc) / ve


def load_data():
    prices = []
    with open(DATA_DIR / "price_series.csv") as f:
        for row in csv.DictReader(f):
            b = int(row["block"])
            if JEFF_ENTRY_BLOCK <= b <= JEFF_EXIT_BLOCK:
                prices.append((b, int(row["tick"]), float(row["price"])))

    swaps = []
    with open(DATA_DIR / "swaps.csv") as f:
        for row in csv.DictReader(f):
            b = int(row["block"])
            if JEFF_ENTRY_BLOCK <= b <= JEFF_EXIT_BLOCK:
                swaps.append((b, int(row["tick"]), abs(int(row["amount1"])) / 1e6))

    # Omnis rebalances in Jeff's period
    omnis = "0x5977767ef6324864f170318681eccb82315f8761"
    tx_burns, tx_mints = {}, {}
    with open(DATA_DIR / "burns.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == omnis:
                b = int(row["block"])
                if JEFF_ENTRY_BLOCK <= b <= JEFF_EXIT_BLOCK:
                    tx_burns.setdefault(row["tx_hash"], []).append(row)
    with open(DATA_DIR / "mints.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == omnis:
                b = int(row["block"])
                if JEFF_ENTRY_BLOCK <= b <= JEFF_EXIT_BLOCK:
                    tx_mints.setdefault(row["tx_hash"], []).append(row)

    omnis_rbs = []
    for tx in sorted(set(tx_burns) & set(tx_mints), key=lambda t: int(tx_mints[t][0]["block"])):
        m = tx_mints[tx][0]
        omnis_rbs.append({
            "block": int(m["block"]),
            "positions": [(int(m["tickLower"]), int(m["tickUpper"]))],
        })

    return prices, swaps, omnis_rbs


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
    capital = JEFF_CAPITAL
    p0 = prices[0][2]
    pos = None
    pos_ep = p0
    pos_cap = capital
    fee = 0.0
    si = 0
    history = []
    n_rb = 0

    for block, tick, price in prices:
        history.append((block, tick, price))
        if should_fn(block, price, pos, history):
            if pos is not None:
                dep = sum(pos_cap * deploy_ratio * w * il_factor(pos_ep, price, tl, tu)
                          for tl, tu, w in pos)
                idle = pos_cap * (1 - deploy_ratio) * (0.5 * price / pos_ep + 0.5)
                capital = dep + idle + fee
                fee = 0.0
            pos = make_fn(price, history)
            pos_ep = price
            pos_cap = capital
            n_rb += 1

        if pos:
            while si < len(swaps) and swaps[si][0] <= block:
                _, stk, vol = swaps[si]
                for tl, tu, w in pos:
                    if tl <= stk < tu:
                        fee += vol * POOL_FEE * VAULT_FEE_SHARE * w
                si += 1

    # Final value
    if pos:
        dep = sum(pos_cap * deploy_ratio * w * il_factor(pos_ep, prices[-1][2], tl, tu)
                  for tl, tu, w in pos)
        idle = pos_cap * (1 - deploy_ratio) * (0.5 * prices[-1][2] / pos_ep + 0.5)
        final = dep + idle + fee
    else:
        final = capital

    hodl = JEFF_CAPITAL * (0.5 * prices[-1][2] / p0 + 0.5)
    ret = (final / JEFF_CAPITAL - 1) * 100
    hodl_ret = (hodl / JEFF_CAPITAL - 1) * 100

    return {
        "name": name, "final": final, "return": ret,
        "hodl_return": hodl_ret, "alpha": ret - hodl_ret,
        "fee": fee, "rebalances": n_rb,
    }


def main():
    prices, swaps, omnis_rbs = load_data()
    p0, pf = prices[0][2], prices[-1][2]

    print("=" * 70)
    print("Jeff Case Study — 新策略 vs 實際結果")
    print("=" * 70)
    print(f"入場: ${p0:,.0f}  →  出場: ${pf:,.0f}  BTC {(pf/p0-1)*100:+.1f}%")
    print(f"期間: {JEFF_DAYS} 天, {len(prices)} 價格點, {len(swaps)} swaps")
    print(f"投入: ${JEFF_CAPITAL:,.0f}")
    print()

    results = []

    # 1. Omnis 實際操作重放
    ri = [0]
    def omnis_make(price, hist):
        if ri[0] >= len(omnis_rbs): return [(align(-887270), align(887270), 1.0)]
        tl, tu = omnis_rbs[ri[0]]["positions"][0]
        return [(tl, tu, 1.0)]
    def omnis_should(block, price, pos, hist):
        if ri[0] >= len(omnis_rbs): return False
        if omnis_rbs[ri[0]]["block"] <= block:
            ri[0] += 1
            return True
        return False
    results.append(run("omnis_actual", prices, swaps, omnis_make, omnis_should, DEPLOY_RATIO))

    # 2. Multi-layer (Charm 參數 + 趨勢偏移)
    lb = [0]
    def ml_make(price, hist):
        t_dir = trend(hist)
        wide_half = price * 0.1785
        narrow_half = price * 0.039
        if t_dir < -0.2:
            n_lo = price * (1 - narrow_half/price * 1.4)
            n_hi = price * (1 + narrow_half/price * 0.6)
        elif t_dir > 0.2:
            n_lo = price * (1 - narrow_half/price * 0.6)
            n_hi = price * (1 + narrow_half/price * 1.4)
        else:
            n_lo, n_hi = price - narrow_half, price + narrow_half
        return [
            (align(-887270), align(887270), 0.083),
            (align(p2t(max(1, price - wide_half))), align(p2t(price + wide_half)), 0.748),
            (align(p2t(max(1, n_lo))), align(p2t(n_hi)), 0.169),
        ]
    def ml_should(block, price, pos, hist):
        if pos is None: lb[0] = block; return True
        if block - lb[0] < 5000: return False
        narrow = pos[2] if len(pos) >= 3 else pos[0]
        pl, pu = t2p(narrow[0]), t2p(narrow[1])
        if price < pl or price > pu: lb[0] = block; return True
        rng = pu - pl
        if rng > 0:
            pct = (price - pl) / rng
            if pct < 0.1 or pct > 0.9: lb[0] = block; return True
        return False
    results.append(run("multi_layer", prices, swaps, ml_make, ml_should, DEPLOY_RATIO))

    # 3. HODL (不做 LP，50/50 持有)
    hodl_val = JEFF_CAPITAL * (0.5 * pf / p0 + 0.5)

    # ── 結果 ──
    print("=" * 70)
    print(f"{'':20} {'最終價值':>10} {'回報':>8} {'Alpha':>8} {'Rebal':>7}")
    print("-" * 70)

    for r in results:
        print(f"{r['name']:20} ${r['final']:>8,.0f} {r['return']:>+7.1f}% {r['alpha']:>+7.2f}% {r['rebalances']:>7}")

    print(f"{'hodl':20} ${hodl_val:>8,.0f} {(hodl_val/JEFF_CAPITAL-1)*100:>+7.1f}%")
    print("-" * 70)
    print(f"{'jeff_actual (報告)':20} ${'719':>8} {'-28.1':>7}%")
    print(f"{'jeff_actual+KAT':20} ${'815':>8} {'-18.5':>7}%  (含 $52.77 KAT)")
    print("=" * 70)

    # 含 KAT 獎勵的比較
    # Jeff 的 KAT 獎勵跟 vault 份額和時間成正比，策略不影響 KAT 分配
    print(f"\n含 KAT 獎勵 (${JEFF_KAT_REWARD:.0f}) 後：")
    for r in results:
        total = r["final"] + JEFF_KAT_REWARD
        total_ret = (total / JEFF_CAPITAL - 1) * 100
        apr = total_ret / JEFF_DAYS * 365
        print(f"  {r['name']:20} ${total:>8,.0f} ({total_ret:>+6.1f}%)  年化 APR: {apr:>+7.1f}%")

    jeff_total = 815
    jeff_ret = (jeff_total / JEFF_CAPITAL - 1) * 100
    jeff_apr = jeff_ret / JEFF_DAYS * 365
    print(f"  {'jeff_actual':20} ${jeff_total:>8,.0f} ({jeff_ret:>+6.1f}%)  年化 APR: {jeff_apr:>+7.1f}%")

    hodl_apr = (hodl_val / JEFF_CAPITAL - 1) * 100 / JEFF_DAYS * 365
    print(f"  {'hodl':20} ${hodl_val:>8,.0f} ({(hodl_val/JEFF_CAPITAL-1)*100:>+6.1f}%)  年化 APR: {hodl_apr:>+7.1f}%")

    # 改善幅度
    ml = next(r for r in results if r["name"] == "multi_layer")
    ml_total = ml["final"] + JEFF_KAT_REWARD
    improvement = ml_total - jeff_total
    print(f"\n💰 新策略 vs Jeff 實際: ${improvement:+,.0f} (Jeff 多拿回 ${abs(improvement):,.0f})")


if __name__ == "__main__":
    main()
