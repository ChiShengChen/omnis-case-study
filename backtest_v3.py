#!/usr/bin/env python3
"""
Backtest v3 — 公平比較：用 Charm 的真實策略參數 + Omnis 的 TVL/fee
==================================================================
解決 TVL 差異問題：所有策略都用同樣的 $2,600 TVL 和 0.158% fee share，
只比較策略本身（tick 邏輯、分配比例、rebalance 頻率）的差異。

Charm 實際策略參數（從鏈上數據提取）：
  - Full-range:  8.3% 資金, [-887270, 887270]
  - Wide:       74.8% 資金, ±17.85% width (固定 35.7% total width)
  - Narrow:     16.9% 資金, ±3.9% width (固定 7.8% total width)
  - Rebalance:  ~每 22 hrs (median 82,592 blocks)
"""

import csv, math, bisect, json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import numpy as np

DATA_DIR = Path(__file__).parent / "data"

TOKEN0_DEC = 8
TOKEN1_DEC = 6
POOL_FEE = 0.0005
TICK_SPACING = 10
INITIAL_CAPITAL = 2600.0
VAULT_FEE_SHARE = 0.00158  # Omnis calibrated

OMNIS = "0x5977767ef6324864f170318681eccb82315f8761"
CHARM = "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff"

# ─── 工具 ────────────────────────────────────────────────────────────────

def t2p(tick):
    if tick <= -887270: return 0.01
    if tick >= 887270: return 1e12
    return (1.0001 ** tick) * (10 ** (TOKEN0_DEC - TOKEN1_DEC))

def p2t(price):
    raw = price / (10 ** (TOKEN0_DEC - TOKEN1_DEC))
    return int(math.floor(math.log(max(1e-18, raw)) / math.log(1.0001)))

