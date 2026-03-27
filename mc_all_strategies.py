#!/usr/bin/env python3
"""
All-Strategies Monte Carlo Comparison
=======================================
Runs ALL four strategies through the same MC framework:
  1. Omnis      — single narrow ±2.5%, rebalance every 6000 blocks, no trend
  2. Charm      — 3-layer (8.3/74.8/16.9), ±17.85% wide, ±3.9% narrow, NO trend, cd=10000
  3. ML         — 3-layer same as Charm BUT with trend shift (±1.4/0.6), cd=5000
  4. Single-Rng — ±5% BTC (cd=5000), ±14.5% ETH (cd=1500), with trend shift

For each: 1000 param-sensitivity runs (±30% perturb) + 500 block-bootstrap paths.

Outputs:
  - mc_all_results.json
  - charts/mc_all_param_*.png
  - charts/mc_all_boot_*.png
  - charts/mc_all_comparison_*.png
"""

import csv, math, json, random, os, sys
import numpy as np
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from monte_carlo import (
    load_pool_data, block_bootstrap, tick_to_price, price_to_tick, align,
    v3_amounts, v3_liquidity, POOL_FEE,
)
from single_range_sweep import run_single_range

# ─── Strategy Simulators ──────────────────────────────────────────────

def run_omnis(prices, swap_tick_agg, cfg, init_usd, params):
    """
    Omnis strategy: single narrow range, periodic rebalance, no trend shift.
    Rebalances every N blocks unconditionally (time-based, like Omnis vault).
    """
    width_pct = params.get("width_pct", 0.025)       # ±2.5%
    rebal_blocks = int(params.get("rebal_blocks", 6000))
    slippage = params.get("slippage", 0.0015)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    position = None  # (tl, tu, L, pa, pb)
    fee_usdc = 0.0
    n_rb = 0
    last_rb_block = 0
    total_fee_usdc = 0.0

    for block, tick, price in prices:
        # Rebalance trigger: first time OR every rebal_blocks OR out-of-range
        should_rb = False
        if position is None:
            should_rb = True
        elif block - last_rb_block >= rebal_blocks:
            should_rb = True
        else:
            _, _, _, pa, pb = position
            if price < pa or price > pb:
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

            wh = price * width_pct
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

    return {
        "alpha": alpha, "vault_return": vault_return,
        "hodl_return": hodl_return, "fee_bps": fee_bps,
        "rebalances": n_rb, "final_val": final_val,
    }


