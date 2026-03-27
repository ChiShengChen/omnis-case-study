#!/usr/bin/env python3
"""
Monte Carlo for Single-Range Strategy
======================================
Validate the optimal single-range configs found by sweep.
1. Parameter Sensitivity: perturb width/cooldown/boundary around optimal
2. Block Bootstrap: resample price paths with fixed optimal params
"""

import csv, math, json, os, sys
import numpy as np
from pathlib import Path
from monte_carlo import load_pool_data, block_bootstrap
from single_range_sweep import run_single_range

BASE_DIR = Path(__file__).parent

# Optimal configs from sweep
OPTIMAL = {
    "wbtc-usdc": {"width_pct": 0.05, "cooldown": 5000, "boundary_pct": 0.05, "trend_shift": True},
    "usdc-eth": {"width_pct": 0.145, "cooldown": 1500, "boundary_pct": 0.03, "trend_shift": True},
}


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(BASE_DIR / "charts", exist_ok=True)
    results = {}

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = "WBTC-USDC" if pool_key == "wbtc-usdc" else "USDC-ETH"
        opt = OPTIMAL[pool_key]
        print(f"\n{'='*60}")
        print(f"  Single-Range MC — {pool_label}")
        print(f"  Optimal: ±{opt['width_pct']*100:.1f}%, cd={opt['cooldown']}, boundary={opt['boundary_pct']*100:.0f}%")
        print(f"{'='*60}")

        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)

        # Baseline
        baseline = run_single_range(prices, swap_tick_agg, cfg, init_usd, opt)
        print(f"  Baseline alpha: {baseline['alpha']*100:+.2f}%")

        # ── 1. Parameter Sensitivity (2,000 runs) ──
        print(f"\n  [1/2] Parameter Sensitivity (2,000 runs)...")
        np.random.seed(42)
        N_PARAM = 2000
        param_alphas = []

        base_w = opt["width_pct"]
        base_cd = opt["cooldown"]

        for i in range(N_PARAM):
            p = {
                "width_pct": np.random.uniform(max(0.02, base_w * 0.5), base_w * 2.0),
                "cooldown": np.random.uniform(1000, max(base_cd * 3, 20000)),
                "boundary_pct": np.random.uniform(0.02, 0.15),
                "trend_shift": True,
                "trend_thresh": np.random.uniform(0.10, 0.40),
                "shift_up": np.random.uniform(1.1, 1.8),
                "shift_down": np.random.uniform(0.3, 0.9),
                "lookback": np.random.randint(10, 40),
                "slippage": np.random.uniform(0.0005, 0.003),
            }
            r = run_single_range(prices, swap_tick_agg, cfg, init_usd, p)
            param_alphas.append(r["alpha"])

            if (i + 1) % 500 == 0:
                print(f"    {i+1}/{N_PARAM}...")

        param_alphas = np.array(param_alphas)
        p_pos = np.mean(param_alphas > 0) * 100
        med = np.median(param_alphas) * 100
        pct5 = np.percentile(param_alphas, 5) * 100
        pct95 = np.percentile(param_alphas, 95) * 100
        mean_a = np.mean(param_alphas) * 100

        print(f"  Results:")
        print(f"    P(alpha > 0) = {p_pos:.1f}%")
        print(f"    Median = {med:+.2f}%, Mean = {mean_a:+.2f}%")
        print(f"    5th = {pct5:+.2f}%, 95th = {pct95:+.2f}%")

        # ── 2. Block Bootstrap (500 paths) ──
        print(f"\n  [2/2] Block Bootstrap (500 paths)...")
        N_BOOT = 500
        boot_alphas = []

        paths = block_bootstrap(prices, swap_tick_agg, cfg, block_hours=4, n_paths=N_BOOT)
        print(f"    Generated {len(paths)} synthetic paths")

        for i, (sp, sa, sta) in enumerate(paths):
            if len(sp) < 10:
                continue
            r = run_single_range(sp, sta, cfg, init_usd, opt)
            boot_alphas.append(r["alpha"])
            if (i + 1) % 200 == 0:
                print(f"    {i+1}/{N_BOOT}...")

        boot_alphas = np.array(boot_alphas)
        bp_pos = np.mean(boot_alphas > 0) * 100
        bmed = np.median(boot_alphas) * 100
        bpct5 = np.percentile(boot_alphas, 5) * 100
        bpct95 = np.percentile(boot_alphas, 95) * 100
        bmean = np.mean(boot_alphas) * 100

        print(f"  Results:")
        print(f"    P(alpha > 0) = {bp_pos:.1f}%")
        print(f"    Median = {bmed:+.2f}%, Mean = {bmean:+.2f}%")
        print(f"    5th = {bpct5:+.2f}%, 95th = {bpct95:+.2f}%")

        # ── Plot: 2 panels side by side ──
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # Param sensitivity
        ax1.hist(param_alphas * 100, bins=60, color="#e67e22", alpha=0.7,
                 edgecolor="white", linewidth=0.5)
        ax1.axvline(0, color="red", linewidth=2, linestyle="--", label="Zero")
        ax1.axvline(baseline["alpha"] * 100, color="#2ecc71", linewidth=2,
                    label=f"Optimal: {baseline['alpha']*100:+.2f}%")
        ax1.axvline(med, color="#f39c12", linewidth=2, linestyle=":",
                    label=f"Median: {med:+.2f}%")
        ax1.set_xlabel("Net Alpha (%)")
        ax1.set_ylabel("Frequency")
        ax1.set_title(f"Param Sensitivity (N={N_PARAM})\n"
                      f"P(α>0)={p_pos:.0f}% | Med={med:+.1f}% | 5th={pct5:+.1f}%")
        ax1.legend(fontsize=9)
        ax1.grid(alpha=0.3)

        # Bootstrap
        ax2.hist(boot_alphas * 100, bins=60, color="#8e44ad", alpha=0.7,
                 edgecolor="white", linewidth=0.5)
        ax2.axvline(0, color="red", linewidth=2, linestyle="--", label="Zero")
        ax2.axvline(baseline["alpha"] * 100, color="#2ecc71", linewidth=2,
                    label=f"Optimal: {baseline['alpha']*100:+.2f}%")
        ax2.axvline(bmed, color="#f39c12", linewidth=2, linestyle=":",
                    label=f"Median: {bmed:+.2f}%")
        ax2.set_xlabel("Net Alpha (%)")
        ax2.set_ylabel("Frequency")
        ax2.set_title(f"Block Bootstrap (N={len(boot_alphas)}, 4h blocks)\n"
                      f"P(α>0)={bp_pos:.0f}% | Med={bmed:+.1f}% | 5th={bpct5:+.1f}%")
        ax2.legend(fontsize=9)
        ax2.grid(alpha=0.3)

        fig.suptitle(f"{pool_label} — Single-Range ±{opt['width_pct']*100:.1f}% Monte Carlo",
                     fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"single_range_mc_{pool_key}.png", dpi=150)
        plt.close(fig)

        results[pool_key] = {
            "optimal_config": {k: v for k, v in opt.items()},
            "baseline_alpha": round(baseline["alpha"] * 100, 2),
            "param_sensitivity": {
                "n": N_PARAM, "p_positive": round(p_pos, 1),
                "median": round(med, 2), "mean": round(mean_a, 2),
                "pct5": round(pct5, 2), "pct95": round(pct95, 2),
            },
            "block_bootstrap": {
                "n": len(boot_alphas), "p_positive": round(bp_pos, 1),
                "median": round(bmed, 2), "mean": round(bmean, 2),
                "pct5": round(bpct5, 2), "pct95": round(bpct95, 2),
            },
        }

    with open(BASE_DIR / "single_range_mc_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # ── Summary comparison table ──
    print(f"\n{'='*60}")
    print("  SUMMARY: Single-Range vs ML 3-Layer")
    print(f"{'='*60}")
    print(f"{'':>30} {'WBTC-USDC':>12} {'USDC-ETH':>12}")
    print(f"  {'─'*54}")

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        r = results[pool_key]

    print(f"  Single-Range (optimal)")
    print(f"    Baseline alpha         {results['wbtc-usdc']['baseline_alpha']:>+10.2f}%  {results['usdc-eth']['baseline_alpha']:>+10.2f}%")
    print(f"    Param P(α>0)          {results['wbtc-usdc']['param_sensitivity']['p_positive']:>10.0f}%  {results['usdc-eth']['param_sensitivity']['p_positive']:>10.0f}%")
    print(f"    Bootstrap P(α>0)      {results['wbtc-usdc']['block_bootstrap']['p_positive']:>10.0f}%  {results['usdc-eth']['block_bootstrap']['p_positive']:>10.0f}%")
    print(f"    Bootstrap median      {results['wbtc-usdc']['block_bootstrap']['median']:>+10.2f}%  {results['usdc-eth']['block_bootstrap']['median']:>+10.2f}%")

    print(f"\n  Done! Charts: charts/single_range_mc_*.png")


if __name__ == "__main__":
    main()