def align(tick):
    return (tick // TICK_SPACING) * TICK_SPACING

# ─── 數據 ────────────────────────────────────────────────────────────────

def load_prices():
    pts = []
    with open(DATA_DIR / "price_series.csv") as f:
        for row in csv.DictReader(f):
            pts.append((int(row["block"]), int(row["tick"]), float(row["price"])))
    pts.sort()
    return pts

def load_swaps():
    swaps = []
    with open(DATA_DIR / "swaps.csv") as f:
        for row in csv.DictReader(f):
            swaps.append((int(row["block"]), int(row["tick"]),
                          abs(int(row["amount1"])) / 1e6))  # USDC volume
    swaps.sort()
    return swaps

def load_rebalances(vault):
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

    rbs = []
    for tx in sorted(set(tx_burns) & set(tx_mints), key=lambda t: int(tx_mints[t][0]["block"])):
        mints = sorted(tx_mints[tx], key=lambda m: int(m["tickLower"]))
        block = int(mints[0]["block"])
        positions = [(int(m["tickLower"]), int(m["tickUpper"])) for m in mints]
        rbs.append({"block": block, "positions": positions})
    return rbs

# ─── IL Model ────────────────────────────────────────────────────────────

def il_factor(entry_price, current_price, tl, tu):
    pa, pb = t2p(tl), t2p(tu)
    if pa <= 0 or pb <= pa: return 1.0
    pe = max(pa, min(pb, entry_price))
    sa, sb, se = math.sqrt(pa), math.sqrt(pb), math.sqrt(pe)
    xe, ye = 1/se - 1/sb, se - sa
    ve = xe * pe + ye
    if ve <= 0: return 1.0
    pc = current_price
    if pc <= pa:
        xc, yc = 1/sa - 1/sb, 0
    elif pc >= pb:
        xc, yc = 0, sb - sa
    else:
        sc = math.sqrt(pc)
        xc, yc = 1/sc - 1/sb, sc - sa
    return (xc * pc + yc) / ve

# ─── Backtest Core ───────────────────────────────────────────────────────

def backtest(name, prices, swaps, make_positions_fn, should_rebalance_fn,
             deploy_ratio=0.046):
    """
    positions = [(tickLower, tickUpper, weight_fraction), ...]
    weight_fraction 加總 = 1.0，代表部署資金中各 position 的分配
    deploy_ratio = 部署到集中區間的比例（其餘 idle = HODL）
    """
    capital = INITIAL_CAPITAL
    p0 = prices[0][2]  # initial price
    pos = None     # current positions list
    pos_ep = p0    # entry price
    pos_cap = capital  # capital at entry
    fee = 0.0
    si = 0         # swap index
    history = []   # price history for strategy
    vals = []
    mx, mdd = capital, 0

    for block, tick, price in prices:
        history.append((block, tick, price))

        # Check rebalance
        if should_rebalance_fn(block, price, pos, history):
            # Settle old position
            if pos is not None:
                dep_val = sum(
                    pos_cap * deploy_ratio * w * il_factor(pos_ep, price, tl, tu)
                    for tl, tu, w in pos
                )
                idle_val = pos_cap * (1 - deploy_ratio) * (0.5 * price / pos_ep + 0.5)
                capital = dep_val + idle_val + fee
                fee = 0.0

            pos = make_positions_fn(price, history)
            pos_ep = price
            pos_cap = capital

        # Accumulate fees
        if pos:
            while si < len(swaps) and swaps[si][0] <= block:
                _, stk, vol = swaps[si]
                for tl, tu, w in pos:
                    if tl <= stk < tu:
                        fee += vol * POOL_FEE * VAULT_FEE_SHARE * w
                si += 1

        # Current value
        if pos:
            dep_val = sum(
                pos_cap * deploy_ratio * w * il_factor(pos_ep, price, tl, tu)
                for tl, tu, w in pos
            )
            idle_val = pos_cap * (1 - deploy_ratio) * (0.5 * price / pos_ep + 0.5)
            cv = dep_val + idle_val + fee
        else:
            cv = capital

        vals.append((block, cv))
        mx = max(mx, cv)
        mdd = max(mdd, (mx - cv) / mx if mx > 0 else 0)

    final = vals[-1][1]
    hodl = INITIAL_CAPITAL * (0.5 * prices[-1][2] / p0 + 0.5)
    ret = (final / INITIAL_CAPITAL - 1) * 100
    hodl_ret = (hodl / INITIAL_CAPITAL - 1) * 100
    n_rb = sum(1 for i in range(1, len(vals)) if any(
        should_rebalance_fn(prices[i][0], prices[i][2], None, history[:i+1])
        for _ in [0]  # dummy
    )) if False else 0  # count below

    return {
        "name": name, "return": ret, "hodl_return": hodl_ret,
        "alpha": ret - hodl_ret, "fee": fee, "max_dd": mdd * 100,
        "final": final, "vals": vals,
    }


# ─── 策略定義 ─────────────────────────────────────────────────────────────

def atr(history, period=14):
    if len(history) < period + 1:
        return history[-1][2] * 0.05
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


# 1. Omnis replay (actual ticks)
def make_omnis_replay(rebalances):
    idx = [0]
    def make(price, hist):
        if idx[0] >= len(rebalances): return [(align(-887270), align(887270), 1.0)]
        rb = rebalances[idx[0]]
        tl, tu = rb["positions"][0]
        return [(tl, tu, 1.0)]
    def should(block, price, pos, hist):
        if idx[0] >= len(rebalances): return False
        if rebalances[idx[0]]["block"] <= block:
            idx[0] += 1
            return True
        return False
    return make, should

# 2. Charm-style (real Charm params: 8.3/74.8/16.9, widths 35.7%/7.8%, ~22hrs)
def make_charm_style():
    last_block = [0]
    MIN_INTERVAL = 80000  # ~22 hrs
    def make(price, hist):
        # Charm's fixed widths
        wide_half = price * 0.1785   # 35.7% / 2
        narrow_half = price * 0.039  # 7.8% / 2
        return [
            (align(-887270), align(887270), 0.083),           # full-range 8.3%
            (align(p2t(price - wide_half)), align(p2t(price + wide_half)), 0.748),   # wide 74.8%
            (align(p2t(price - narrow_half)), align(p2t(price + narrow_half)), 0.169),  # narrow 16.9%
        ]
    def should(block, price, pos, hist):
        if pos is None: return True
        if block - last_block[0] < MIN_INTERVAL: return False
        # Charm rebalances when narrow goes out of range
        narrow = pos[2] if len(pos) >= 3 else pos[0]
        pl, pu = t2p(narrow[0]), t2p(narrow[1])
        if price < pl or price > pu:
            last_block[0] = block
            return True
        # Also rebalance at ~22hr intervals even if in range
        if block - last_block[0] >= MIN_INTERVAL * 1.5:
            last_block[0] = block
            return True
        return False
    return make, should

# 3. Baseline ATR (Omnis current: single position, ATR×2.0)
def make_baseline():
    last_block = [0]
    def make(price, hist):
        a = atr(hist)
        if a <= 0: a = price * 0.05
        return [(align(p2t(max(1, price - a*2))), align(p2t(price + a*2)), 1.0)]
    def should(block, price, pos, hist):
        if pos is None: return True
        return block - last_block[0] >= 6000 and (last_block.__setitem__(0, block) or True)
    # fix: track block
    last_b = [0]
    def should2(block, price, pos, hist):
        if pos is None:
            last_b[0] = block
            return True
        if block - last_b[0] >= 6000:
            last_b[0] = block
            return True
        return False
    return make, should2

# 4. Our multi-layer ATR (Charm-inspired but with trend awareness)
def make_multi_layer():
    last_block = [0]
    def make(price, hist):
        a = atr(hist)
        if a <= 0: a = price * 0.05
        t_dir = trend(hist)
        # Asymmetric narrow based on trend
        if t_dir < -0.2:
            n_lo = price - a * 1.5 * 1.4
            n_hi = price + a * 1.5 * 0.6
        elif t_dir > 0.2:
            n_lo = price - a * 1.5 * 0.6
            n_hi = price + a * 1.5 * 1.4
        else:
            n_lo = price - a * 1.5
            n_hi = price + a * 1.5
        return [
            (align(-887270), align(887270), 0.083),                              # 8.3%
            (align(p2t(max(1, price - a*4))), align(p2t(price + a*4)), 0.748),   # 74.8%
            (align(p2t(max(1, n_lo))), align(p2t(n_hi)), 0.169),                 # 16.9%
        ]
    def should(block, price, pos, hist):
        if pos is None:
            last_block[0] = block
            return True
        if block - last_block[0] < 5000: return False
        if len(pos) >= 3:
            pl, pu = t2p(pos[2][0]), t2p(pos[2][1])
        else:
            pl, pu = t2p(pos[0][0]), t2p(pos[0][1])
        if price < pl or price > pu:
            last_block[0] = block
            return True
        rng = pu - pl
        if rng > 0:
            pct = (price - pl) / rng
            if pct < 0.1 or pct > 0.9:
                last_block[0] = block
                return True
        return False
    return make, should

# 5. Multi-layer with Charm's EXACT allocation (for direct comparison)
def make_multi_layer_charm_alloc():
    """Same as multi-layer but using Charm's proven 8.3/74.8/16.9 split AND fixed widths"""
    last_block = [0]
    def make(price, hist):
        t_dir = trend(hist)
        wide_half = price * 0.1785   # 35.7% / 2 (same as Charm)
        # Narrow with trend shift (our improvement over Charm)
        base_narrow = price * 0.039  # 7.8% / 2
        if t_dir < -0.2:
            n_lo = price - base_narrow * 1.4
            n_hi = price + base_narrow * 0.6
        elif t_dir > 0.2:
            n_lo = price - base_narrow * 0.6
            n_hi = price + base_narrow * 1.4
        else:
            n_lo = price - base_narrow
            n_hi = price + base_narrow
        return [
            (align(-887270), align(887270), 0.083),
            (align(p2t(max(1, price - wide_half))), align(p2t(price + wide_half)), 0.748),
            (align(p2t(max(1, n_lo))), align(p2t(n_hi)), 0.169),
        ]
    def should(block, price, pos, hist):
        if pos is None:
            last_block[0] = block
            return True
        if block - last_block[0] < 5000: return False
        if len(pos) >= 3:
            pl, pu = t2p(pos[2][0]), t2p(pos[2][1])
        else:
            pl, pu = t2p(pos[0][0]), t2p(pos[0][1])
        if price < pl or price > pu:
            last_block[0] = block
            return True
        rng = pu - pl
        if rng > 0:
            pct = (price - pl) / rng
            if pct < 0.1 or pct > 0.9:
                last_block[0] = block
                return True
        return False
    return make, should


# ─── Main ────────────────────────────────────────────────────────────────

def run_backtest(name, prices, swaps, make_fn, should_fn, deploy_ratio):
    """Wrapper that also counts rebalances"""
    capital = INITIAL_CAPITAL
    p0 = prices[0][2]
    pos = None
    pos_ep = p0
    pos_cap = capital
    fee = 0.0
    si = 0
    history = []
    vals = []
    mx, mdd = capital, 0
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

        if pos:
            dep = sum(pos_cap * deploy_ratio * w * il_factor(pos_ep, price, tl, tu)
                      for tl, tu, w in pos)
            idle = pos_cap * (1 - deploy_ratio) * (0.5 * price / pos_ep + 0.5)
            cv = dep + idle + fee
        else:
            cv = capital

        vals.append((block, cv))
        mx = max(mx, cv)
        mdd = max(mdd, (mx - cv) / mx if mx > 0 else 0)

    final = vals[-1][1]
    hodl = INITIAL_CAPITAL * (0.5 * prices[-1][2] / p0 + 0.5)
    ret = (final / INITIAL_CAPITAL - 1) * 100
    hodl_ret = (hodl / INITIAL_CAPITAL - 1) * 100

    return {
        "name": name, "return": ret, "hodl_return": hodl_ret,
        "alpha": ret - hodl_ret, "fee": fee, "rebalances": n_rb,
        "max_dd": mdd * 100, "final": final,
    }


def main():
    print("=" * 78)
    print("Backtest v3 — Fair Comparison (same TVL, same fee share)")
    print("=" * 78)

    prices = load_prices()
    swaps = load_swaps()
    omnis_rb = load_rebalances(OMNIS)
    print(f"Data: {len(prices)} prices, {len(swaps)} swaps, BTC ${prices[0][2]:,.0f}→${prices[-1][2]:,.0f}")
    print(f"Deploy ratio: 4.6% (Omnis actual), Fee share: 0.158%\n")

    DEPLOY = 0.046
    results = []

    # 1. Omnis actual replay
    make, should = make_omnis_replay(omnis_rb)
    r = run_backtest("omnis_replay", prices, swaps, make, should, DEPLOY)
    results.append(r)

    # 2. Charm-style (Charm's proven parameters, our TVL)
    make, should = make_charm_style()
    r = run_backtest("charm_style", prices, swaps, make, should, DEPLOY)
    results.append(r)

    # 3. Baseline ATR (current Omnis strategy, simulated)
    make, should = make_baseline()
    r = run_backtest("baseline_atr", prices, swaps, make, should, DEPLOY)
    results.append(r)

    # 4. Multi-layer ATR (our new strategy, ATR-based widths)
    make, should = make_multi_layer()
    r = run_backtest("multi_layer_atr", prices, swaps, make, should, DEPLOY)
    results.append(r)

    # 5. Multi-layer with Charm's exact allocation + our trend awareness
    make, should = make_multi_layer_charm_alloc()
    r = run_backtest("ml_charm_trend", prices, swaps, make, should, DEPLOY)
    results.append(r)

    # Results
    hodl_ret = results[0]["hodl_return"]
    print("=" * 78)
    print(f"RESULTS  |  HODL: {hodl_ret:+.2f}%  |  Deploy: {DEPLOY*100:.1f}%  |  Fee share: {VAULT_FEE_SHARE*100:.3f}%")
    print("=" * 78)
    print(f"{'Strategy':<22} {'Return':>8} {'Alpha':>8} {'Fee':>8} {'Rebal':>7} {'MaxDD':>7}")
    print("-" * 78)
    for r in results:
        print(f"{r['name']:<22} {r['return']:>+7.2f}% {r['alpha']:>+7.2f}% "
              f"${r['fee']:>6.2f} {r['rebalances']:>7} {r['max_dd']:>6.2f}%")
    print("-" * 78)
    print(f"{'report_omnis':<22} {'':>8} {'-3.65':>7}% {'$142.81':>8} {'1,306':>7} {'25.61':>6}%")
    print(f"{'report_charm':<22} {'':>8} {'+1.50':>7}% {'$22,555':>8} {'516':>7} {'25.23':>6}%")
    print("=" * 78)

    # Comparison
    om = next(r for r in results if r["name"] == "omnis_replay")
    cs = next(r for r in results if r["name"] == "charm_style")
    ml = next(r for r in results if r["name"] == "multi_layer_atr")
    mlt = next(r for r in results if r["name"] == "ml_charm_trend")

    print(f"\n📈 Charm-style vs Omnis:        {om['alpha']:+.2f}% → {cs['alpha']:+.2f}%  (Δ{cs['alpha']-om['alpha']:+.2f}%)")
    print(f"📈 Multi-layer ATR vs Omnis:    {om['alpha']:+.2f}% → {ml['alpha']:+.2f}%  (Δ{ml['alpha']-om['alpha']:+.2f}%)")
    print(f"📈 ML+Charm+Trend vs Omnis:     {om['alpha']:+.2f}% → {mlt['alpha']:+.2f}%  (Δ{mlt['alpha']-om['alpha']:+.2f}%)")
    print(f"📈 ML+Charm+Trend vs Charm-style: {cs['alpha']:+.2f}% → {mlt['alpha']:+.2f}%  (Δ{mlt['alpha']-cs['alpha']:+.2f}%)")

    out = DATA_DIR / "backtest_v3_results.json"
    out.write_text(json.dumps({"results": results}, indent=2, default=str))
    print(f"\n💾 {out}")


if __name__ == "__main__":
    main()