def run_charm(prices, swap_tick_agg, cfg, init_usd, params):
    """
    Charm strategy: 3-layer (full/wide/narrow), NO trend shift.
    Fixed symmetric ranges, rebalance on edge breach after cooldown.
    """
    wide_pct = params.get("wide_pct", 0.1785)
    narrow_pct = params.get("narrow_pct", 0.039)
    alloc_full = params.get("alloc_full", 0.083)
    alloc_wide = params.get("alloc_wide", 0.748)
    alloc_narrow = params.get("alloc_narrow", 0.169)
    cooldown = int(params.get("cooldown", 10000))
    slippage = params.get("slippage", 0.0015)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    # Normalize allocations
    total_alloc = alloc_full + alloc_wide + alloc_narrow
    alloc_full /= total_alloc
    alloc_wide /= total_alloc
    alloc_narrow /= total_alloc

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    positions = []
    fee_base = 0.0
    fee_usdc = 0.0
    n_rb = 0
    last_rb_block = 0
    total_fee_usdc = 0.0

    def make_ranges(price):
        """Symmetric 3-layer ranges (no trend shift)."""
        wh = price * wide_pct
        nh = price * narrow_pct
        return [
            (align(-887270, ts), align(887270, ts), alloc_full),
            (align(price_to_tick(max(0.01, price - wh), t0, t1, inv), ts),
             align(price_to_tick(price + wh, t0, t1, inv), ts), alloc_wide),
            (align(price_to_tick(max(0.01, price - nh), t0, t1, inv), ts),
             align(price_to_tick(price + nh, t0, t1, inv), ts), alloc_narrow),
        ]

    for block, tick, price in prices:
        should_rb = False
        if not positions:
            should_rb = True
        elif block - last_rb_block >= cooldown:
            _, _, _, _, pa_n, pb_n = positions[-1]  # narrow range
            if price < pa_n or price > pb_n:
                should_rb = True
            elif pb_n > pa_n:
                pct = (price - pa_n) / (pb_n - pa_n)
                if pct < 0.1 or pct > 0.9:
                    should_rb = True

        if should_rb:
            for tl_p, tu_p, L_p, w_p, pa_p, pb_p in positions:
                b, u = v3_amounts(L_p, price, pa_p, pb_p)
                base_bal += b
                usdc_bal += u
            base_bal += fee_base
            usdc_bal += fee_usdc
            total_fee_usdc += fee_usdc + fee_base * price

            if n_rb > 0:
                total_val = base_bal * price + usdc_bal
                narrow_swap_vol = total_val * alloc_narrow * 0.5
                usdc_bal -= narrow_swap_vol * slippage

            fee_base = 0
            fee_usdc = 0

            ranges = make_ranges(price)
            positions = []
            for tl_r, tu_r, w in ranges:
                pa_r = tick_to_price(tl_r, t0, t1, inv)
                pb_r = tick_to_price(tu_r, t0, t1, inv)
                if pa_r > pb_r:
                    pa_r, pb_r = pb_r, pa_r
                alloc_b = base_bal * w
                alloc_u = usdc_bal * w
                L = v3_liquidity(alloc_b, alloc_u, price, pa_r, pb_r)
                if L > 0:
                    used_b, used_u = v3_amounts(L, price, pa_r, pb_r)
                    base_bal -= used_b
                    usdc_bal -= used_u
                positions.append((tl_r, tu_r, L, w, pa_r, pb_r))

            last_rb_block = block
            n_rb += 1

        # Fees
        if positions and block in swap_tick_agg:
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                for tl_p, tu_p, L_p, w_p, pa_p, pb_p in positions:
                    if tl_p <= tick_bucket < tu_p and L_p > 0:
                        fee_usdc += vol_u * POOL_FEE * fee_share * w_p

    # Final
    p_end = prices[-1][2]
    pos_base = sum(v3_amounts(L, p_end, pa, pb)[0] for _, _, L, _, pa, pb in positions)
    pos_usdc = sum(v3_amounts(L, p_end, pa, pb)[1] for _, _, L, _, pa, pb in positions)
    final_val = (pos_base + base_bal + fee_base) * p_end + pos_usdc + usdc_bal + fee_usdc
    total_fee_usdc += fee_usdc + fee_base * p_end

    vault_return = (final_val - init_usd) / init_usd
    hodl_return = ((init_usd / 2 / p0) * p_end + init_usd / 2 - init_usd) / init_usd
    alpha = vault_return - hodl_return
    fee_bps = total_fee_usdc / init_usd * 10000

    return {
        "alpha": alpha, "vault_return": vault_return,
        "hodl_return": hodl_return, "fee_bps": fee_bps,
        "rebalances": n_rb, "final_val": final_val,
    }


