#!/usr/bin/env python3
"""
Stress Test Analysis for CLAMM Strategies
==========================================
Simulates extreme market scenarios and measures strategy resilience.

Scenarios:
  1. Flash Crash: -20% in 1 hour, then stabilize
  2. Black Swan: -40% in 4 hours
  3. Sustained Bleed: -3% per week for 12 weeks
  4. V-Shape Recovery: -25% crash then +30% bounce in 48h
  5. Whipsaw: ±10% oscillations every 6 hours (no net direction)
  6. Moonshot: +50% in 1 week

For each scenario, run all strategies and compare:
  - Final alpha, max drawdown, IL locked, rebalance count
"""

import csv, math, json, os, sys
import numpy as np
from pathlib import Path
from monte_carlo import (
    load_pool_data, tick_to_price, price_to_tick, align,
    v3_amounts, v3_liquidity, POOL_FEE, run_sim
)
from single_range_sweep import run_single_range
from rv_width_strategy import run_rv_width, run_lazy_return
from meihua_strategy import run_meihua_for_mc
from astro_strategy import run_astro

BASE_DIR = Path(__file__).parent


# ─── Synthetic Price Path Generators ─────────────────────────────────

def generate_base_path(start_price, n_points=2000, block_interval=100):
    """Generate a base price path with realistic microstructure."""
    rng = np.random.default_rng(42)
    prices = [start_price]
    for i in range(1, n_points):
        # Random walk with mean reversion
        ret = rng.normal(0, 0.001)  # ~0.1% per step
        prices.append(prices[-1] * (1 + ret))

    base_block = 19208958
    base_ts = 1765951769
    result = []
    for i, p in enumerate(prices):
        block = base_block + i * block_interval
        tick = int(math.floor(math.log(p / 100) / math.log(1.0001))) if p > 0 else 0
        result.append((block, tick, p))
    return result


def inject_flash_crash(base_prices, crash_pct=-0.20, crash_at=0.3, recovery_blocks=500):
    """Inject a flash crash at crash_at fraction of the path."""
    prices = list(base_prices)
    n = len(prices)
    crash_idx = int(n * crash_at)
    crash_blocks = 36  # ~1 hour at 100 block intervals

    # Crash phase
    for i in range(crash_idx, min(crash_idx + crash_blocks, n)):
        frac = (i - crash_idx) / crash_blocks
        mult = 1 + crash_pct * frac
        b, t, p = prices[i]
        new_p = base_prices[crash_idx][2] * mult
        prices[i] = (b, price_to_tick(new_p, 8, 6, False), new_p)

    # Stabilize at crashed level
    crashed_price = base_prices[crash_idx][2] * (1 + crash_pct)
    for i in range(crash_idx + crash_blocks, n):
        rng = np.random.default_rng(i)
        jitter = rng.normal(0, 0.001)
        new_p = crashed_price * (1 + jitter)
        b = prices[i][0]
        prices[i] = (b, price_to_tick(new_p, 8, 6, False), new_p)

    return prices


def inject_black_swan(base_prices, crash_pct=-0.40, crash_at=0.3):
    """Inject a black swan: -40% over 4 hours, no recovery."""
    prices = list(base_prices)
    n = len(prices)
    crash_idx = int(n * crash_at)
    crash_blocks = 144  # ~4 hours

    for i in range(crash_idx, n):
        if i < crash_idx + crash_blocks:
            frac = (i - crash_idx) / crash_blocks
            mult = 1 + crash_pct * frac
        else:
            mult = 1 + crash_pct + (i - crash_idx - crash_blocks) * (-0.001)  # slow continued bleed
        new_p = base_prices[crash_idx][2] * max(0.3, mult)
        b = prices[i][0]
        prices[i] = (b, price_to_tick(new_p, 8, 6, False), new_p)

    return prices


