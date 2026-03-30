#!/usr/bin/env python3
"""
梅花易數 LP 策略 (Plum Blossom I Ching LP Strategy)
=====================================================
以時間與價格起盤，用卦象驅動 LP range 決策。

起卦法：
  上卦 = (year_branch + month + day) % 8
  下卦 = (year_branch + month + day + hour) % 8
  動爻 = (year_branch + month + day + hour + price_digits) % 6

卦象 → 策略映射：
  1. 體用五行生克 → 決定寬度（生體=窄/積極，克體=寬/防禦）
  2. 動爻位置 → 決定趨勢偏移方向
  3. 互卦 → 決定 rebalance 冷卻期

八卦：乾(1)兌(2)離(3)震(4)巽(5)坎(6)艮(7)坤(8)
       ☰    ☱    ☲    ☳    ☴    ☵    ☶    ☷
五行：金   金   火   木   木   水   土   土
"""

import csv, math, json, os, sys
import numpy as np
from pathlib import Path
from monte_carlo import (
    load_pool_data, block_bootstrap, tick_to_price, price_to_tick, align,
    v3_amounts, v3_liquidity, POOL_FEE
)

BASE_DIR = Path(__file__).parent

# ─── 八卦 & 五行 ─────────────────────────────────────────────────────

BAGUA = {
    1: {"name": "乾", "symbol": "☰", "element": "金", "nature": "剛健"},
    2: {"name": "兌", "symbol": "☱", "element": "金", "nature": "喜悅"},
    3: {"name": "離", "symbol": "☲", "element": "火", "nature": "光明"},
    4: {"name": "震", "symbol": "☳", "element": "木", "nature": "震動"},
    5: {"name": "巽", "symbol": "☴", "element": "木", "nature": "漸進"},
    6: {"name": "坎", "symbol": "☵", "element": "水", "nature": "險陷"},
    7: {"name": "艮", "symbol": "☶", "element": "土", "nature": "止靜"},
    8: {"name": "坤", "symbol": "☷", "element": "土", "nature": "順承"},
}

# 五行生克
SHENG = {"金": "水", "水": "木", "木": "火", "火": "土", "土": "金"}  # A生B
KE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}      # A克B

def wuxing_relation(yong_elem, ti_elem):
    """
    用卦五行對體卦的關係：
      生體(用生體) → 大吉，積極窄區間
      體生用(體生用) → 洩氣，略保守
      克體(用克體) → 凶，防禦寬區間
      體克用 → 小吉，適度
      比和(同) → 中性
    Returns: score from -2 (最凶) to +2 (最吉)
    """
    if yong_elem == ti_elem:
        return 0  # 比和
    if SHENG[yong_elem] == ti_elem:
        return +2  # 用生體，大吉
    if SHENG[ti_elem] == yong_elem:
        return -1  # 體生用，洩氣
    if KE[yong_elem] == ti_elem:
        return -2  # 用克體，凶
    if KE[ti_elem] == yong_elem:
        return +1  # 體克用，小吉
    return 0


