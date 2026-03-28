#!/usr/bin/env python3
"""
Realized Volatility Width Strategy
====================================
Single-range strategy where width = k × 7d_realized_vol.
Sweeps k from 1.0 to 4.0, then runs Monte Carlo validation.

Also tests Lazy Return strategy (no rebalance until price returns).
"""

import csv, math, json, os, sys
import numpy as np
from pathlib import Path
from monte_carlo import (
    load_pool_data, block_bootstrap, tick_to_price, price_to_tick, align,
    v3_amounts, v3_liquidity, POOL_FEE
)

BASE_DIR = Path(__file__).parent


def realized_vol(prices, window=7*24):
    """7-day realized vol from price list (hourly-ish data)."""
    if len(prices) < window + 1:
        # Fallback: use all available data
        if len(prices) < 10:
            return 0.05  # default 5%
        window = len(prices) - 1
    recent = prices[-window-1:]
    log_rets = [math.log(recent[i] / recent[i-1]) for i in range(1, len(recent)) if recent[i-1] > 0]
    if not log_rets:
        return 0.05
    return max(0.01, np.std(log_rets) * math.sqrt(len(log_rets)))  # annualize-ish


def run_rv_width(prices, swap_tick_agg, cfg, init_usd, params):
    """
    RV-Width strategy: width = k * realized_vol_7d.

    params:
      k:            volatility multiplier (default 2.0)
      min_width:    minimum width pct (default 0.03)
      max_width:    maximum width pct (default 0.25)
      cooldown:     min blocks between rebalances (default 5000)
      vol_window:   lookback for vol calc in price points (default 168 = ~7d)
      slippage:     swap slippage (default 0.0015)
      trend_shift:  apply trend shift (default True)
    """
    k = params.get("k", 2.0)
    min_width = params.get("min_width", 0.03)
    max_width = params.get("max_width", 0.25)
    cooldown = int(params.get("cooldown", 5000))
    vol_window = int(params.get("vol_window", 168))
    slippage = params.get("slippage", 0.0015)
    trend_shift = params.get("trend_shift", True)

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
    widths_used = []

    for block, tick, price in prices:
        price_history.append(price)
        total_count += 1

        if position:
            _, _, _, pa, pb = position
            if pa <= price <= pb:
                in_range_count += 1

        should_rb = False
        if position is None:
            should_rb = True
        elif block - last_rb_block >= cooldown:
            _, _, _, pa, pb = position
            if price < pa or price > pb:
                should_rb = True
            elif pb > pa:
                pct = (price - pa) / (pb - pa)
                if pct < 0.05 or pct > 0.95:
                    should_rb = True

        if should_rb:
            if position:
                tl_p, tu_p, L_p, pa_p, pb_p = position
                b, u = v3_amounts(L_p, price, pa_p, pb_p)
                base_bal += b
                usdc_bal += u
                usdc_bal += fee_usdc
                total_fee_usdc += fee_usdc

                if n_rb > 0:
                    total_val = base_bal * price + usdc_bal
                    usdc_bal -= total_val * 0.5 * slippage

            fee_usdc = 0.0

            # Calculate width from realized vol
            rv = realized_vol(price_history, vol_window)
            width_pct = max(min_width, min(max_width, k * rv))
            widths_used.append(width_pct)
            wh = price * width_pct

            # Trend shift
            if trend_shift and len(price_history) >= 20:
                r = (price_history[-1] - price_history[-20]) / price_history[-20]
                t_dir = max(-1, min(1, r / 0.2))
                if t_dir < -0.2:
                    lo, hi = price - wh * 1.4, price + wh * 0.6
                elif t_dir > 0.2:
                    lo, hi = price - wh * 0.6, price + wh * 1.4
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

    # Final
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
        "avg_width": round(np.mean(widths_used) * 100, 2) if widths_used else 0,
    }