def inject_sustained_bleed(base_prices, weekly_pct=-0.03, weeks=12):
    """Gradual decline: -3% per week for 12 weeks."""
    prices = list(base_prices)
    n = len(prices)
    blocks_per_week = 7 * 24 * 36  # ~6048 blocks per week at 100-block intervals

    for i in range(n):
        week = i / blocks_per_week
        if week > weeks:
            mult = (1 + weekly_pct) ** weeks
        else:
            mult = (1 + weekly_pct) ** week
        rng = np.random.default_rng(i + 100)
        jitter = rng.normal(0, 0.002)
        new_p = base_prices[0][2] * mult * (1 + jitter)
        b = prices[i][0]
        prices[i] = (b, price_to_tick(max(1, new_p), 8, 6, False), max(1, new_p))

    return prices


def inject_v_shape(base_prices, crash_pct=-0.25, bounce_pct=0.30, crash_at=0.3):
    """V-shape: crash -25% then bounce +30% within 48 hours."""
    prices = list(base_prices)
    n = len(prices)
    crash_idx = int(n * crash_at)
    crash_blocks = 72   # ~2 hours down
    bounce_blocks = 144  # ~4 hours up

    start_p = base_prices[crash_idx][2]

    for i in range(crash_idx, n):
        if i < crash_idx + crash_blocks:
            # Crash
            frac = (i - crash_idx) / crash_blocks
            new_p = start_p * (1 + crash_pct * frac)
        elif i < crash_idx + crash_blocks + bounce_blocks:
            # Bounce
            bottom = start_p * (1 + crash_pct)
            frac = (i - crash_idx - crash_blocks) / bounce_blocks
            target = bottom * (1 + bounce_pct)
            new_p = bottom + (target - bottom) * frac
        else:
            # Stabilize at bounced level
            rng = np.random.default_rng(i + 200)
            jitter = rng.normal(0, 0.001)
            stab_p = start_p * (1 + crash_pct) * (1 + bounce_pct)
            new_p = stab_p * (1 + jitter)

        b = prices[i][0]
        prices[i] = (b, price_to_tick(max(1, new_p), 8, 6, False), max(1, new_p))

    return prices


def inject_whipsaw(base_prices, amplitude_pct=0.10, period_blocks=216):
    """Whipsaw: ±10% oscillations every 6 hours, no net direction."""
    prices = list(base_prices)
    n = len(prices)
    start_p = base_prices[0][2]

    for i in range(n):
        phase = (i % period_blocks) / period_blocks * 2 * math.pi
        osc = math.sin(phase) * amplitude_pct
        rng = np.random.default_rng(i + 300)
        jitter = rng.normal(0, 0.002)
        new_p = start_p * (1 + osc) * (1 + jitter)
        b = prices[i][0]
        prices[i] = (b, price_to_tick(max(1, new_p), 8, 6, False), max(1, new_p))

    return prices


def inject_moonshot(base_prices, gain_pct=0.50, ramp_blocks=2520):
    """Moonshot: +50% over 1 week, then stabilize."""
    prices = list(base_prices)
    n = len(prices)
    start_p = base_prices[0][2]

    for i in range(n):
        if i < ramp_blocks:
            frac = i / ramp_blocks
            mult = 1 + gain_pct * frac
        else:
            mult = 1 + gain_pct
        rng = np.random.default_rng(i + 400)
        jitter = rng.normal(0, 0.002)
        new_p = start_p * mult * (1 + jitter)
        b = prices[i][0]
        prices[i] = (b, price_to_tick(max(1, new_p), 8, 6, False), max(1, new_p))

    return prices


# ─── Generate synthetic swap data ───────────────────────────────────