def qigua(timestamp, price):
    """
    梅花易數起卦。

    timestamp: unix timestamp
    price: current price (float)

    Returns: dict with 本卦、變卦、體用、五行關係
    """
    import datetime
    dt = datetime.datetime.utcfromtimestamp(timestamp)

    # 地支序數 (simplified: year % 12 + 1)
    year_branch = (dt.year % 12) + 1
    month = dt.month
    day = dt.day
    hour_zhi = ((dt.hour + 1) // 2) % 12 + 1  # 時辰 (子=1, 丑=2, ...)

    # 價格數字之和
    price_digits = sum(int(c) for c in str(int(price)) if c.isdigit())

    # 起卦
    upper_num = (year_branch + month + day) % 8
    if upper_num == 0: upper_num = 8
    lower_num = (year_branch + month + day + hour_zhi) % 8
    if lower_num == 0: lower_num = 8

    # 動爻 (1-6)
    yao_total = year_branch + month + day + hour_zhi + price_digits
    dong_yao = yao_total % 6
    if dong_yao == 0: dong_yao = 6

    # 體用判斷：動爻在上卦(4-6)則上卦為用、下卦為體；在下卦(1-3)則下卦為用、上卦為體
    if dong_yao >= 4:
        ti_gua = lower_num  # 下卦為體
        yong_gua = upper_num  # 上卦為用(動)
    else:
        ti_gua = upper_num  # 上卦為體
        yong_gua = lower_num  # 下卦為用(動)

    ti_elem = BAGUA[ti_gua]["element"]
    yong_elem = BAGUA[yong_gua]["element"]
    relation = wuxing_relation(yong_elem, ti_elem)

    # 互卦 (inner trigrams: lines 2-4 = lower inner, lines 3-5 = upper inner)
    # Simplified: use middle numbers
    hu_upper = ((upper_num + lower_num) % 8) or 8
    hu_lower = ((upper_num * lower_num) % 8) or 8

    # 變卦 (change the dong_yao line)
    if dong_yao >= 4:
        bian_upper = (upper_num + dong_yao) % 8 or 8
        bian_lower = lower_num
    else:
        bian_upper = upper_num
        bian_lower = (lower_num + dong_yao) % 8 or 8

    return {
        "upper": upper_num,
        "lower": lower_num,
        "dong_yao": dong_yao,
        "ti_gua": ti_gua,
        "yong_gua": yong_gua,
        "ti_element": ti_elem,
        "yong_element": yong_elem,
        "relation": relation,  # -2 to +2
        "hu_upper": hu_upper,
        "hu_lower": hu_lower,
        "bian_upper": bian_upper,
        "bian_lower": bian_lower,
        "hexagram": f"{BAGUA[upper_num]['symbol']}{BAGUA[lower_num]['symbol']}",
        "name": f"{BAGUA[upper_num]['name']}{BAGUA[lower_num]['name']}",
        "ti_name": BAGUA[ti_gua]["name"],
        "yong_name": BAGUA[yong_gua]["name"],
    }


def gua_to_params(gua_result):
    """
    將卦象轉換為 LP 策略參數。

    五行生克 → 寬度：
      +2 (生體)：窄 ±4%，積極收 fee
      +1 (體克用)：適度 ±7%
       0 (比和)：中性 ±10%
      -1 (體生用)：略寬 ±14%
      -2 (克體)：寬 ±20%，防禦

    動爻位置 → 趨勢偏移：
      1,2 (下卦下) → 下跌趨勢偏移
      3,4 (中間)   → 無偏移
      5,6 (上卦上) → 上漲趨勢偏移

    互卦五行 → 冷卻期：
      動卦(震/巽) → 短冷卻(3000)，市場活躍
      靜卦(艮/坤) → 長冷卻(15000)，市場沉寂
      其他 → 中等(7000)
    """
    rel = gua_result["relation"]
    dong = gua_result["dong_yao"]
    hu_elem = BAGUA[gua_result["hu_upper"]]["element"]

    # 寬度映射
    width_map = {+2: 0.04, +1: 0.07, 0: 0.10, -1: 0.14, -2: 0.20}
    width_pct = width_map.get(rel, 0.10)

    # 趨勢偏移
    if dong <= 2:
        trend_bias = -1  # 下行趨勢
        shift_up, shift_down = 0.6, 1.4
    elif dong >= 5:
        trend_bias = +1  # 上行趨勢
        shift_up, shift_down = 1.4, 0.6
    else:
        trend_bias = 0   # 無偏移
        shift_up, shift_down = 1.0, 1.0

    # 冷卻期
    if hu_elem in ("木",):  # 震/巽 → 活躍
        cooldown = 3000
    elif hu_elem in ("土",):  # 艮/坤 → 沉寂
        cooldown = 15000
    elif hu_elem in ("水",):  # 坎 → 流動
        cooldown = 5000
    elif hu_elem in ("火",):  # 離 → 波動
        cooldown = 4000
    else:  # 金 → 堅定
        cooldown = 8000

    return {
        "width_pct": width_pct,
        "shift_up": shift_up,
        "shift_down": shift_down,
        "trend_bias": trend_bias,
        "cooldown": cooldown,
        "gua_name": gua_result["name"],
        "hexagram": gua_result["hexagram"],
        "relation": rel,
        "relation_text": {+2: "生體(大吉)", +1: "體克用(小吉)", 0: "比和(中性)",
                          -1: "體生用(洩)", -2: "克體(凶)"}[rel],
    }


# ─── 梅花策略模擬 ───────────────────────────────────────────────────

def simulate_meihua(pool_key, strategy_name):
    """Simulate 梅花易數 strategy, output dense CSV format."""
    from monte_carlo import load_pool_data
    prices_raw, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    p0 = prices_raw[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    position = None
    fee_usdc = 0.0
    n_rb = 0
    last_rb_block = 0
    total_fee_usdc = 0.0

    gua_log = []  # 記錄每次起卦

    base_ts = 1765951769 if pool_key == "wbtc-usdc" else 1765951769 + (23693484 - 19208958)
    base_block = 19208958 if pool_key == "wbtc-usdc" else 23693484

    for block, tick, price in prices_raw:
        timestamp = base_ts + (block - base_block)

        # Rebalance check
        should_rb = False
        if position is None:
            should_rb = True
        else:
            pa, pb = position[3], position[4]
            current_cooldown = position[5] if len(position) > 5 else 5000
            if block - last_rb_block >= current_cooldown:
                if price < pa or price > pb:
                    should_rb = True
                elif pb > pa:
                    pct = (price - pa) / (pb - pa)
                    if pct < 0.05 or pct > 0.95:
                        should_rb = True

        if should_rb:
            # Burn
            if position:
                tl_p, tu_p, L_p, pa_p, pb_p = position[:5]
                b, u = v3_amounts(L_p, price, pa_p, pb_p)
                base_bal += b
                usdc_bal += u
                usdc_bal += fee_usdc
                total_fee_usdc += fee_usdc
                if n_rb > 0:
                    total_val = base_bal * price + usdc_bal
                    usdc_bal -= total_val * 0.5 * 0.0015
            fee_usdc = 0.0

            # 起卦
            gua = qigua(timestamp, price)
            params = gua_to_params(gua)

            gua_log.append({
                "block": block,
                "price": round(price, 2),
                "hexagram": params["hexagram"],
                "name": params["gua_name"],
                "relation": params["relation_text"],
                "width": f"±{params['width_pct']*100:.0f}%",
                "bias": {-1: "↓下行", 0: "—中性", 1: "↑上行"}[params["trend_bias"]],
                "cooldown": params["cooldown"],
            })

            # 設定區間
            wh = price * params["width_pct"]
            if params["trend_bias"] < 0:
                lo = price - wh * params["shift_down"]
                hi = price + wh * params["shift_up"]
            elif params["trend_bias"] > 0:
                lo = price - wh * params["shift_up"]
                hi = price + wh * params["shift_down"]
            else:
                lo, hi = price - wh, price + wh

            tl = align(price_to_tick(max(0.01, lo), t0, t1, inv), ts)
            tu = align(price_to_tick(hi, t0, t1, inv), ts)
            pa = tick_to_price(tl, t0, t1, inv)
            pb = tick_to_price(tu, t0, t1, inv)
            if pa > pb: pa, pb = pb, pa

            L = v3_liquidity(base_bal, usdc_bal, price, pa, pb)
            if L > 0:
                used_b, used_u = v3_amounts(L, price, pa, pb)
                base_bal -= used_b
                usdc_bal -= used_u
            position = (tl, tu, L, pa, pb, params["cooldown"])

            last_rb_block = block
            n_rb += 1

        # Fees
        if position and block in swap_tick_agg:
            tl_p, tu_p = position[0], position[1]
            L_p = position[2]
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                if tl_p <= tick_bucket < tu_p and L_p > 0:
                    fee_usdc += vol_u * POOL_FEE * fee_share

    # Final
    p_end = prices_raw[-1][2]
    if position:
        pos_b, pos_u = v3_amounts(position[2], p_end, position[3], position[4])
    else:
        pos_b, pos_u = 0, 0

    final_val = (pos_b + base_bal) * p_end + pos_u + usdc_bal + fee_usdc
    total_fee_usdc += fee_usdc

    vault_return = (final_val - init_usd) / init_usd
    hodl_return = ((init_usd / 2 / p0) * p_end + init_usd / 2 - init_usd) / init_usd
    alpha = vault_return - hodl_return

    return {
        "alpha": alpha,
        "vault_return": vault_return,
        "hodl_return": hodl_return,
        "fee_bps": total_fee_usdc / init_usd * 10000,
        "rebalances": n_rb,
        "gua_log": gua_log,
    }


def run_meihua_for_mc(prices, swap_tick_agg, cfg, init_usd, params):
    """MC-compatible wrapper: run meihua on given price/swap data."""
    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    position = None
    fee_usdc = 0.0
    n_rb = 0
    last_rb_block = 0
    total_fee_usdc = 0.0

    # Use fixed base timestamp
    base_ts = params.get("base_ts", 1765951769)
    base_block_ref = params.get("base_block", prices[0][0])

    for block, tick, price in prices:
        timestamp = base_ts + (block - base_block_ref)

        should_rb = False
        if position is None:
            should_rb = True
        else:
            _, _, _, pa, pb = position[:5]
            cd = position[5] if len(position) > 5 else 5000
            if block - last_rb_block >= cd:
                if price < pa or price > pb:
                    should_rb = True
                elif pb > pa:
                    pct = (price - pa) / (pb - pa)
                    if pct < 0.05 or pct > 0.95:
                        should_rb = True

        if should_rb:
            if position:
                b, u = v3_amounts(position[2], price, position[3], position[4])
                base_bal += b
                usdc_bal += u
                usdc_bal += fee_usdc
                total_fee_usdc += fee_usdc
                if n_rb > 0:
                    total_val = base_bal * price + usdc_bal
                    usdc_bal -= total_val * 0.5 * 0.0015
            fee_usdc = 0.0

            gua = qigua(timestamp, price)
            gp = gua_to_params(gua)

            wh = price * gp["width_pct"]
            if gp["trend_bias"] < 0:
                lo = price - wh * gp["shift_down"]
                hi = price + wh * gp["shift_up"]
            elif gp["trend_bias"] > 0:
                lo = price - wh * gp["shift_up"]
                hi = price + wh * gp["shift_down"]
            else:
                lo, hi = price - wh, price + wh

            tl = align(price_to_tick(max(0.01, lo), t0, t1, inv), ts)
            tu = align(price_to_tick(hi, t0, t1, inv), ts)
            pa = tick_to_price(tl, t0, t1, inv)
            pb = tick_to_price(tu, t0, t1, inv)
            if pa > pb: pa, pb = pb, pa

            L = v3_liquidity(base_bal, usdc_bal, price, pa, pb)
            if L > 0:
                used_b, used_u = v3_amounts(L, price, pa, pb)
                base_bal -= used_b
                usdc_bal -= used_u
            position = (tl, tu, L, pa, pb, gp["cooldown"])
            last_rb_block = block
            n_rb += 1

        if position and block in swap_tick_agg:
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                if position[0] <= tick_bucket < position[1] and position[2] > 0:
                    fee_usdc += vol_u * POOL_FEE * fee_share

    p_end = prices[-1][2]
    if position:
        pos_b, pos_u = v3_amounts(position[2], p_end, position[3], position[4])
    else:
        pos_b, pos_u = 0, 0
    final_val = (pos_b + base_bal) * p_end + pos_u + usdc_bal + fee_usdc
    total_fee_usdc += fee_usdc

    vault_return = (final_val - init_usd) / init_usd
    hodl_return = ((init_usd / 2 / p0) * p_end + init_usd / 2 - init_usd) / init_usd

    return {
        "alpha": vault_return - hodl_return,
        "vault_return": vault_return,
        "hodl_return": hodl_return,
        "fee_bps": total_fee_usdc / init_usd * 10000,
        "rebalances": n_rb,
    }


# ─── Main ────────────────────────────────────────────────────────────

def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(BASE_DIR / "charts", exist_ok=True)
    results = {}

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = pool_key.upper()
        print(f"\n{'='*60}")
        print(f"  梅花易數 LP 策略 — {pool_label}")
        print(f"{'='*60}")

        # Run baseline
        r = simulate_meihua(pool_key, f"meihua-{pool_key}")
        print(f"\n  基線結果:")
        print(f"    Alpha:      {r['alpha']*100:+.2f}%")
        print(f"    Vault Return: {r['vault_return']*100:+.2f}%")
        print(f"    Fee:        {r['fee_bps']:.0f} bps")
        print(f"    Rebalances: {r['rebalances']}")

        print(f"\n  卦象紀錄 (前 10 次):")
        print(f"    {'Block':>10} {'Price':>10} {'卦象':>6} {'卦名':>6} {'生克':>12} {'寬度':>6} {'偏移':>6} {'冷卻':>6}")
        for g in r["gua_log"][:10]:
            print(f"    {g['block']:>10} {g['price']:>10} {g['hexagram']:>6} {g['name']:>6} {g['relation']:>12} {g['width']:>6} {g['bias']:>6} {g['cooldown']:>6}")
        if len(r["gua_log"]) > 10:
            print(f"    ... ({len(r['gua_log'])} total)")

        # Monte Carlo: bootstrap only (no param to perturb — 卦象是確定性的)
        print(f"\n  Block Bootstrap (500 paths)...")
        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)
        paths = block_bootstrap(prices, swap_tick_agg, cfg, block_hours=4, n_paths=500)

        boot_alphas = []
        for i, (sp, sa, sta) in enumerate(paths):
            if len(sp) < 10: continue
            br = run_meihua_for_mc(sp, sta, cfg, init_usd, {})
            boot_alphas.append(br["alpha"])
            if (i+1) % 200 == 0:
                print(f"    {i+1}/500...")
        boot_alphas = np.array(boot_alphas)

        bp = np.mean(boot_alphas > 0) * 100
        bmed = np.median(boot_alphas) * 100
        bpct5 = np.percentile(boot_alphas, 5) * 100
        bpct95 = np.percentile(boot_alphas, 95) * 100

        print(f"\n  Bootstrap 結果:")
        print(f"    P(α>0) = {bp:.1f}%")
        print(f"    Median = {bmed:+.2f}%")
        print(f"    5th    = {bpct5:+.2f}%")
        print(f"    95th   = {bpct95:+.2f}%")

        # Compare with ML
        from monte_carlo import run_sim
        ml = run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, {})

        print(f"\n  對比 ML 3-Layer:")
        print(f"    {'':>15} {'梅花':>10} {'ML':>10}")
        print(f"    {'Alpha':>15} {r['alpha']*100:>+9.2f}% {ml['alpha']*100:>+9.2f}%")
        print(f"    {'Rebalances':>15} {r['rebalances']:>9} {ml['rebalances']:>9}")
        print(f"    {'Boot Median':>15} {bmed:>+9.2f}% {'—':>9}")

        # Plot: 卦象時間線 + bootstrap
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # 卦象時間線
        gua_blocks = [g["block"] for g in r["gua_log"]]
        gua_prices = [g["price"] for g in r["gua_log"]]
        gua_widths = [float(g["width"].replace("±", "").replace("%", "")) for g in r["gua_log"]]
        gua_rels = [{"生體(大吉)": 2, "體克用(小吉)": 1, "比和(中性)": 0,
                     "體生用(洩)": -1, "克體(凶)": -2}[g["relation"]] for g in r["gua_log"]]

        colors = {2: "#22C55E", 1: "#86EFAC", 0: "#94A3B8", -1: "#FCA5A5", -2: "#EF4444"}

        for i, g in enumerate(r["gua_log"]):
            c = colors[gua_rels[i]]
            ax1.scatter(gua_blocks[i], gua_prices[i], c=c, s=gua_widths[i]*3,
                       alpha=0.8, edgecolors="white", linewidth=0.5, zorder=3)

        # Price line
        price_data = [(b, p) for b, _, p in prices]
        ax1.plot([b for b, p in price_data[::10]], [p for b, p in price_data[::10]],
                color="#64748b", linewidth=0.8, alpha=0.5, zorder=1)

        ax1.set_xlabel("Block")
        ax1.set_ylabel("Price")
        ax1.set_title(f"{pool_label} — 梅花卦象時間線\n"
                      f"●大=寬區間 ●小=窄區間 | 🟢吉 🔴凶")
        ax1.grid(alpha=0.2)

        # Legend
        for rel, c, label in [(2, "#22C55E", "生體(大吉)"), (1, "#86EFAC", "體克用(小吉)"),
                               (0, "#94A3B8", "比和"), (-1, "#FCA5A5", "體生用(洩)"), (-2, "#EF4444", "克體(凶)")]:
            ax1.scatter([], [], c=c, s=40, label=label)
        ax1.legend(fontsize=7, loc="upper right")

        # Bootstrap histogram
        ax2.hist(boot_alphas * 100, bins=50, color="#8B5CF6", alpha=0.7, edgecolor="white", linewidth=0.5)
        ax2.axvline(0, color="red", linewidth=2, linestyle="--")
        ax2.axvline(r["alpha"] * 100, color="#22C55E", linewidth=2, label=f"Baseline: {r['alpha']*100:+.2f}%")
        ax2.axvline(bmed, color="#F59E0B", linewidth=2, linestyle=":", label=f"Median: {bmed:+.2f}%")
        ax2.set_xlabel("Net Alpha (%)")
        ax2.set_ylabel("Frequency")
        ax2.set_title(f"Bootstrap (N=500)\n"
                      f"P(α>0)={bp:.0f}% | Med={bmed:+.1f}% | 5th={bpct5:+.1f}%")
        ax2.legend(fontsize=9)
        ax2.grid(alpha=0.3)

        fig.suptitle(f"梅花易數 LP 策略 — {pool_label}", fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"meihua_{pool_key}.png", dpi=150)
        plt.close(fig)

        results[pool_key] = {
            "baseline_alpha": round(r["alpha"] * 100, 2),
            "vault_return": round(r["vault_return"] * 100, 2),
            "fee_bps": round(r["fee_bps"], 1),
            "rebalances": r["rebalances"],
            "gua_log": r["gua_log"],
            "bootstrap": {
                "p_positive": round(bp, 1),
                "median": round(bmed, 2),
                "pct5": round(bpct5, 2),
                "pct95": round(bpct95, 2),
            },
            "ml_baseline_alpha": round(ml["alpha"] * 100, 2),
        }

    with open(BASE_DIR / "meihua_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print("  完成！")
    print(f"  圖表: charts/meihua_*.png")
    print(f"  數據: meihua_results.json")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
