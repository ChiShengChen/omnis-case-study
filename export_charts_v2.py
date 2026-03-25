#!/usr/bin/env python3
"""
額外圖表：Rebalance 時機、Position 寬度、In-Range 比例
=====================================================
"""
import csv, math, json
from pathlib import Path
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

DATA_DIR_BTC = Path(__file__).parent / "data"
DATA_DIR_ETH = Path(__file__).parent / "data_eth"
OUT_DIR = Path(__file__).parent / "charts"
OUT_DIR.mkdir(exist_ok=True)

plt.rcParams.update({
    "figure.facecolor": "#1a1a2e",
    "axes.facecolor": "#16213e",
    "axes.edgecolor": "#334155",
    "axes.labelcolor": "#e2e8f0",
    "text.color": "#e2e8f0",
    "xtick.color": "#94a3b8",
    "ytick.color": "#94a3b8",
    "grid.color": "#334155",
    "grid.alpha": 0.5,
    "legend.facecolor": "#1e293b",
    "legend.edgecolor": "#334155",
    "font.size": 11,
    "axes.titlesize": 14,
    "figure.dpi": 150,
})

OMNIS_BTC = "0x5977767ef6324864f170318681eccb82315f8761"
OMNIS_ETH = "0x811b8c618716ca62b092b67c09e55361ae6df429"
CHARM_BTC = "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff"


def load_prices(data_dir):
    pts = []
    with open(data_dir / "price_series.csv") as f:
        for row in csv.DictReader(f):
            pts.append((int(row["block"]), float(row["price"])))
    pts.sort()
    return pts