def run_ml(prices, swap_tick_agg, cfg, init_usd, params):
    """
    ML (Multi-Layer) strategy: 3-layer WITH trend shift.
    This is the full strategy from monte_carlo.py's run_sim, adapted to
    accept swap_tick_agg directly (no swap_agg needed).
    """
    wide_pct = params.get("wide_pct", 0.1785)
    narrow_pct = params.get("narrow_pct", 0.039)
    alloc_full = params.get("alloc_full", 0.083)
    alloc_wide = params.get("alloc_wide", 0.748)
    alloc_narrow = params.get("alloc_narrow", 0.169)
    trend_thresh = params.get("trend_thresh", 0.20)
    trend_up = params.get("trend_up", 1.4)
    trend_down = params.get("trend_down", 0.6)
    cooldown = int(params.get("cooldown", 5000))
    lookback = int(params.get("lookback", 20))
    slippage = params.get("slippage", 0.0015)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    total_alloc = alloc_full + alloc_wide + alloc_narrow
    alloc_full /= total_alloc
    alloc_wide /= total_alloc
    alloc_narrow /= total_alloc

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    positions = []
    fee_base = 0.0
    fee_usdc = 0.0
    n_rb = 0
    price_history = []
    last_rb_block = 0
    total_fee_usdc = 0.0

    def make_ranges(price):
        if len(price_history) >= lookback:
            r = (price_history[-1] - price_history[-lookback]) / price_history[-lookback]
            t_dir = max(-1, min(1, r / trend_thresh))
        else:
            t_dir = 0

        wh = price * wide_pct
        nh = price * narrow_pct
        if t_dir < -0.2:
            n_lo, n_hi = price - nh * trend_up, price + nh * trend_down
        elif t_dir > 0.2:
            n_lo, n_hi = price - nh * trend_down, price + nh * trend_up
        else:
            n_lo, n_hi = price - nh, price + nh

        return [
            (align(-887270, ts), align(887270, ts), alloc_full),
            (align(price_to_tick(max(0.01, price - wh), t0, t1, inv), ts),
             align(price_to_tick(price + wh, t0, t1, inv), ts), alloc_wide),
            (align(price_to_tick(max(0.01, n_lo), t0, t1, inv), ts),
             align(price_to_tick(n_hi, t0, t1, inv), ts), alloc_narrow),
        ]

    for block, tick, price in prices:
        price_history.append(price)

        should_rb = False
        if not positions:
            should_rb = True
        elif block - last_rb_block >= cooldown:
            _, _, _, _, pa_n, pb_n = positions[-1]
            if price < pa_n or price > pb_n:
                should_rb = True
            elif pb_n > pa_n:
                pct = (price - pa_n) / (pb_n - pa_n)
                if pct < 0.1 or pct > 0.9:
                    should_rb = True

        if should_rb:
            for tl_p, tu_p, L_p, w_p, pa_p, pb_p in positions:
                b, u = v3_amounts(L_p, price, pa_p, pb_p)
                base_bal += b
                usdc_bal += u
            base_bal += fee_base
            usdc_bal += fee_usdc
            total_fee_usdc += fee_usdc + fee_base * price

            if n_rb > 0:
                total_val = base_bal * price + usdc_bal
                narrow_swap_vol = total_val * alloc_narrow * 0.5
                usdc_bal -= narrow_swap_vol * slippage

            fee_base = 0
            fee_usdc = 0

            ranges = make_ranges(price)
            positions = []
            for tl_r, tu_r, w in ranges:
                pa_r = tick_to_price(tl_r, t0, t1, inv)
                pb_r = tick_to_price(tu_r, t0, t1, inv)
                if pa_r > pb_r:
                    pa_r, pb_r = pb_r, pa_r
                alloc_b = base_bal * w
                alloc_u = usdc_bal * w
                L = v3_liquidity(alloc_b, alloc_u, price, pa_r, pb_r)
                if L > 0:
                    used_b, used_u = v3_amounts(L, price, pa_r, pb_r)
                    base_bal -= used_b
                    usdc_bal -= used_u
                positions.append((tl_r, tu_r, L, w, pa_r, pb_r))

            last_rb_block = block
            n_rb += 1

        # Fees
        if positions and block in swap_tick_agg:
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                for tl_p, tu_p, L_p, w_p, pa_p, pb_p in positions:
                    if tl_p <= tick_bucket < tu_p and L_p > 0:
                        fee_usdc += vol_u * POOL_FEE * fee_share * w_p

    # Final
    p_end = prices[-1][2]
    pos_base = sum(v3_amounts(L, p_end, pa, pb)[0] for _, _, L, _, pa, pb in positions)
    pos_usdc = sum(v3_amounts(L, p_end, pa, pb)[1] for _, _, L, _, pa, pb in positions)
    final_val = (pos_base + base_bal + fee_base) * p_end + pos_usdc + usdc_bal + fee_usdc
    total_fee_usdc += fee_usdc + fee_base * p_end

    vault_return = (final_val - init_usd) / init_usd
    hodl_return = ((init_usd / 2 / p0) * p_end + init_usd / 2 - init_usd) / init_usd
    alpha = vault_return - hodl_return
    fee_bps = total_fee_usdc / init_usd * 10000

    return {
        "alpha": alpha, "vault_return": vault_return,
        "hodl_return": hodl_return, "fee_bps": fee_bps,
        "rebalances": n_rb, "final_val": final_val,
    }