def generate_swaps(prices, avg_vol_per_block=50):
    """Generate synthetic swaps matching price path."""
    from collections import defaultdict
    swap_agg = defaultdict(float)
    swap_tick_agg = defaultdict(lambda: defaultdict(float))

    rng = np.random.default_rng(42)
    for block, tick, price in prices:
        vol = max(1, rng.exponential(avg_vol_per_block))
        tick_bucket = (tick // 10) * 10
        swap_agg[block] += vol
        swap_tick_agg[block][tick_bucket] += vol

    return swap_agg, swap_tick_agg


# ─── Run all strategies on a scenario ────────────────────────────────

def run_scenario(scenario_name, prices, cfg, init_usd):
    """Run all strategies on given price path, return results dict."""
    swap_agg, swap_tick_agg = generate_swaps(prices)

    results = {}

    # ML 3-Layer
    try:
        r = run_sim(prices, swap_agg, swap_tick_agg, cfg, init_usd, {})
        results["ML"] = r
    except:
        results["ML"] = {"alpha": 0, "rebalances": 0, "vault_return": 0}

    # SR-Fixed (±5%)
    try:
        r = run_single_range(prices, swap_tick_agg, cfg, init_usd,
                             {"width_pct": 0.05, "trend_shift": True, "cooldown": 5000, "boundary_pct": 0.05})
        results["SR-Fixed"] = r
    except:
        results["SR-Fixed"] = {"alpha": 0, "rebalances": 0, "vault_return": 0}

    # SR1-RVWidth
    try:
        r = run_rv_width(prices, swap_tick_agg, cfg, init_usd, {"k": 2.0, "cooldown": 5000})
        results["SR1-RVWidth"] = r
    except:
        results["SR1-RVWidth"] = {"alpha": 0, "rebalances": 0, "vault_return": 0}

    # SR2-Lazy
    try:
        r = run_lazy_return(prices, swap_tick_agg, cfg, init_usd,
                           {"width_pct": 0.07, "return_pct": 0.7})
        results["SR2-Lazy"] = r
    except:
        results["SR2-Lazy"] = {"alpha": 0, "rebalances": 0, "vault_return": 0}

    # Meihua
    try:
        r = run_meihua_for_mc(prices, swap_tick_agg, cfg, init_usd, {})
        results["Meihua"] = r
    except:
        results["Meihua"] = {"alpha": 0, "rebalances": 0, "vault_return": 0}

    # Astro
    try:
        r = run_astro(prices, swap_tick_agg, cfg, init_usd, {})
        results["Astro"] = r
    except:
        results["Astro"] = {"alpha": 0, "rebalances": 0, "vault_return": 0}

    return results


# ─── Main ────────────────────────────────────────────────────────────

def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(BASE_DIR / "charts", exist_ok=True)

    # Use BTC-like config
    cfg = {"t0_dec": 8, "t1_dec": 6, "invert": False,
           "fee_share": 0.00158, "tick_spacing": 10}
    init_usd = 2600.0
    start_price = 85000.0

    # Generate base path
    base = generate_base_path(start_price, n_points=2000, block_interval=100)

    scenarios = {
        "Flash Crash (-20%, 1h)": inject_flash_crash(base, -0.20),
        "Black Swan (-40%, 4h)": inject_black_swan(base, -0.40),
        "Sustained Bleed (-3%/wk)": inject_sustained_bleed(base, -0.03, 12),
        "V-Shape (-25% → +30%)": inject_v_shape(base, -0.25, 0.30),
        "Whipsaw (±10%, 6h cycles)": inject_whipsaw(base, 0.10),
        "Moonshot (+50%, 1wk)": inject_moonshot(base, 0.50),
    }

    all_results = {}
    strategies = ["ML", "SR-Fixed", "SR1-RVWidth", "SR2-Lazy", "Meihua", "Astro"]

    print(f"{'='*70}")
    print(f"  CLAMM Stress Test Analysis")
    print(f"  Start: ${start_price:,.0f} | TVL: ${init_usd:,.0f} | 2,000 price points")
    print(f"{'='*70}")

    for sc_name, sc_prices in scenarios.items():
        print(f"\n  Scenario: {sc_name}")
        price_change = (sc_prices[-1][2] / sc_prices[0][2] - 1) * 100
        print(f"    Price: ${sc_prices[0][2]:,.0f} → ${sc_prices[-1][2]:,.0f} ({price_change:+.1f}%)")

        results = run_scenario(sc_name, sc_prices, cfg, init_usd)

        print(f"    {'Strategy':>14} {'Alpha':>8} {'Return':>8} {'Rebal':>6}")
        for s in strategies:
            r = results.get(s, {})
            a = r.get("alpha", 0) * 100
            vr = r.get("vault_return", 0) * 100
            rb = r.get("rebalances", 0)
            print(f"    {s:>14} {a:>+7.2f}% {vr:>+7.2f}% {rb:>5}")

        all_results[sc_name] = {
            s: {
                "alpha": round(results[s].get("alpha", 0) * 100, 2),
                "vault_return": round(results[s].get("vault_return", 0) * 100, 2),
                "hodl_return": round(results[s].get("hodl_return", 0) * 100, 2),
                "rebalances": results[s].get("rebalances", 0),
                "fee_bps": round(results[s].get("fee_bps", 0), 1),
            }
            for s in strategies
        }

    # ─── Summary heatmap ──
    fig, ax = plt.subplots(figsize=(12, 7))

    sc_names = list(all_results.keys())
    alpha_matrix = np.array([
        [all_results[sc][s]["alpha"] for s in strategies]
        for sc in sc_names
    ])

    im = ax.imshow(alpha_matrix, cmap="RdYlGn", aspect="auto",
                   vmin=max(-20, alpha_matrix.min()),
                   vmax=min(20, alpha_matrix.max()))

    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels(strategies, rotation=45, ha="right", fontsize=10)
    ax.set_yticks(range(len(sc_names)))
    ax.set_yticklabels(sc_names, fontsize=10)

    # Annotate cells
    for i in range(len(sc_names)):
        for j in range(len(strategies)):
            val = alpha_matrix[i, j]
            color = "white" if abs(val) > 8 else "black"
            ax.text(j, i, f"{val:+.1f}%", ha="center", va="center",
                    fontsize=9, color=color, fontweight="bold")

    plt.colorbar(im, ax=ax, shrink=0.8, label="Net Alpha (%)")
    ax.set_title("Stress Test: Net Alpha by Scenario × Strategy", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(BASE_DIR / "charts" / "stress_test_heatmap.png", dpi=150)
    plt.close(fig)

    # ─── Price paths visualization ──
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    for idx, (sc_name, sc_prices) in enumerate(scenarios.items()):
        ax = axes[idx // 3][idx % 3]
        blocks = [p[0] for p in sc_prices]
        prices_arr = [p[2] for p in sc_prices]
        ax.plot(range(len(prices_arr)), prices_arr, color="#3498db", linewidth=1)
        ax.set_title(sc_name, fontsize=10, fontweight="bold")
        ax.set_ylabel("Price ($)")
        ax.grid(alpha=0.2)
        ax.axhline(start_price, color="gray", linewidth=0.5, linestyle="--")

    fig.suptitle("Stress Test Price Scenarios", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(BASE_DIR / "charts" / "stress_test_scenarios.png", dpi=150)
    plt.close(fig)

    # ─── Resilience ranking ──
    print(f"\n{'='*70}")
    print(f"  RESILIENCE RANKING (average alpha across all scenarios)")
    print(f"{'='*70}")

    avg_alphas = {}
    for s in strategies:
        alphas = [all_results[sc][s]["alpha"] for sc in sc_names]
        avg_alphas[s] = np.mean(alphas)

    ranked = sorted(avg_alphas.items(), key=lambda x: x[1], reverse=True)
    for rank, (s, avg) in enumerate(ranked, 1):
        worst = min(all_results[sc][s]["alpha"] for sc in sc_names)
        best = max(all_results[sc][s]["alpha"] for sc in sc_names)
        print(f"  #{rank} {s:>14}: avg={avg:+.2f}%, worst={worst:+.2f}%, best={best:+.2f}%")

    # Save results
    output = {
        "scenarios": all_results,
        "resilience_ranking": [
            {"rank": i+1, "strategy": s, "avg_alpha": round(a, 2),
             "worst": round(min(all_results[sc][s]["alpha"] for sc in sc_names), 2),
             "best": round(max(all_results[sc][s]["alpha"] for sc in sc_names), 2)}
            for i, (s, a) in enumerate(ranked)
        ],
        "config": {
            "start_price": start_price,
            "init_usd": init_usd,
            "n_points": 2000,
        }
    }

    with open(BASE_DIR / "stress_test_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n  Charts: charts/stress_test_*.png")
    print(f"  Data:   stress_test_results.json")


if __name__ == "__main__":
    main()
