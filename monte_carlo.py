#!/usr/bin/env python3
"""
Monte Carlo Robustness Analysis for Multi-Layer Strategy
=========================================================
1. Parameter Sensitivity: 10,000 runs with random parameter perturbation
2. Block Bootstrap: 1,000 synthetic price paths via block resampling

Outputs:
  - monte_carlo_results.json (for dashboard)
  - charts/mc_param_sensitivity.png
  - charts/mc_bootstrap.png
"""

import csv, math, json, random, os, sys
import numpy as np
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).parent

# ─── V3 Math (from generate_backtest_dashboard.py) ───────────────────

def tick_to_price(tick, t0_dec, t1_dec, invert):
    if tick <= -887270: return 0.01
    if tick >= 887270: return 1e12
    raw = 1.0001 ** tick
    human = raw * (10 ** (t0_dec - t1_dec))
    return 1.0 / human if invert and human > 0 else human

def price_to_tick(price, t0_dec, t1_dec, invert):
    if invert:
        raw_h = 1.0 / price if price > 0 else 1e-18
    else:
        raw_h = price
    raw = raw_h / (10 ** (t0_dec - t1_dec))
    if raw <= 0: return -887270
    return int(math.floor(math.log(raw) / math.log(1.0001)))

def align(tick, sp=10):
    return (tick // sp) * sp

def v3_amounts(L, price, pa, pb):
    if pa <= 0 or pb <= pa or L <= 0:
        return 0, 0
    sa, sb = math.sqrt(pa), math.sqrt(pb)
    if price <= pa:
        return L * (1/sa - 1/sb), 0
    elif price >= pb:
        return 0, L * (sb - sa)
    else:
        sp = math.sqrt(price)
        return L * (1/sp - 1/sb), L * (sp - sa)

def v3_liquidity(base_amt, quote_amt, price, pa, pb):
    if pa <= 0 or pb <= pa: return 0
    sa, sb = math.sqrt(pa), math.sqrt(pb)
    if price <= pa:
        dx = 1/sa - 1/sb
        return base_amt / dx if dx > 0 else 0
    elif price >= pb:
        dy = sb - sa
        return quote_amt / dy if dy > 0 else 0
    else:
        sp = math.sqrt(price)
        dx = 1/sp - 1/sb
        dy = sp - sa
        Lx = base_amt / dx if dx > 0 else float('inf')
        Ly = quote_amt / dy if dy > 0 else float('inf')
        return min(Lx, Ly)

POOL_FEE = 0.0005

# ─── Data loading ────────────────────────────────────────────────────

def load_pool_data(pool_key):
    """Load price_series and pre-aggregated swap volumes per price block."""
    if pool_key == "wbtc-usdc":
        data_dir = BASE_DIR / "data"
        t0, t1, inv = 8, 6, False
        fee_share = 0.00158
        init_usd = 2600.0
    else:
        data_dir = BASE_DIR / "data_eth"
        t0, t1, inv = 6, 18, True
        fee_share = 0.00133
        init_usd = 2134.0

    prices = []
    with open(data_dir / "price_series.csv") as f:
        for row in csv.DictReader(f):
            prices.append((int(row["block"]), int(row["tick"]), float(row["price"])))
    prices.sort()

    # Load swaps — use USDC-side volume, pre-aggregate by price block
    swap_file = data_dir / "swaps.csv"
    raw_swaps = []
    opener = open
    fname = swap_file
    if not swap_file.exists():
        import gzip
        opener = lambda f: gzip.open(f, "rt")
        fname = str(swap_file) + ".gz"

    with opener(fname) as f:
        for row in csv.DictReader(f):
            if inv:
                vol_usdc = abs(int(row["amount0"])) / (10**t0)
            else:
                vol_usdc = abs(int(row["amount1"])) / (10**t1)
            raw_swaps.append((int(row["block"]), int(row["tick"]), vol_usdc))
    raw_swaps.sort()

    # Pre-aggregate: for each price block, sum vol_usdc by tick bucket (per 10 ticks)
    # This is the main optimization: instead of scanning 187K swaps per sim,
    # we scan ~4K pre-aggregated entries
    price_blocks = sorted(set(b for b, _, _ in prices))
    block_set = set(price_blocks)

    # Map each swap to its nearest price block (the one at or before it)
    # Build: swap_by_price_block[block] = total_vol_usdc (simplified: ignore tick filtering)
    # For tick filtering, also store per-tick volumes
    from collections import defaultdict
    swap_agg = defaultdict(float)  # block -> total_vol_usdc
    swap_tick_agg = defaultdict(lambda: defaultdict(float))  # block -> {tick_bucket -> vol}

    pi = 0
    for sb, stk, svol in raw_swaps:
        # Find the price block this swap belongs to
        while pi < len(price_blocks) - 1 and price_blocks[pi + 1] <= sb:
            pi += 1
        pb = price_blocks[pi]
        swap_agg[pb] += svol
        tick_bucket = (stk // 10) * 10
        swap_tick_agg[pb][tick_bucket] += svol

    cfg = {"t0_dec": t0, "t1_dec": t1, "invert": inv,
           "fee_share": fee_share, "tick_spacing": 10}
    return prices, swap_agg, swap_tick_agg, cfg, init_usd


# ─── Fast simulation (returns alpha only) ────────────────────────────

def run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, params):
    """
    Run ML strategy with given parameters. Returns dict with alpha, fee_bps, rebalances.
    Uses pre-aggregated swap data for speed.
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
    price_history = []
    last_rb_block = 0
    total_fee_usdc = 0.0

    def make_ranges(price):
        # Trend
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
                if pa_r > pb_r: pa_r, pb_r = pb_r, pa_r
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

        # Fees (using pre-aggregated swap volumes)
        if positions and block in swap_tick_agg:
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                for tl_p, tu_p, L_p, w_p, pa_p, pb_p in positions:
                    if tl_p <= tick_bucket < tu_p and L_p > 0:
                        fee_usdc += vol_u * POOL_FEE * fee_share * w_p

    # Final valuation
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
        "alpha": alpha,
        "vault_return": vault_return,
        "hodl_return": hodl_return,
        "fee_bps": fee_bps,
        "rebalances": n_rb,
        "final_val": final_val,
    }


# ─── Block Bootstrap ─────────────────────────────────────────────────

def block_bootstrap(prices, swap_tick_agg, cfg, block_hours=4, n_paths=1000):
    """
    Cut price data into time blocks, resample to create synthetic paths.
    Returns list of (synth_prices, synth_swap_agg, synth_swap_tick_agg) tuples.
    """
    from collections import defaultdict

    if len(prices) < 10:
        return []

    blocks_per_chunk = block_hours * 3600
    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]

    # Group prices into chunks, carry swap_tick_agg along
    chunks = []
    chunk_prices = []
    chunk_swap_ticks = {}  # block -> {tick_bucket -> vol}
    chunk_start = prices[0][0]

    for block, tick, price in prices:
        if block - chunk_start >= blocks_per_chunk and chunk_prices:
            chunks.append((chunk_prices[:], dict(chunk_swap_ticks)))
            chunk_prices = []
            chunk_swap_ticks = {}
            chunk_start = block
        chunk_prices.append((block, tick, price))
        if block in swap_tick_agg:
            chunk_swap_ticks[block] = dict(swap_tick_agg[block])

    if chunk_prices:
        chunks.append((chunk_prices[:], dict(chunk_swap_ticks)))

    if len(chunks) < 3:
        return []

    n_chunks_needed = len(chunks)
    paths = []

    for _ in range(n_paths):
        chosen = [random.choice(chunks) for _ in range(n_chunks_needed)]

        synth_prices = []
        synth_swap_agg = {}
        synth_swap_tick_agg = {}
        current_block = 0
        price_level = chosen[0][0][0][2]

        for chunk_p, chunk_st in chosen:
            if not chunk_p:
                continue
            base_block = chunk_p[0][0]
            base_price = chunk_p[0][2]

            for block, tick, price in chunk_p:
                new_block = current_block + (block - base_block)
                ret = price / base_price if base_price > 0 else 1.0
                new_price = price_level * ret
                new_tick = price_to_tick(new_price, t0, t1, inv)
                synth_prices.append((new_block, new_tick, new_price))

                # Carry swap data
                if block in chunk_st:
                    total_vol = sum(chunk_st[block].values())
                    synth_swap_agg[new_block] = total_vol
                    synth_swap_tick_agg[new_block] = dict(chunk_st[block])

            last_ret = chunk_p[-1][2] / base_price if base_price > 0 else 1.0
            price_level *= last_ret
            current_block += chunk_p[-1][0] - base_block + 100

        paths.append((synth_prices, synth_swap_agg, synth_swap_tick_agg))

    return paths


# ─── Main ────────────────────────────────────────────────────────────

def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(BASE_DIR / "charts", exist_ok=True)

    results = {}

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = "WBTC-USDC" if pool_key == "wbtc-usdc" else "USDC-ETH"
        print(f"\n{'='*60}")
        print(f"  Monte Carlo — {pool_label}")
        print(f"{'='*60}")

        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)
        print(f"  Loaded {len(prices)} price points, {len(swap_agg)} swap blocks")

        # ── Baseline ──
        baseline = run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, {})
        print(f"  Baseline alpha: {baseline['alpha']*100:+.2f}%")

        # ── 1. Parameter Sensitivity (10,000 runs) ──
        print(f"\n  [1/2] Parameter Sensitivity (2,000 runs)...")
        np.random.seed(42)
        N_PARAM = 2000
        param_alphas = []
        param_details = []

        for i in range(N_PARAM):
            p = {
                "wide_pct": np.random.uniform(0.12, 0.25),
                "narrow_pct": np.random.uniform(0.02, 0.06),
                "alloc_full": np.random.uniform(0.03, 0.15),
                "alloc_wide": np.random.uniform(0.55, 0.90),
                "alloc_narrow": np.random.uniform(0.08, 0.30),
                "trend_thresh": np.random.uniform(0.10, 0.40),
                "trend_up": np.random.uniform(1.1, 1.8),
                "trend_down": np.random.uniform(0.3, 0.9),
                "cooldown": np.random.uniform(2000, 10000),
                "lookback": np.random.randint(10, 40),
                "slippage": np.random.uniform(0.0005, 0.003),
            }
            r = run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, p)
            param_alphas.append(r["alpha"])
            if i < 100:  # keep details for first 100
                param_details.append({**p, "alpha": r["alpha"],
                                       "rebalances": r["rebalances"]})

            if (i + 1) % 500 == 0:
                print(f"    {i+1}/{N_PARAM}...")

        param_alphas = np.array(param_alphas)
        p_positive = np.mean(param_alphas > 0) * 100
        median_alpha = np.median(param_alphas) * 100
        pct5 = np.percentile(param_alphas, 5) * 100
        pct95 = np.percentile(param_alphas, 95) * 100
        mean_alpha = np.mean(param_alphas) * 100

        print(f"  Results:")
        print(f"    P(alpha > 0) = {p_positive:.1f}%")
        print(f"    Median alpha = {median_alpha:+.2f}%")
        print(f"    Mean alpha   = {mean_alpha:+.2f}%")
        print(f"    5th pct      = {pct5:+.2f}%")
        print(f"    95th pct     = {pct95:+.2f}%")

        # Plot
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.hist(param_alphas * 100, bins=80, color="#4A90D9", alpha=0.7,
                edgecolor="white", linewidth=0.5)
        ax.axvline(0, color="red", linewidth=2, linestyle="--", label="Zero alpha")
        ax.axvline(baseline["alpha"] * 100, color="#2ecc71", linewidth=2,
                   label=f"Baseline: {baseline['alpha']*100:+.2f}%")
        ax.axvline(median_alpha, color="#f39c12", linewidth=2, linestyle=":",
                   label=f"Median: {median_alpha:+.2f}%")

        ax.set_xlabel("Net Alpha (%)", fontsize=12)
        ax.set_ylabel("Frequency", fontsize=12)
        ax.set_title(f"{pool_label} — Parameter Sensitivity (N={N_PARAM:,})\n"
                     f"P(α>0) = {p_positive:.1f}%  |  Median = {median_alpha:+.2f}%  |  "
                     f"5th = {pct5:+.2f}%  |  95th = {pct95:+.2f}%",
                     fontsize=13)
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"mc_param_sensitivity_{pool_key}.png", dpi=150)
        plt.close(fig)

        # ── 2. Block Bootstrap (1,000 paths) ──
        print(f"\n  [2/2] Block Bootstrap (500 synthetic paths)...")
        N_BOOT = 500
        boot_alphas = []

        paths = block_bootstrap(prices, swap_tick_agg, cfg, block_hours=4, n_paths=N_BOOT)
        print(f"    Generated {len(paths)} synthetic paths")

        for i, (sp, sa, sta) in enumerate(paths):
            if len(sp) < 10:
                continue
            r = run_sim(sp, sa, sta, cfg, init_usd, {})
            boot_alphas.append(r["alpha"])
            if (i + 1) % 200 == 0:
                print(f"    {i+1}/{N_BOOT}...")

        boot_alphas = np.array(boot_alphas)
        bp_positive = np.mean(boot_alphas > 0) * 100
        bmedian = np.median(boot_alphas) * 100
        bpct5 = np.percentile(boot_alphas, 5) * 100
        bpct95 = np.percentile(boot_alphas, 95) * 100
        bmean = np.mean(boot_alphas) * 100

        print(f"  Results:")
        print(f"    P(alpha > 0) = {bp_positive:.1f}%")
        print(f"    Median alpha = {bmedian:+.2f}%")
        print(f"    Mean alpha   = {bmean:+.2f}%")
        print(f"    5th pct      = {bpct5:+.2f}%")
        print(f"    95th pct     = {bpct95:+.2f}%")

        # Plot
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.hist(boot_alphas * 100, bins=60, color="#9B59B6", alpha=0.7,
                edgecolor="white", linewidth=0.5)
        ax.axvline(0, color="red", linewidth=2, linestyle="--", label="Zero alpha")
        ax.axvline(baseline["alpha"] * 100, color="#2ecc71", linewidth=2,
                   label=f"Baseline: {baseline['alpha']*100:+.2f}%")
        ax.axvline(bmedian, color="#f39c12", linewidth=2, linestyle=":",
                   label=f"Median: {bmedian:+.2f}%")

        ax.set_xlabel("Net Alpha (%)", fontsize=12)
        ax.set_ylabel("Frequency", fontsize=12)
        ax.set_title(f"{pool_label} — Block Bootstrap (N={len(boot_alphas):,}, 4h blocks)\n"
                     f"P(α>0) = {bp_positive:.1f}%  |  Median = {bmedian:+.2f}%  |  "
                     f"5th = {bpct5:+.2f}%  |  95th = {bpct95:+.2f}%",
                     fontsize=13)
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(BASE_DIR / "charts" / f"mc_bootstrap_{pool_key}.png", dpi=150)
        plt.close(fig)

        # Store results
        results[pool_key] = {
            "baseline_alpha": round(baseline["alpha"] * 100, 2),
            "param_sensitivity": {
                "n_runs": N_PARAM,
                "p_positive": round(p_positive, 1),
                "median": round(median_alpha, 2),
                "mean": round(mean_alpha, 2),
                "pct5": round(pct5, 2),
                "pct95": round(pct95, 2),
                "std": round(np.std(param_alphas) * 100, 2),
                "histogram": [round(x * 100, 3) for x in param_alphas.tolist()],
            },
            "block_bootstrap": {
                "n_paths": len(boot_alphas),
                "block_hours": 4,
                "p_positive": round(bp_positive, 1),
                "median": round(bmedian, 2),
                "mean": round(bmean, 2),
                "pct5": round(bpct5, 2),
                "pct95": round(bpct95, 2),
                "std": round(np.std(boot_alphas) * 100, 2),
                "histogram": [round(x * 100, 3) for x in boot_alphas.tolist()],
            },
        }

    # Save JSON
    with open(BASE_DIR / "monte_carlo_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print("  Done!")
    print(f"  Charts: charts/mc_param_sensitivity_*.png, charts/mc_bootstrap_*.png")
    print(f"  Data:   monte_carlo_results.json")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