def load_rebalances(data_dir, vault_addr):
    vault = vault_addr.lower()
    tx_mints = {}
    with open(data_dir / "mints.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == vault:
                tx_mints.setdefault(row["tx_hash"], []).append(row)
    tx_burns = {}
    with open(data_dir / "burns.csv") as f:
        for row in csv.DictReader(f):
            if row["owner"] == vault:
                tx_burns.setdefault(row["tx_hash"], []).append(row)

    rbs = []
    for tx in sorted(set(tx_burns) & set(tx_mints), key=lambda t: int(tx_mints[t][0]["block"])):
        mints = sorted(tx_mints[tx], key=lambda m: int(m["tickLower"]))
        block = int(mints[0]["block"])
        positions = []
        for m in mints:
            positions.append((int(m["tickLower"]), int(m["tickUpper"])))
        rbs.append({"block": block, "positions": positions})
    return rbs


def t2p_btc(tick):
    return (1.0001 ** tick) * (10 ** (8-6))

def t2p_eth(tick):
    raw = (1.0001 ** tick) * (10 ** (6-18))
    return 1.0 / raw if raw > 0 else 0


def block_to_date(block, start_block, start_ts=1765951769):
    ts = start_ts + (block - start_block)
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def simulate_ml_rebalances(prices, t2p_fn, is_eth=False):
    """Simulate ML strategy rebalance timing and positions"""
    rbs = []
    last_rb_block = 0
    narrow_lo = narrow_hi = 0

    price_history = []
    for block, price in prices:
        price_history.append(price)

        should_rb = False
        if not rbs:
            should_rb = True
        elif block - last_rb_block >= 5000:
            if narrow_lo > 0 and narrow_hi > 0:
                pa, pb = min(narrow_lo, narrow_hi), max(narrow_lo, narrow_hi)
                if price < pa or price > pb:
                    should_rb = True
                elif pb > pa:
                    pct = (price - pa) / (pb - pa)
                    if pct < 0.1 or pct > 0.9:
                        should_rb = True

        if should_rb:
            # Compute ranges
            trend = 0
            if len(price_history) >= 20:
                r = (price_history[-1] - price_history[-20]) / price_history[-20]
                trend = max(-1, min(1, r / 0.2))

            wide_half = price * 0.1785
            nh = price * 0.039
            if trend < -0.2:
                n_lo, n_hi = price - nh*1.4, price + nh*0.6
            elif trend > 0.2:
                n_lo, n_hi = price - nh*0.6, price + nh*1.4
            else:
                n_lo, n_hi = price - nh, price + nh

            narrow_lo, narrow_hi = n_lo, n_hi
            last_rb_block = block

            rbs.append({
                "block": block,
                "price": price,
                "wide_lo": price - wide_half,
                "wide_hi": price + wide_half,
                "narrow_lo": n_lo,
                "narrow_hi": n_hi,
                "trend": trend,
            })

    return rbs


# ─── Chart 7: Rebalance Timing ──────────────────────────────────────

def chart_rebalance_timing(pool_name, prices, omnis_rbs, ml_rbs, charm_rbs, start_block):
    fig, ax = plt.subplots(figsize=(16, 8))

    # Price line
    blocks = [b for b, _ in prices]
    price_vals = [p for _, p in prices]
    dates = [block_to_date(b, start_block) for b in blocks]
    ax.plot(dates, price_vals, color="#64748b", linewidth=1, alpha=0.8, label="Price")

    # Omnis rebalances (red dots)
    omnis_dates = [block_to_date(r["block"], start_block) for r in omnis_rbs]
    omnis_prices = []
    for r in omnis_rbs:
        idx = min(range(len(blocks)), key=lambda i: abs(blocks[i] - r["block"]))
        omnis_prices.append(price_vals[idx])
    ax.scatter(omnis_dates, omnis_prices, color="#F7931A", s=3, alpha=0.3, zorder=3, label=f"Omnis ({len(omnis_rbs)} rebal)")

    # ML rebalances (green dots)
    ml_dates = [block_to_date(r["block"], start_block) for r in ml_rbs]
    ml_prices = [r["price"] for r in ml_rbs]
    ax.scatter(ml_dates, ml_prices, color="#22C55E", s=60, zorder=5, edgecolors="white",
               linewidth=1, label=f"Multi-Layer ({len(ml_rbs)} rebal)")

    # Charm rebalances (blue dots) if available
    if charm_rbs:
        charm_dates = [block_to_date(r["block"], start_block) for r in charm_rbs]
        charm_prices = []
        for r in charm_rbs:
            idx = min(range(len(blocks)), key=lambda i: abs(blocks[i] - r["block"]))
            charm_prices.append(price_vals[idx])
        ax.scatter(charm_dates, charm_prices, color="#00A3FF", s=30, zorder=4, marker="D",
                   alpha=0.7, label=f"Charm ({len(charm_rbs)} rebal)")

    ax.set_title(f"{pool_name} — Rebalance Timing on Price Chart", fontsize=16, fontweight="bold")
    ax.set_ylabel("Price (USDC)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f"${x:,.0f}"))
    fig.autofmt_xdate()
    fig.tight_layout()

    fname = f"07_rebalance_timing_{pool_name.lower().replace('-','_')}.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


# ─── Chart 8: Position Width Over Time ──────────────────────────────

def chart_position_width(pool_name, prices, ml_rbs, start_block):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[1, 1], sharex=True)

    blocks = [b for b, _ in prices]
    price_vals = [p for _, p in prices]
    dates = [block_to_date(b, start_block) for b in blocks]

    # Top: price with ML narrow range shaded
    ax1.plot(dates, price_vals, color="#e2e8f0", linewidth=1.5, label="Price")

    for i, rb in enumerate(ml_rbs):
        rb_date = block_to_date(rb["block"], start_block)
        next_date = block_to_date(ml_rbs[i+1]["block"], start_block) if i+1 < len(ml_rbs) else dates[-1]

        # Narrow band
        ax1.fill_between([rb_date, next_date], rb["narrow_lo"], rb["narrow_hi"],
                         color="#22C55E", alpha=0.25)
        # Wide band
        ax1.fill_between([rb_date, next_date], rb["wide_lo"], rb["wide_hi"],
                         color="#22C55E", alpha=0.08)

    ax1.set_title(f"{pool_name} — Multi-Layer Position Ranges Over Time", fontsize=16, fontweight="bold")
    ax1.set_ylabel("Price (USDC)")
    ax1.legend(["Price", "Narrow ±3.9%", "Wide ±17.85%"], loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f"${x:,.0f}"))

    # Bottom: trend direction
    trend_dates = [block_to_date(rb["block"], start_block) for rb in ml_rbs]
    trend_vals = [rb["trend"] for rb in ml_rbs]

    colors = ["#ef4444" if t < -0.2 else "#22C55E" if t > 0.2 else "#64748b" for t in trend_vals]
    ax2.bar(trend_dates, trend_vals, width=2, color=colors, alpha=0.7)
    ax2.axhline(y=0.2, color="#22C55E", linewidth=0.8, linestyle="--", alpha=0.5)
    ax2.axhline(y=-0.2, color="#ef4444", linewidth=0.8, linestyle="--", alpha=0.5)
    ax2.axhline(y=0, color="#64748b", linewidth=0.5)
    ax2.set_ylabel("Trend Signal")
    ax2.set_ylim(-1.1, 1.1)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

    fig.autofmt_xdate()
    fig.tight_layout()

    fname = f"08_position_width_{pool_name.lower().replace('-','_')}.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


# ─── Chart 9: In-Range Percentage ───────────────────────────────────

def compute_in_range_pct(prices, rebalances, t2p_fn, is_multi=False):
    """Compute rolling in-range % over time"""
    # Build position timeline
    rb_idx = 0
    current_lo = current_hi = 0
    in_range_count = 0
    total_count = 0
    rolling_pct = []

    for block, price in prices:
        # Update position from rebalances
        while rb_idx < len(rebalances) and rebalances[rb_idx]["block"] <= block:
            rb = rebalances[rb_idx]
            if is_multi:
                current_lo = rb.get("narrow_lo", 0)
                current_hi = rb.get("narrow_hi", 0)
            else:
                tl, tu = rb["positions"][0]
                p1, p2 = t2p_fn(tl), t2p_fn(tu)
                current_lo, current_hi = min(p1, p2), max(p1, p2)
            rb_idx += 1

        total_count += 1
        if current_lo > 0 and current_hi > current_lo:
            if current_lo <= price <= current_hi:
                in_range_count += 1

        pct = in_range_count / total_count * 100 if total_count > 0 else 0
        rolling_pct.append(pct)

    return rolling_pct