def run_lazy_return(prices, swap_tick_agg, cfg, init_usd, params):
    """
    Lazy Return: set wide range, only rebalance when price RETURNS to center.

    params:
      width_pct:      initial range half-width (default 0.15)
      return_pct:     price must return within this % of center to trigger rebalance (default 0.5)
      slippage:       swap slippage (default 0.0015)
    """
    width_pct = params.get("width_pct", 0.15)
    return_pct = params.get("return_pct", 0.5)
    slippage = params.get("slippage", 0.0015)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    position = None
    position_center = None
    was_out_of_range = False
    fee_usdc = 0.0
    n_rb = 0
    total_fee_usdc = 0.0
    in_range_count = 0
    total_count = 0

    for block, tick, price in prices:
        total_count += 1

        if position:
            _, _, _, pa, pb = position
            in_range = pa <= price <= pb
            if in_range:
                in_range_count += 1

            if not in_range:
                was_out_of_range = True

        should_rb = False
        if position is None:
            should_rb = True
        elif was_out_of_range and position_center:
            # Only rebalance when price returns close to old center
            dist = abs(price - position_center) / position_center
            if dist < width_pct * return_pct:
                should_rb = True

        if should_rb:
            if position:
                tl_p, tu_p, L_p, pa_p, pb_p = position
                b, u = v3_amounts(L_p, price, pa_p, pb_p)
                base_bal += b
                usdc_bal += u
                usdc_bal += fee_usdc
                total_fee_usdc += fee_usdc

                if n_rb > 0:
                    total_val = base_bal * price + usdc_bal
                    usdc_bal -= total_val * 0.5 * slippage

            fee_usdc = 0.0
            was_out_of_range = False

            wh = price * width_pct
            lo, hi = price - wh, price + wh
            position_center = price

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
    }


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(BASE_DIR / "charts", exist_ok=True)
    results = {}

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = "WBTC-USDC" if pool_key == "wbtc-usdc" else "USDC-ETH"
        print(f"\n{'='*60}")
        print(f"  RV-Width & Lazy Return — {pool_label}")
        print(f"{'='*60}")

        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)

        # ── 1. RV-Width: Sweep k ──
        print(f"\n  [1/4] RV-Width: sweep k=1.0 to 4.0...")
        ks = np.arange(0.5, 4.5, 0.25)
        rv_results = []
        for k_val in ks:
            r = run_rv_width(prices, swap_tick_agg, cfg, init_usd, {"k": k_val})
            rv_results.append(r)
            if k_val % 1.0 < 0.01:
                print(f"    k={k_val:.1f}: alpha={r['alpha']*100:+.2f}%, rb={r['rebalances']}, avg_w=±{r['avg_width']:.1f}%")

        # Find best k
        best_idx = np.argmax([r["alpha"] for r in rv_results])
        best_k = ks[best_idx]
        best_rv = rv_results[best_idx]
        print(f"  Best k={best_k:.2f}: alpha={best_rv['alpha']*100:+.2f}%, rb={best_rv['rebalances']}, avg_w=±{best_rv['avg_width']:.1f}%")

        # ── 2. Lazy Return: Sweep width ──
        print(f"\n  [2/4] Lazy Return: sweep width...")
        widths = np.arange(0.05, 0.26, 0.02)
        return_pcts = [0.3, 0.5, 0.7]
        lazy_results = {}
        for rp in return_pcts:
            lazy_results[rp] = []
            for w in widths:
                r = run_lazy_return(prices, swap_tick_agg, cfg, init_usd,
                                    {"width_pct": w, "return_pct": rp})
                lazy_results[rp].append(r)

        # Find best lazy
        best_lazy_alpha = -999
        best_lazy_cfg = {}
        for rp in return_pcts:
            for i, w in enumerate(widths):
                a = lazy_results[rp][i]["alpha"]
                if a > best_lazy_alpha:
                    best_lazy_alpha = a
                    best_lazy_cfg = {"width": w, "return_pct": rp, **lazy_results[rp][i]}
        print(f"  Best Lazy: width=±{best_lazy_cfg['width']*100:.0f}%, return={best_lazy_cfg['return_pct']}, alpha={best_lazy_cfg['alpha']*100:+.2f}%, rb={best_lazy_cfg['rebalances']}")

        # ── 3. Monte Carlo: RV-Width with best k ──
        print(f"\n  [3/4] Monte Carlo: RV-Width k={best_k:.2f} (1000 param + 500 bootstrap)...")
        np.random.seed(42)

        # Param sensitivity
        rv_param_alphas = []
        for i in range(1000):
            p = {
                "k": np.random.uniform(max(0.5, best_k * 0.5), best_k * 2.0),
                "min_width": np.random.uniform(0.02, 0.05),
                "max_width": np.random.uniform(0.15, 0.30),
                "cooldown": np.random.uniform(2000, 15000),
                "vol_window": np.random.randint(50, 300),
                "slippage": np.random.uniform(0.0005, 0.003),
                "trend_shift": np.random.choice([True, False]),
            }
            r = run_rv_width(prices, swap_tick_agg, cfg, init_usd, p)
            rv_param_alphas.append(r["alpha"])
            if (i + 1) % 250 == 0:
                print(f"      param {i+1}/1000...")

        rv_param_alphas = np.array(rv_param_alphas)

        # Bootstrap
        rv_boot_alphas = []
        paths = block_bootstrap(prices, swap_tick_agg, cfg, block_hours=4, n_paths=500)
        for i, (sp, sa, sta) in enumerate(paths):
            if len(sp) < 10:
                continue
            r = run_rv_width(sp, sta, cfg, init_usd, {"k": best_k})
            rv_boot_alphas.append(r["alpha"])
            if (i + 1) % 200 == 0:
                print(f"      boot {i+1}/500...")
        rv_boot_alphas = np.array(rv_boot_alphas)

        # ── 4. Monte Carlo: Lazy Return ──
        print(f"\n  [4/4] Monte Carlo: Lazy Return (1000 param + 500 bootstrap)...")

        lazy_param_alphas = []
        for i in range(1000):
            p = {
                "width_pct": np.random.uniform(0.05, 0.25),
                "return_pct": np.random.uniform(0.2, 0.8),
                "slippage": np.random.uniform(0.0005, 0.003),
            }
            r = run_lazy_return(prices, swap_tick_agg, cfg, init_usd, p)
            lazy_param_alphas.append(r["alpha"])
            if (i + 1) % 250 == 0:
                print(f"      param {i+1}/1000...")
        lazy_param_alphas = np.array(lazy_param_alphas)

        lazy_boot_alphas = []
        for i, (sp, sa, sta) in enumerate(paths):
            if len(sp) < 10:
                continue
            r = run_lazy_return(sp, sta, cfg, init_usd,
                               {"width_pct": best_lazy_cfg["width"], "return_pct": best_lazy_cfg["return_pct"]})
            lazy_boot_alphas.append(r["alpha"])
        lazy_boot_alphas = np.array(lazy_boot_alphas)

        # ── Print summary ──
        print(f"\n  {'─'*55}")
        print(f"  {'':>25} {'RV-Width':>12} {'Lazy Return':>12} {'ML 3-Layer':>12}")
        print(f"  {'─'*55}")

        from monte_carlo import run_sim
        ml = run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, {})

        print(f"  {'Baseline alpha':>25} {best_rv['alpha']*100:>+10.2f}% {best_lazy_cfg['alpha']*100:>+10.2f}% {ml['alpha']*100:>+10.2f}%")
        print(f"  {'Rebalances':>25} {best_rv['rebalances']:>10} {best_lazy_cfg['rebalances']:>10} {ml['rebalances']:>10}")
        print(f"  {'Param P(α>0)':>25} {np.mean(rv_param_alphas>0)*100:>9.0f}% {np.mean(lazy_param_alphas>0)*100:>9.0f}% {'—':>10}")
        print(f"  {'Param median':>25} {np.median(rv_param_alphas)*100:>+10.2f}% {np.median(lazy_param_alphas)*100:>+10.2f}% {'—':>10}")
        print(f"  {'Boot P(α>0)':>25} {np.mean(rv_boot_alphas>0)*100:>9.0f}% {np.mean(lazy_boot_alphas>0)*100:>9.0f}% {'—':>10}")
        print(f"  {'Boot median':>25} {np.median(rv_boot_alphas)*100:>+10.2f}% {np.median(lazy_boot_alphas)*100:>+10.2f}% {'—':>10}")
        print(f"  {'Boot 5th pct':>25} {np.percentile(rv_boot_alphas,5)*100:>+10.2f}% {np.percentile(lazy_boot_alphas,5)*100:>+10.2f}% {'—':>10}")
        print(f"  {'─'*55}")

        # ── Plot ──
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # RV-Width k sweep
        ax = axes[0, 0]
        ax.plot(ks, [r["alpha"] * 100 for r in rv_results], "o-", color="#e67e22", markersize=4)
        ax.axhline(0, color="red", linewidth=1, linestyle="--")
        ax.axhline(ml["alpha"] * 100, color="#22C55E", linewidth=1, linestyle=":", label=f"ML baseline: {ml['alpha']*100:+.2f}%")
        ax.axvline(best_k, color="#e67e22", linewidth=1, linestyle="--", alpha=0.5)
        ax.set_xlabel("k (volatility multiplier)")
        ax.set_ylabel("Net Alpha (%)")
        ax.set_title(f"RV-Width: Alpha vs k\nBest k={best_k:.2f}, α={best_rv['alpha']*100:+.2f}%")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        # Lazy Return width sweep
        ax = axes[0, 1]
        for rp in return_pcts:
            ax.plot(widths * 100, [r["alpha"] * 100 for r in lazy_results[rp]],
                    "o-", markersize=3, label=f"return={rp}")
        ax.axhline(0, color="red", linewidth=1, linestyle="--")
        ax.axhline(ml["alpha"] * 100, color="#22C55E", linewidth=1, linestyle=":", label=f"ML: {ml['alpha']*100:+.2f}%")
        ax.set_xlabel("Range Width (%)")
        ax.set_ylabel("Net Alpha (%)")
        ax.set_title("Lazy Return: Alpha vs Width")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

        # MC param histograms
        ax = axes[1, 0]
        ax.hist(rv_param_alphas * 100, bins=50, color="#e67e22", alpha=0.6, label="RV-Width")
        ax.hist(lazy_param_alphas * 100, bins=50, color="#3498db", alpha=0.6, label="Lazy Return")
        ax.axvline(0, color="red", linewidth=2, linestyle="--")
        ax.set_xlabel("Net Alpha (%)")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Param Sensitivity\nRV P(α>0)={np.mean(rv_param_alphas>0)*100:.0f}%, Lazy P(α>0)={np.mean(lazy_param_alphas>0)*100:.0f}%")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        # MC bootstrap histograms
        ax = axes[1, 1]
        ax.hist(rv_boot_alphas * 100, bins=50, color="#e67e22", alpha=0.6, label="RV-Width")
        ax.hist(lazy_boot_alphas * 100, bins=50, color="#3498db", alpha=0.6, label="Lazy Return")
        ax.axvline(0, color="red", linewidth=2, linestyle="--")
        ax.set_xlabel("Net Alpha (%)")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Block Bootstrap\nRV P(α>0)={np.mean(rv_boot_alphas>0)*100:.0f}%, Lazy P(α>0)={np.mean(lazy_boot_alphas>0)*100:.0f}%")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        fig.suptitle(f"{pool_label} — RV-Width & Lazy Return Strategies", fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"rv_lazy_{pool_key}.png", dpi=150)
        plt.close(fig)

        results[pool_key] = {
            "rv_width": {
                "best_k": round(best_k, 2),
                "baseline_alpha": round(best_rv["alpha"] * 100, 2),
                "rebalances": best_rv["rebalances"],
                "avg_width": best_rv["avg_width"],
                "in_range_pct": round(best_rv["in_range_pct"], 1),
                "param_p_positive": round(np.mean(rv_param_alphas > 0) * 100, 1),
                "param_median": round(np.median(rv_param_alphas) * 100, 2),
                "boot_p_positive": round(np.mean(rv_boot_alphas > 0) * 100, 1),
                "boot_median": round(np.median(rv_boot_alphas) * 100, 2),
                "boot_pct5": round(np.percentile(rv_boot_alphas, 5) * 100, 2),
            },
            "lazy_return": {
                "best_width": round(best_lazy_cfg["width"] * 100, 1),
                "best_return_pct": best_lazy_cfg["return_pct"],
                "baseline_alpha": round(best_lazy_cfg["alpha"] * 100, 2),
                "rebalances": best_lazy_cfg["rebalances"],
                "in_range_pct": round(best_lazy_cfg["in_range_pct"], 1),
                "param_p_positive": round(np.mean(lazy_param_alphas > 0) * 100, 1),
                "param_median": round(np.median(lazy_param_alphas) * 100, 2),
                "boot_p_positive": round(np.mean(lazy_boot_alphas > 0) * 100, 1),
                "boot_median": round(np.median(lazy_boot_alphas) * 100, 2),
                "boot_pct5": round(np.percentile(lazy_boot_alphas, 5) * 100, 2),
            },
            "ml_baseline": {
                "alpha": round(ml["alpha"] * 100, 2),
                "rebalances": ml["rebalances"],
            },
        }

    with open(BASE_DIR / "rv_lazy_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print("  Done!")
    print(f"  Charts: charts/rv_lazy_*.png")
    print(f"  Data:   rv_lazy_results.json")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