# ─── Strategy configurations ─────────────────────────────────────────

# Baseline parameters per strategy per pool
STRATEGY_CONFIGS = {
    "omnis": {
        "wbtc-usdc": {"width_pct": 0.025, "rebal_blocks": 6000, "slippage": 0.0015},
        "usdc-eth":  {"width_pct": 0.025, "rebal_blocks": 6000, "slippage": 0.0015},
    },
    "charm": {
        "wbtc-usdc": {"wide_pct": 0.1785, "narrow_pct": 0.039,
                       "alloc_full": 0.083, "alloc_wide": 0.748, "alloc_narrow": 0.169,
                       "cooldown": 10000, "slippage": 0.0015},
        "usdc-eth":  {"wide_pct": 0.1785, "narrow_pct": 0.039,
                       "alloc_full": 0.083, "alloc_wide": 0.748, "alloc_narrow": 0.169,
                       "cooldown": 10000, "slippage": 0.0015},
    },
    "ml": {
        "wbtc-usdc": {"wide_pct": 0.1785, "narrow_pct": 0.039,
                       "alloc_full": 0.083, "alloc_wide": 0.748, "alloc_narrow": 0.169,
                       "trend_thresh": 0.20, "trend_up": 1.4, "trend_down": 0.6,
                       "cooldown": 5000, "lookback": 20, "slippage": 0.0015},
        "usdc-eth":  {"wide_pct": 0.1785, "narrow_pct": 0.039,
                       "alloc_full": 0.083, "alloc_wide": 0.748, "alloc_narrow": 0.169,
                       "trend_thresh": 0.20, "trend_up": 1.4, "trend_down": 0.6,
                       "cooldown": 5000, "lookback": 20, "slippage": 0.0015},
    },
    "single_range": {
        "wbtc-usdc": {"width_pct": 0.05, "cooldown": 5000, "boundary_pct": 0.05,
                       "trend_shift": True, "trend_thresh": 0.20,
                       "shift_up": 1.4, "shift_down": 0.6, "lookback": 20, "slippage": 0.0015},
        "usdc-eth":  {"width_pct": 0.145, "cooldown": 1500, "boundary_pct": 0.03,
                       "trend_shift": True, "trend_thresh": 0.20,
                       "shift_up": 1.4, "shift_down": 0.6, "lookback": 20, "slippage": 0.0015},
    },
}

# Map strategy name -> simulator function
SIMULATORS = {
    "omnis": run_omnis,
    "charm": run_charm,
    "ml": run_ml,
    "single_range": run_single_range,
}


