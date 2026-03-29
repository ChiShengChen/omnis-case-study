#!/usr/bin/env python3
"""
Monte Carlo v2: All 6 strategies with WIDE parameter ranges.
Fixes the ±30% narrow perturbation issue from mc_all_strategies.py.
"""

import json, os, sys
import numpy as np
from pathlib import Path
from monte_carlo import load_pool_data, run_sim, block_bootstrap, POOL_FEE
from single_range_sweep import run_single_range
from rv_width_strategy import run_rv_width, run_lazy_return

BASE_DIR = Path(__file__).parent
N_PARAM = 1000
N_BOOT = 500


def run_omnis(prices, swap_tick_agg, cfg, init_usd, params):
    """Omnis-style: single narrow range, time-based rebalance."""
    return run_single_range(prices, swap_tick_agg, cfg, init_usd, {
        "width_pct": params.get("width_pct", 0.025),
        "trend_shift": False,
        "cooldown": params.get("cooldown", 6000),
        "boundary_pct": params.get("boundary_pct", 0.5),  # rebalance before hitting edge
        "slippage": params.get("slippage", 0.0015),
    })


def run_charm(prices, swap_tick_agg, cfg, init_usd, params):
    """Charm-style: 3-layer, symmetric (no trend shift)."""
    return run_sim(prices, {}, swap_tick_agg, cfg, init_usd, {
        "wide_pct": params.get("wide_pct", 0.1785),
        "narrow_pct": params.get("narrow_pct", 0.039),
        "alloc_full": params.get("alloc_full", 0.083),
        "alloc_wide": params.get("alloc_wide", 0.748),
        "alloc_narrow": params.get("alloc_narrow", 0.169),
        "trend_thresh": 999,  # effectively no trend
        "cooldown": params.get("cooldown", 10000),
        "slippage": params.get("slippage", 0.0015),
    })


def run_ml(prices, swap_agg, swap_tick_agg, cfg, init_usd, params):
    """ML: 3-layer with trend shift."""
    return run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, params)


# Wide parameter ranges for each strategy
PARAM_RANGES = {
    "omnis": lambda rng: {
        "width_pct": rng.uniform(0.015, 0.05),
        "cooldown": rng.uniform(2000, 15000),
        "boundary_pct": rng.uniform(0.1, 0.9),
        "slippage": rng.uniform(0.0005, 0.003),
    },
    "charm": lambda rng: {
        "wide_pct": rng.uniform(0.10, 0.25),
        "narrow_pct": rng.uniform(0.02, 0.06),
        "alloc_full": rng.uniform(0.03, 0.15),
        "alloc_wide": rng.uniform(0.55, 0.90),
        "alloc_narrow": rng.uniform(0.08, 0.30),
        "cooldown": rng.uniform(5000, 30000),
        "slippage": rng.uniform(0.0005, 0.003),
    },
    "ml": lambda rng: {
        "wide_pct": rng.uniform(0.10, 0.25),
        "narrow_pct": rng.uniform(0.02, 0.06),
        "alloc_full": rng.uniform(0.03, 0.15),
        "alloc_wide": rng.uniform(0.55, 0.90),
        "alloc_narrow": rng.uniform(0.08, 0.30),
        "trend_thresh": rng.uniform(0.10, 0.40),
        "trend_up": rng.uniform(1.1, 1.8),
        "trend_down": rng.uniform(0.3, 0.9),
        "cooldown": rng.uniform(2000, 15000),
        "lookback": int(rng.uniform(10, 40)),
        "slippage": rng.uniform(0.0005, 0.003),
    },
    "single_range": lambda rng: {
        "width_pct": rng.uniform(0.03, 0.20),
        "trend_shift": True,
        "trend_thresh": rng.uniform(0.10, 0.40),
        "shift_up": rng.uniform(1.1, 1.8),
        "shift_down": rng.uniform(0.3, 0.9),
        "cooldown": rng.uniform(1000, 15000),
        "boundary_pct": rng.uniform(0.02, 0.15),
        "slippage": rng.uniform(0.0005, 0.003),
    },
    "rv_width": lambda rng: {
        "k": rng.uniform(0.5, 4.0),
        "min_width": rng.uniform(0.02, 0.05),
        "max_width": rng.uniform(0.15, 0.30),
        "cooldown": rng.uniform(2000, 15000),
        "vol_window": int(rng.uniform(50, 300)),
        "slippage": rng.uniform(0.0005, 0.003),
        "trend_shift": bool(rng.choice([True, False])),
    },
    "lazy_return": lambda rng: {
        "width_pct": rng.uniform(0.05, 0.25),
        "return_pct": rng.uniform(0.2, 0.8),
        "slippage": rng.uniform(0.0005, 0.003),
    },
}

# Baseline params
SR_BASELINE = {
    "wbtc-usdc": {"width_pct": 0.05, "cooldown": 5000, "boundary_pct": 0.05, "trend_shift": True},
    "usdc-eth": {"width_pct": 0.145, "cooldown": 1500, "boundary_pct": 0.03, "trend_shift": True},
}
RV_BASELINE = {
    "wbtc-usdc": {"k": 1.5, "cooldown": 5000},
    "usdc-eth": {"k": 3.0, "cooldown": 5000},
}
LAZY_BASELINE = {
    "wbtc-usdc": {"width_pct": 0.07, "return_pct": 0.7},
    "usdc-eth": {"width_pct": 0.07, "return_pct": 0.7},
}