def chart_in_range(pool_name, prices, omnis_rbs, ml_rbs, charm_rbs, t2p_fn, start_block):
    fig, ax = plt.subplots(figsize=(14, 7))

    blocks = [b for b, _ in prices]
    dates = [block_to_date(b, start_block) for b in blocks]

    # Omnis
    omnis_pct = compute_in_range_pct(prices, omnis_rbs, t2p_fn, is_multi=False)
    ax.plot(dates, omnis_pct, color="#F7931A", linewidth=2, label="Omnis")

    # ML
    ml_pct = compute_in_range_pct(prices, ml_rbs, t2p_fn, is_multi=True)
    ax.plot(dates, ml_pct, color="#22C55E", linewidth=2, label="Multi-Layer")

    # Charm
    if charm_rbs:
        # Charm has 3 positions per rebalance; use the narrow one (index 2)
        charm_narrow_rbs = []
        for rb in charm_rbs:
            if len(rb["positions"]) >= 3:
                tl, tu = rb["positions"][2]  # narrow
                p1, p2 = t2p_fn(tl), t2p_fn(tu)
                charm_narrow_rbs.append({
                    "block": rb["block"],
                    "narrow_lo": min(p1, p2),
                    "narrow_hi": max(p1, p2),
                })
        if charm_narrow_rbs:
            charm_pct = compute_in_range_pct(prices, charm_narrow_rbs, t2p_fn, is_multi=True)
            ax.plot(dates, charm_pct, color="#00A3FF", linewidth=2, label="Charm (narrow)")

    # Final values annotation
    for label, pct_arr, color in [("Omnis", omnis_pct, "#F7931A"),
                                    ("ML", ml_pct, "#22C55E")]:
        final = pct_arr[-1] if pct_arr else 0
        ax.annotate(f"{label}: {final:.1f}%", xy=(dates[-1], final),
                    xytext=(10, 0), textcoords="offset points",
                    color=color, fontsize=10, fontweight="bold")

    ax.set_title(f"{pool_name} — Cumulative In-Range Percentage", fontsize=16, fontweight="bold")
    ax.set_ylabel("In-Range (%)")
    ax.set_ylim(0, 105)
    ax.legend(loc="lower left", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()
    fig.tight_layout()

    fname = f"09_in_range_{pool_name.lower().replace('-','_')}.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


# ─── Main ───────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Exporting Additional Charts")
    print("=" * 60)

    # WBTC-USDC
    print("\n📊 WBTC-USDC")
    prices_btc = load_prices(DATA_DIR_BTC)
    omnis_btc_rbs = load_rebalances(DATA_DIR_BTC, OMNIS_BTC)
    charm_btc_rbs = load_rebalances(DATA_DIR_BTC, CHARM_BTC)
    ml_btc_rbs = simulate_ml_rebalances(prices_btc, t2p_btc)
    start_btc = prices_btc[0][0]

    chart_rebalance_timing("WBTC-USDC", prices_btc, omnis_btc_rbs, ml_btc_rbs, charm_btc_rbs, start_btc)
    chart_position_width("WBTC-USDC", prices_btc, ml_btc_rbs, start_btc)
    chart_in_range("WBTC-USDC", prices_btc, omnis_btc_rbs, ml_btc_rbs, charm_btc_rbs, t2p_btc, start_btc)

    # USDC-ETH
    if DATA_DIR_ETH.exists() and (DATA_DIR_ETH / "price_series.csv").exists():
        print("\n📊 USDC-ETH")
        prices_eth = load_prices(DATA_DIR_ETH)
        omnis_eth_rbs = load_rebalances(DATA_DIR_ETH, OMNIS_ETH)
        ml_eth_rbs = simulate_ml_rebalances(prices_eth, t2p_eth, is_eth=True)
        start_eth = prices_eth[0][0]

        chart_rebalance_timing("USDC-ETH", prices_eth, omnis_eth_rbs, ml_eth_rbs, [], start_eth)
        chart_position_width("USDC-ETH", prices_eth, ml_eth_rbs, start_eth)
        chart_in_range("USDC-ETH", prices_eth, omnis_eth_rbs, ml_eth_rbs, [], t2p_eth, start_eth)

    print(f"\n✅ All charts in {OUT_DIR}")
    for f in sorted(OUT_DIR.glob("0[789]*.png")):
        print(f"   {f.name} ({f.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