def perturb_params(base_params, pct=0.30, rng=None):
    """Perturb each numeric parameter by ±pct around the base value."""
    if rng is None:
        rng = np.random.default_rng()
    perturbed = {}
    for k, v in base_params.items():
        if isinstance(v, bool):
            perturbed[k] = v
            continue
        if isinstance(v, (int, float)):
            lo = v * (1 - pct)
            hi = v * (1 + pct)
            if lo > hi:
                lo, hi = hi, lo
            # Ensure positive values for things that must be positive
            lo = max(lo, 1e-6)
            new_val = rng.uniform(lo, hi)
            if isinstance(v, int) and k not in ("slippage",):
                new_val = int(round(new_val))
            perturbed[k] = new_val
        else:
            perturbed[k] = v
    return perturbed


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(BASE_DIR / "charts", exist_ok=True)

    N_PARAM = 1000
    N_BOOT = 500
    PERTURB_PCT = 0.30

    results = {}
    strategy_names = ["omnis", "charm", "ml", "single_range"]
    strategy_labels = {
        "omnis": "Omnis (±2.5% narrow)",
        "charm": "Charm (3-layer, no trend)",
        "ml": "ML (3-layer + trend)",
        "single_range": "Single-Range Optimal",
    }
    strategy_colors = {
        "omnis": "#e74c3c",
        "charm": "#3498db",
        "ml": "#2ecc71",
        "single_range": "#f39c12",
    }

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = "WBTC-USDC" if pool_key == "wbtc-usdc" else "USDC-ETH"
        print(f"\n{'='*70}")
        print(f"  ALL-STRATEGY MONTE CARLO — {pool_label}")
        print(f"{'='*70}")

        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)
        print(f"  Data: {len(prices)} price points, {len(swap_agg)} swap blocks")

        results[pool_key] = {}

        # Pre-generate bootstrap paths once (shared across strategies)
        print(f"\n  Generating {N_BOOT} bootstrap paths (shared)...")
        random.seed(42)
        boot_paths = block_bootstrap(prices, swap_tick_agg, cfg,
                                      block_hours=4, n_paths=N_BOOT)
        print(f"  Got {len(boot_paths)} valid paths")

        for strat_name in strategy_names:
            strat_label = strategy_labels[strat_name]
            base_params = STRATEGY_CONFIGS[strat_name][pool_key]
            sim_func = SIMULATORS[strat_name]

            print(f"\n  ── {strat_label} ──")

            # --- Baseline ---
            baseline = sim_func(prices, swap_tick_agg, cfg, init_usd, base_params)
            print(f"    Baseline: alpha={baseline['alpha']*100:+.2f}%, "
                  f"fee={baseline['fee_bps']:.0f}bps, rb={baseline['rebalances']}")

            # --- Parameter Sensitivity ---
            print(f"    [1/2] Param sensitivity ({N_PARAM} runs, ±{PERTURB_PCT*100:.0f}%)...")
            rng = np.random.default_rng(42)
            param_alphas = []

            for i in range(N_PARAM):
                p = perturb_params(base_params, pct=PERTURB_PCT, rng=rng)
                r = sim_func(prices, swap_tick_agg, cfg, init_usd, p)
                param_alphas.append(r["alpha"])
                if (i + 1) % 250 == 0:
                    print(f"      {i+1}/{N_PARAM}...")

            param_alphas = np.array(param_alphas)
            p_pos = float(np.mean(param_alphas > 0) * 100)
            med = float(np.median(param_alphas) * 100)
            pct5 = float(np.percentile(param_alphas, 5) * 100)
            pct95 = float(np.percentile(param_alphas, 95) * 100)
            mean_a = float(np.mean(param_alphas) * 100)
            std_a = float(np.std(param_alphas) * 100)

            print(f"    P(α>0)={p_pos:.1f}%, median={med:+.2f}%, "
                  f"5th={pct5:+.2f}%, 95th={pct95:+.2f}%")

            # --- Block Bootstrap ---
            print(f"    [2/2] Block bootstrap ({len(boot_paths)} paths)...")
            boot_alphas = []

            for i, (sp, sa, sta) in enumerate(boot_paths):
                if len(sp) < 10:
                    continue
                r = sim_func(sp, sta, cfg, init_usd, base_params)
                boot_alphas.append(r["alpha"])
                if (i + 1) % 200 == 0:
                    print(f"      {i+1}/{len(boot_paths)}...")

            boot_alphas = np.array(boot_alphas)
            bp_pos = float(np.mean(boot_alphas > 0) * 100)
            bmed = float(np.median(boot_alphas) * 100)
            bpct5 = float(np.percentile(boot_alphas, 5) * 100)
            bpct95 = float(np.percentile(boot_alphas, 95) * 100)
            bmean = float(np.mean(boot_alphas) * 100)
            bstd = float(np.std(boot_alphas) * 100)

            print(f"    P(α>0)={bp_pos:.1f}%, median={bmed:+.2f}%, "
                  f"5th={bpct5:+.2f}%, 95th={bpct95:+.2f}%")

            # Store
            results[pool_key][strat_name] = {
                "baseline_alpha": round(baseline["alpha"] * 100, 3),
                "baseline_fee_bps": round(baseline["fee_bps"], 1),
                "baseline_rebalances": baseline["rebalances"],
                "param": {
                    "n_runs": N_PARAM,
                    "perturb_pct": PERTURB_PCT,
                    "p_positive": round(p_pos, 1),
                    "median": round(med, 3),
                    "mean": round(mean_a, 3),
                    "pct5": round(pct5, 3),
                    "pct95": round(pct95, 3),
                    "std": round(std_a, 3),
                    "histogram": [round(x * 100, 3) for x in param_alphas.tolist()],
                },
                "bootstrap": {
                    "n_paths": len(boot_alphas),
                    "block_hours": 4,
                    "p_positive": round(bp_pos, 1),
                    "median": round(bmed, 3),
                    "mean": round(bmean, 3),
                    "pct5": round(bpct5, 3),
                    "pct95": round(bpct95, 3),
                    "std": round(bstd, 3),
                    "histogram": [round(x * 100, 3) for x in boot_alphas.tolist()],
                },
            }

        # ── Per-pool charts ──

        # 1. Param sensitivity overlay
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        for idx, sn in enumerate(strategy_names):
            ax = axes[idx // 2, idx % 2]
            hist_data = results[pool_key][sn]["param"]["histogram"]
            ax.hist(hist_data, bins=50, color=strategy_colors[sn], alpha=0.7,
                    edgecolor="white", linewidth=0.5)
            ax.axvline(0, color="red", linewidth=1.5, linestyle="--", label="Zero")
            bl = results[pool_key][sn]["baseline_alpha"]
            ax.axvline(bl, color="black", linewidth=1.5,
                       label=f"Baseline: {bl:+.2f}%")
            med = results[pool_key][sn]["param"]["median"]
            ax.axvline(med, color="grey", linewidth=1.5, linestyle=":",
                       label=f"Median: {med:+.2f}%")
            pp = results[pool_key][sn]["param"]["p_positive"]
            p5 = results[pool_key][sn]["param"]["pct5"]
            p95 = results[pool_key][sn]["param"]["pct95"]
            ax.set_title(f"{strategy_labels[sn]}\n"
                         f"P(α>0)={pp:.0f}% | Med={med:+.1f}% | "
                         f"[{p5:+.1f}%, {p95:+.1f}%]",
                         fontsize=10)
            ax.set_xlabel("Alpha (%)")
            ax.set_ylabel("Count")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)

        fig.suptitle(f"{pool_label} — Param Sensitivity (N={N_PARAM}, ±{PERTURB_PCT*100:.0f}% perturb)",
                     fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"mc_all_param_{pool_key}.png", dpi=150)
        plt.close(fig)

        # 2. Bootstrap overlay
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        for idx, sn in enumerate(strategy_names):
            ax = axes[idx // 2, idx % 2]
            hist_data = results[pool_key][sn]["bootstrap"]["histogram"]
            ax.hist(hist_data, bins=50, color=strategy_colors[sn], alpha=0.7,
                    edgecolor="white", linewidth=0.5)
            ax.axvline(0, color="red", linewidth=1.5, linestyle="--", label="Zero")
            bl = results[pool_key][sn]["baseline_alpha"]
            ax.axvline(bl, color="black", linewidth=1.5,
                       label=f"Baseline: {bl:+.2f}%")
            bm = results[pool_key][sn]["bootstrap"]["median"]
            ax.axvline(bm, color="grey", linewidth=1.5, linestyle=":",
                       label=f"Median: {bm:+.2f}%")
            bp = results[pool_key][sn]["bootstrap"]["p_positive"]
            b5 = results[pool_key][sn]["bootstrap"]["pct5"]
            b95 = results[pool_key][sn]["bootstrap"]["pct95"]
            ax.set_title(f"{strategy_labels[sn]}\n"
                         f"P(α>0)={bp:.0f}% | Med={bm:+.1f}% | "
                         f"[{b5:+.1f}%, {b95:+.1f}%]",
                         fontsize=10)
            ax.set_xlabel("Alpha (%)")
            ax.set_ylabel("Count")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)

        fig.suptitle(f"{pool_label} — Block Bootstrap (N={N_BOOT}, 4h blocks)",
                     fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"mc_all_boot_{pool_key}.png", dpi=150)
        plt.close(fig)

        # 3. Comparison bar chart
        fig, axes = plt.subplots(1, 3, figsize=(16, 5))

        # 3a. Baseline alpha
        ax = axes[0]
        vals = [results[pool_key][sn]["baseline_alpha"] for sn in strategy_names]
        bars = ax.bar([strategy_labels[sn].split(" (")[0] for sn in strategy_names],
                      vals, color=[strategy_colors[sn] for sn in strategy_names],
                      edgecolor="white", linewidth=1)
        ax.axhline(0, color="red", linewidth=1, linestyle="--")
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                    f"{v:+.2f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.set_ylabel("Alpha (%)")
        ax.set_title("Baseline Alpha")
        ax.grid(alpha=0.3, axis="y")

        # 3b. Param P(alpha>0)
        ax = axes[1]
        vals_param = [results[pool_key][sn]["param"]["p_positive"] for sn in strategy_names]
        vals_boot = [results[pool_key][sn]["bootstrap"]["p_positive"] for sn in strategy_names]
        x = np.arange(len(strategy_names))
        w = 0.35
        b1 = ax.bar(x - w/2, vals_param, w, label="Param Sensitivity",
                     color=[strategy_colors[sn] for sn in strategy_names],
                     alpha=0.8, edgecolor="white")
        b2 = ax.bar(x + w/2, vals_boot, w, label="Bootstrap",
                     color=[strategy_colors[sn] for sn in strategy_names],
                     alpha=0.4, edgecolor="white", hatch="//")
        ax.axhline(50, color="grey", linewidth=1, linestyle=":")
        for bars_set in [b1, b2]:
            for bar in bars_set:
                h = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2, h + 0.5,
                        f"{h:.0f}%", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([strategy_labels[sn].split(" (")[0] for sn in strategy_names],
                           fontsize=9)
        ax.set_ylabel("P(alpha > 0) %")
        ax.set_title("Probability of Positive Alpha")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3, axis="y")

        # 3c. Median alpha
        ax = axes[2]
        vals_param_med = [results[pool_key][sn]["param"]["median"] for sn in strategy_names]
        vals_boot_med = [results[pool_key][sn]["bootstrap"]["median"] for sn in strategy_names]
        b1 = ax.bar(x - w/2, vals_param_med, w, label="Param Sensitivity",
                     color=[strategy_colors[sn] for sn in strategy_names],
                     alpha=0.8, edgecolor="white")
        b2 = ax.bar(x + w/2, vals_boot_med, w, label="Bootstrap",
                     color=[strategy_colors[sn] for sn in strategy_names],
                     alpha=0.4, edgecolor="white", hatch="//")
        ax.axhline(0, color="red", linewidth=1, linestyle="--")
        for bars_set in [b1, b2]:
            for bar in bars_set:
                h = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2,
                        h + (0.2 if h >= 0 else -0.5),
                        f"{h:+.1f}%", ha="center",
                        va="bottom" if h >= 0 else "top", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([strategy_labels[sn].split(" (")[0] for sn in strategy_names],
                           fontsize=9)
        ax.set_ylabel("Median Alpha (%)")
        ax.set_title("Median Alpha Across MC Runs")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3, axis="y")

        fig.suptitle(f"{pool_label} — Strategy Comparison (Monte Carlo)",
                     fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"mc_all_comparison_{pool_key}.png", dpi=150)
        plt.close(fig)

    # ─── Save JSON ────────────────────────────────────────────────────
    with open(BASE_DIR / "mc_all_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # ─── Summary table ────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("  ALL-STRATEGY MONTE CARLO SUMMARY")
    print(f"{'='*80}")

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = "WBTC-USDC" if pool_key == "wbtc-usdc" else "USDC-ETH"
        print(f"\n  {pool_label}")
        print(f"  {'Strategy':<24} {'Baseline':>9} {'P(α>0)':>8} {'Median':>8} "
              f"{'[5th':>7} {'95th]':>7} | {'Boot P+':>8} {'Boot Med':>9}")
        print(f"  {'─'*90}")
        for sn in strategy_names:
            r = results[pool_key][sn]
            print(f"  {strategy_labels[sn]:<24} "
                  f"{r['baseline_alpha']:>+8.2f}% "
                  f"{r['param']['p_positive']:>7.1f}% "
                  f"{r['param']['median']:>+7.2f}% "
                  f"{r['param']['pct5']:>+6.2f}% "
                  f"{r['param']['pct95']:>+6.2f}% | "
                  f"{r['bootstrap']['p_positive']:>7.1f}% "
                  f"{r['bootstrap']['median']:>+8.2f}%")

    print(f"\n  Output: mc_all_results.json")
    print(f"  Charts: charts/mc_all_param_*.png, charts/mc_all_boot_*.png, charts/mc_all_comparison_*.png")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