def mc_strategy(name, run_fn, prices, swap_agg, swap_tick_agg, cfg, init_usd,
                baseline_params, param_range_fn, boot_paths, rng):
    """Run MC for one strategy: baseline + param sensitivity + bootstrap."""

    # Baseline
    if name in ("ml",):
        baseline = run_fn(prices, swap_agg, swap_tick_agg, cfg, init_usd, baseline_params)
    elif name in ("omnis", "charm"):
        baseline = run_fn(prices, swap_tick_agg, cfg, init_usd, baseline_params)
    else:
        baseline = run_fn(prices, swap_tick_agg, cfg, init_usd, baseline_params)

    print(f"    Baseline α={baseline['alpha']*100:+.2f}%, rb={baseline['rebalances']}")

    # Param sensitivity
    param_alphas = []
    for i in range(N_PARAM):
        p = param_range_fn(rng)
        if name in ("ml",):
            r = run_fn(prices, swap_agg, swap_tick_agg, cfg, init_usd, p)
        else:
            r = run_fn(prices, swap_tick_agg, cfg, init_usd, p)
        param_alphas.append(r["alpha"])
        if (i + 1) % 250 == 0:
            print(f"      param {i+1}/{N_PARAM}...")
    param_alphas = np.array(param_alphas)

    # Bootstrap
    boot_alphas = []
    for i, (sp, sa, sta) in enumerate(boot_paths):
        if len(sp) < 10:
            continue
        if name in ("ml",):
            r = run_fn(sp, sa, sta, cfg, init_usd, baseline_params)
        else:
            r = run_fn(sp, sta, cfg, init_usd, baseline_params)
        boot_alphas.append(r["alpha"])
        if (i + 1) % 200 == 0:
            print(f"      boot {i+1}/{N_BOOT}...")
    boot_alphas = np.array(boot_alphas)

    return {
        "baseline_alpha": round(baseline["alpha"] * 100, 3),
        "rebalances": baseline["rebalances"],
        "param": {
            "p_positive": round(np.mean(param_alphas > 0) * 100, 1),
            "median": round(np.median(param_alphas) * 100, 2),
            "mean": round(np.mean(param_alphas) * 100, 2),
            "pct5": round(np.percentile(param_alphas, 5) * 100, 2),
            "pct95": round(np.percentile(param_alphas, 95) * 100, 2),
            "histogram": [round(x * 100, 3) for x in param_alphas.tolist()],
        },
        "bootstrap": {
            "p_positive": round(np.mean(boot_alphas > 0) * 100, 1),
            "median": round(np.median(boot_alphas) * 100, 2),
            "mean": round(np.mean(boot_alphas) * 100, 2),
            "pct5": round(np.percentile(boot_alphas, 5) * 100, 2),
            "pct95": round(np.percentile(boot_alphas, 95) * 100, 2),
            "histogram": [round(x * 100, 3) for x in boot_alphas.tolist()],
        },
    }


def main():
    os.makedirs(BASE_DIR / "charts", exist_ok=True)
    results = {}
    rng = np.random.default_rng(42)

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = pool_key.upper()
        print(f"\n{'='*60}")
        print(f"  MC v2 — {pool_label} (wide ranges, 6 strategies)")
        print(f"{'='*60}")

        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)
        paths = block_bootstrap(prices, swap_tick_agg, cfg, block_hours=4, n_paths=N_BOOT)
        print(f"  {len(paths)} bootstrap paths generated")

        pool_results = {}

        strategies = [
            ("omnis", run_omnis, {}, PARAM_RANGES["omnis"]),
            ("charm", run_charm, {}, PARAM_RANGES["charm"]),
            ("ml", lambda p, sa, sta, c, iu, params: run_ml(p, sa, sta, c, iu, params),
             {}, PARAM_RANGES["ml"]),
            ("single_range", run_single_range, SR_BASELINE[pool_key], PARAM_RANGES["single_range"]),
            ("rv_width", run_rv_width, RV_BASELINE[pool_key], PARAM_RANGES["rv_width"]),
            ("lazy_return", run_lazy_return, LAZY_BASELINE[pool_key], PARAM_RANGES["lazy_return"]),
        ]

        for name, fn, baseline_p, param_fn in strategies:
            print(f"\n  [{name}]")
            pool_results[name] = mc_strategy(
                name, fn, prices, swap_agg, swap_tick_agg, cfg, init_usd,
                baseline_p, param_fn, paths, rng
            )

        results[pool_key] = pool_results

    with open(BASE_DIR / "mc_all_v2_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for pool_key in results:
        print(f"\n  {pool_key.upper()}:")
        print(f"  {'Strategy':>15} {'Baseline':>10} {'Param P':>8} {'Boot P':>8} {'Boot Med':>10}")
        for s in results[pool_key]:
            d = results[pool_key][s]
            print(f"  {s:>15} {d['baseline_alpha']:>+9.2f}% {d['param']['p_positive']:>7.0f}% {d['bootstrap']['p_positive']:>7.0f}% {d['bootstrap']['median']:>+9.2f}%")

    print(f"\n  Saved to mc_all_v2_results.json")


if __name__ == "__main__":
    main()
