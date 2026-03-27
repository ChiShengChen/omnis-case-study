#!/usr/bin/env python3
"""
Single-Range Strategy Sweep
============================
Find the optimal single-range width by sweeping ±5% to ±25%.
Tests: width × cooldown × trend_shift combinations.

Outputs:
  - charts/single_range_sweep_*.png
  - single_range_results.json
"""

import csv, math, json, os, sys
import numpy as np
from pathlib import Path
from monte_carlo import (
    load_pool_data, tick_to_price, price_to_tick, align,
    v3_amounts, v3_liquidity, POOL_FEE
)

BASE_DIR = Path(__file__).parent


def run_single_range(prices, swap_tick_agg, cfg, init_usd, params):
    """
    Single-range strategy simulation.

    params:
      width_pct:    half-width of range (e.g. 0.10 = ±10%)
      trend_shift:  whether to apply trend-aware centering (bool)
      trend_thresh: trend threshold (default 0.20)
      shift_up:     uptrend multiplier (default 1.4)
      shift_down:   downtrend multiplier (default 0.6)
      cooldown:     min blocks between rebalances (default 5000)
      lookback:     trend lookback periods (default 20)
      slippage:     swap slippage rate (default 0.0015)
      boundary_pct: rebalance when price within this % of edge (default 0.05)
    """
    width_pct = params.get("width_pct", 0.10)
    trend_shift = params.get("trend_shift", False)
    trend_thresh = params.get("trend_thresh", 0.20)
    shift_up = params.get("shift_up", 1.4)
    shift_down = params.get("shift_down", 0.6)
    cooldown = int(params.get("cooldown", 5000))
    lookback = int(params.get("lookback", 20))
    slippage = params.get("slippage", 0.0015)
    boundary_pct = params.get("boundary_pct", 0.05)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    position = None  # (tl, tu, L, pa, pb)
    fee_usdc = 0.0
    n_rb = 0
    price_history = []
    last_rb_block = 0
    total_fee_usdc = 0.0
    in_range_count = 0
    total_count = 0

    for block, tick, price in prices:
        price_history.append(price)
        total_count += 1

        # Check in-range
        if position:
            _, _, _, pa, pb = position
            if pa <= price <= pb:
                in_range_count += 1

        # Rebalance check
        should_rb = False
        if position is None:
            should_rb = True
        elif block - last_rb_block >= cooldown:
            _, _, _, pa, pb = position
            if price < pa or price > pb:
                should_rb = True
            elif pb > pa:
                pct = (price - pa) / (pb - pa)
                if pct < boundary_pct or pct > (1 - boundary_pct):
                    should_rb = True

        if should_rb:
            # Burn
            if position:
                tl_p, tu_p, L_p, pa_p, pb_p = position
                b, u = v3_amounts(L_p, price, pa_p, pb_p)
                base_bal += b
                usdc_bal += u
                base_bal += 0  # no base fees in simplified model
                usdc_bal += fee_usdc
                total_fee_usdc += fee_usdc

                # Slippage cost
                total_val = base_bal * price + usdc_bal
                swap_vol = total_val * 0.5  # ~50% needs swap for ratio adjustment
                usdc_bal -= swap_vol * slippage

            fee_usdc = 0.0

            # Make new range
            wh = price * width_pct

            if trend_shift and len(price_history) >= lookback:
                r = (price_history[-1] - price_history[-lookback]) / price_history[-lookback]
                t_dir = max(-1, min(1, r / trend_thresh))
                if t_dir < -0.2:
                    lo, hi = price - wh * shift_up, price + wh * shift_down
                elif t_dir > 0.2:
                    lo, hi = price - wh * shift_down, price + wh * shift_up
                else:
                    lo, hi = price - wh, price + wh
            else:
                lo, hi = price - wh, price + wh

            tl = align(price_to_tick(max(0.01, lo), t0, t1, inv), ts)
            tu = align(price_to_tick(hi, t0, t1, inv), ts)
            pa = tick_to_price(tl, t0, t1, inv)
            pb = tick_to_price(tu, t0, t1, inv)
            if pa > pb:
                pa, pb = pb, pa

            L = v3_liquidity(base_bal, usdc_bal, price, pa, pb)
            if L > 0:
                used_b, used_u = v3_amounts(L, price, pa, pb)
                base_bal -= used_b
                usdc_bal -= used_u
            position = (tl, tu, L, pa, pb)

            last_rb_block = block
            n_rb += 1

        # Fees
        if position and block in swap_tick_agg:
            tl_p, tu_p, L_p, pa_p, pb_p = position
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                if tl_p <= tick_bucket < tu_p and L_p > 0:
                    fee_usdc += vol_u * POOL_FEE * fee_share

    # Final valuation
    p_end = prices[-1][2]
    if position:
        tl_p, tu_p, L_p, pa_p, pb_p = position
        pos_b, pos_u = v3_amounts(L_p, p_end, pa_p, pb_p)
    else:
        pos_b, pos_u = 0, 0

    final_val = (pos_b + base_bal) * p_end + pos_u + usdc_bal + fee_usdc
    total_fee_usdc += fee_usdc

    vault_return = (final_val - init_usd) / init_usd
    hodl_return = ((init_usd / 2 / p0) * p_end + init_usd / 2 - init_usd) / init_usd
    alpha = vault_return - hodl_return
    fee_bps = total_fee_usdc / init_usd * 10000
    in_range_pct = in_range_count / total_count * 100 if total_count > 0 else 0

    return {
        "alpha": alpha,
        "vault_return": vault_return,
        "hodl_return": hodl_return,
        "fee_bps": fee_bps,
        "rebalances": n_rb,
        "in_range_pct": in_range_pct,
        "final_val": final_val,
    }


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(BASE_DIR / "charts", exist_ok=True)

    # Sweep parameters
    widths = np.arange(0.03, 0.26, 0.01)  # ±3% to ±25%
    cooldowns = [3000, 5000, 10000, 25000, 50000, 100000, 600000]
    cooldown_labels = ["0.8h", "1.4h", "2.8h", "7h", "14h", "28h", "7d"]

    all_results = {}

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = "WBTC-USDC" if pool_key == "wbtc-usdc" else "USDC-ETH"
        print(f"\n{'='*60}")
        print(f"  Single-Range Sweep — {pool_label}")
        print(f"{'='*60}")

        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)

        # ── 1. Width sweep (fixed cooldown=5000, with and without trend shift) ──
        print(f"\n  [1/3] Width sweep (±3% to ±25%)...")
        width_results_no_trend = []
        width_results_trend = []

        for w in widths:
            r_no = run_single_range(prices, swap_tick_agg, cfg, init_usd,
                                     {"width_pct": w, "trend_shift": False, "cooldown": 5000})
            r_tr = run_single_range(prices, swap_tick_agg, cfg, init_usd,
                                     {"width_pct": w, "trend_shift": True, "cooldown": 5000})
            width_results_no_trend.append(r_no)
            width_results_trend.append(r_tr)

        # Plot: Width vs Alpha
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # Alpha vs Width
        ax = axes[0, 0]
        ax.plot(widths * 100, [r["alpha"] * 100 for r in width_results_no_trend],
                "o-", color="#3498db", label="Symmetric", markersize=4)
        ax.plot(widths * 100, [r["alpha"] * 100 for r in width_results_trend],
                "s-", color="#2ecc71", label="+ Trend Shift", markersize=4)
        ax.axhline(0, color="red", linewidth=1, linestyle="--")
        ax.set_xlabel("Range Half-Width (%)")
        ax.set_ylabel("Net Alpha (%)")
        ax.set_title("Alpha vs Range Width")
        ax.legend()
        ax.grid(alpha=0.3)

        # Fee vs Width
        ax = axes[0, 1]
        ax.plot(widths * 100, [r["fee_bps"] for r in width_results_no_trend],
                "o-", color="#3498db", label="Symmetric", markersize=4)
        ax.plot(widths * 100, [r["fee_bps"] for r in width_results_trend],
                "s-", color="#2ecc71", label="+ Trend Shift", markersize=4)
        ax.set_xlabel("Range Half-Width (%)")
        ax.set_ylabel("Fee Earned (bps)")
        ax.set_title("Fee Capture vs Range Width")
        ax.legend()
        ax.grid(alpha=0.3)

        # Rebalances vs Width
        ax = axes[1, 0]
        ax.plot(widths * 100, [r["rebalances"] for r in width_results_no_trend],
                "o-", color="#3498db", label="Symmetric", markersize=4)
        ax.plot(widths * 100, [r["rebalances"] for r in width_results_trend],
                "s-", color="#2ecc71", label="+ Trend Shift", markersize=4)
        ax.set_xlabel("Range Half-Width (%)")
        ax.set_ylabel("Rebalances")
        ax.set_title("Rebalance Count vs Range Width")
        ax.legend()
        ax.grid(alpha=0.3)

        # In-Range % vs Width
        ax = axes[1, 1]
        ax.plot(widths * 100, [r["in_range_pct"] for r in width_results_no_trend],
                "o-", color="#3498db", label="Symmetric", markersize=4)
        ax.plot(widths * 100, [r["in_range_pct"] for r in width_results_trend],
                "s-", color="#2ecc71", label="+ Trend Shift", markersize=4)
        ax.set_xlabel("Range Half-Width (%)")
        ax.set_ylabel("In-Range (%)")
        ax.set_title("Time In-Range vs Range Width")
        ax.legend()
        ax.grid(alpha=0.3)

        fig.suptitle(f"{pool_label} — Single-Range Width Sweep (cooldown=5000 blocks)",
                     fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"single_range_width_{pool_key}.png", dpi=150)
        plt.close(fig)

        # ── 2. Width × Cooldown heatmap ──
        print(f"  [2/3] Width × Cooldown heatmap...")
        heatmap = np.zeros((len(cooldowns), len(widths)))
        heatmap_rb = np.zeros((len(cooldowns), len(widths)))

        for ci, cd in enumerate(cooldowns):
            for wi, w in enumerate(widths):
                r = run_single_range(prices, swap_tick_agg, cfg, init_usd,
                                     {"width_pct": w, "trend_shift": True, "cooldown": cd})
                heatmap[ci, wi] = r["alpha"] * 100
                heatmap_rb[ci, wi] = r["rebalances"]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

        # Alpha heatmap
        im1 = ax1.imshow(heatmap, aspect="auto", cmap="RdYlGn",
                          vmin=min(-3, heatmap.min()), vmax=max(3, heatmap.max()))
        ax1.set_xticks(range(0, len(widths), 3))
        ax1.set_xticklabels([f"±{w*100:.0f}%" for w in widths[::3]], rotation=45)
        ax1.set_yticks(range(len(cooldowns)))
        ax1.set_yticklabels(cooldown_labels)
        ax1.set_xlabel("Range Width")
        ax1.set_ylabel("Cooldown Period")
        ax1.set_title("Net Alpha (%)")
        plt.colorbar(im1, ax=ax1, shrink=0.8)

        # Mark best
        best_idx = np.unravel_index(heatmap.argmax(), heatmap.shape)
        ax1.plot(best_idx[1], best_idx[0], "k*", markersize=15)
        ax1.annotate(f"Best: {heatmap[best_idx]:+.2f}%\n±{widths[best_idx[1]]*100:.0f}%, {cooldown_labels[best_idx[0]]}",
                     xy=(best_idx[1], best_idx[0]), fontsize=9,
                     xytext=(best_idx[1]+3, best_idx[0]+1),
                     arrowprops=dict(arrowstyle="->"),
                     bbox=dict(boxstyle="round,pad=0.3", facecolor="white"))

        # Rebalance heatmap
        im2 = ax2.imshow(heatmap_rb, aspect="auto", cmap="YlOrRd")
        ax2.set_xticks(range(0, len(widths), 3))
        ax2.set_xticklabels([f"±{w*100:.0f}%" for w in widths[::3]], rotation=45)
        ax2.set_yticks(range(len(cooldowns)))
        ax2.set_yticklabels(cooldown_labels)
        ax2.set_xlabel("Range Width")
        ax2.set_ylabel("Cooldown Period")
        ax2.set_title("Rebalance Count")
        plt.colorbar(im2, ax=ax2, shrink=0.8)

        fig.suptitle(f"{pool_label} — Width × Cooldown Heatmap (with Trend Shift)",
                     fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"single_range_heatmap_{pool_key}.png", dpi=150)
        plt.close(fig)

        # ── 3. Find optimal and compare with ML ──
        print(f"  [3/3] Finding optimal single-range config...")

        # Sweep finer around best
        best_w = widths[best_idx[1]]
        best_cd = cooldowns[best_idx[0]]
        fine_widths = np.arange(max(0.03, best_w - 0.03), min(0.25, best_w + 0.03), 0.005)

        best_alpha = -999
        best_config = {}
        for w in fine_widths:
            for cd in [best_cd // 2, best_cd, best_cd * 2]:
                for boundary in [0.03, 0.05, 0.10]:
                    r = run_single_range(prices, swap_tick_agg, cfg, init_usd,
                                         {"width_pct": w, "trend_shift": True,
                                          "cooldown": cd, "boundary_pct": boundary})
                    if r["alpha"] > best_alpha:
                        best_alpha = r["alpha"]
                        best_config = {"width_pct": round(w, 4), "cooldown": cd,
                                       "boundary_pct": boundary, **r}

        # Also get ML baseline for comparison
        from monte_carlo import run_sim
        ml_baseline = run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, {})

        print(f"\n  {'─'*50}")
        print(f"  OPTIMAL SINGLE-RANGE CONFIG:")
        print(f"    Width:      ±{best_config['width_pct']*100:.1f}%")
        print(f"    Cooldown:   {best_config['cooldown']} blocks ({best_config['cooldown']/3600:.1f}h)")
        print(f"    Boundary:   {best_config['boundary_pct']*100:.0f}%")
        print(f"    Trend:      Yes")
        print(f"    Alpha:      {best_config['alpha']*100:+.2f}%")
        print(f"    Fee:        {best_config['fee_bps']:.0f} bps")
        print(f"    Rebalances: {best_config['rebalances']}")
        print(f"    In-Range:   {best_config['in_range_pct']:.1f}%")
        print(f"  {'─'*50}")
        print(f"  ML 3-LAYER BASELINE:")
        print(f"    Alpha:      {ml_baseline['alpha']*100:+.2f}%")
        print(f"    Fee:        {ml_baseline['fee_bps']:.0f} bps")
        print(f"    Rebalances: {ml_baseline['rebalances']}")
        print(f"  {'─'*50}")

        all_results[pool_key] = {
            "optimal": {
                "width_pct": best_config["width_pct"],
                "cooldown": best_config["cooldown"],
                "boundary_pct": best_config["boundary_pct"],
                "trend_shift": True,
                "alpha": round(best_config["alpha"] * 100, 2),
                "fee_bps": round(best_config["fee_bps"], 1),
                "rebalances": best_config["rebalances"],
                "in_range_pct": round(best_config["in_range_pct"], 1),
            },
            "ml_baseline": {
                "alpha": round(ml_baseline["alpha"] * 100, 2),
                "fee_bps": round(ml_baseline["fee_bps"], 1),
                "rebalances": ml_baseline["rebalances"],
            },
            "width_sweep": [
                {"width": round(w * 100, 1),
                 "alpha_sym": round(width_results_no_trend[i]["alpha"] * 100, 2),
                 "alpha_trend": round(width_results_trend[i]["alpha"] * 100, 2),
                 "rb_sym": width_results_no_trend[i]["rebalances"],
                 "rb_trend": width_results_trend[i]["rebalances"],
                 "inrange_trend": round(width_results_trend[i]["in_range_pct"], 1)}
                for i, w in enumerate(widths)
            ],
        }

    # Save
    with open(BASE_DIR / "single_range_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print("  Done!")
    print(f"  Charts: charts/single_range_*.png")
    print(f"  Data:   single_range_results.json")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
