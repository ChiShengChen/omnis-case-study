#!/usr/bin/env python3
"""
從 dashboard JSON 數據匯出靜態圖表
===================================
輸出: case_study/charts/
"""
import json
import math
from pathlib import Path
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

DATA_DIR = Path(__file__).parent / "backtest-dashboard" / "data"
OUT_DIR = Path(__file__).parent / "charts"
OUT_DIR.mkdir(exist_ok=True)

# Style
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

VAULT_COLORS = {
    "omnis-wbtc-usdc": "#F7931A",
    "omnis-usdc-eth": "#627EEA",
    "charm-wbtc-usdc": "#00C2FF",
    "charm-usdc-eth": "#00A3FF",
    "steer-usdc-eth": "#FF6B6B",
    "ml-wbtc-usdc": "#22C55E",
    "ml-usdc-eth": "#10B981",
}

VAULT_LABELS = {
    "omnis-wbtc-usdc": "Omnis",
    "omnis-usdc-eth": "Omnis",
    "charm-wbtc-usdc": "Charm",
    "charm-usdc-eth": "Charm",
    "steer-usdc-eth": "Steer 競品",
    "ml-wbtc-usdc": "Multi-Layer (ours)",
    "ml-usdc-eth": "Multi-Layer (ours)",
}


def load_data():
    intervals = json.loads((DATA_DIR / "intervals.json").read_text())
    metadata = json.loads((DATA_DIR / "metadata.json").read_text())
    windows = json.loads((DATA_DIR / "windows.json").read_text())
    return intervals, metadata, windows


def ts_to_dates(timestamps):
    return [datetime.fromtimestamp(t, tz=timezone.utc) for t in timestamps]


def chart_1_cumulative_returns(intervals, metadata, pool_name):
    """圖1: 累積回報曲線 — vault return vs HODL"""
    fig, ax = plt.subplots(figsize=(14, 7))

    pool_vaults = [v for v in metadata["vaults"] if v["pool"] == pool_name]

    for v in pool_vaults:
        vid = v["id"]
        if vid not in intervals:
            continue
        data = intervals[vid]
        dates = ts_to_dates(data["timestamps"])
        vault_ret = [r * 100 for r in data["vault_return"]]
        hodl_ret = [r * 100 for r in data["hodl_return"]]

        label = VAULT_LABELS.get(vid, vid)
        color = VAULT_COLORS.get(vid, "#888")

        ax.plot(dates, vault_ret, color=color, linewidth=2, label=f"{label} vault")
        ax.plot(dates, hodl_ret, color=color, linewidth=1, linestyle="--", alpha=0.5, label=f"{label} HODL")

    ax.axhline(y=0, color="#64748b", linewidth=0.8, linestyle="-")
    ax.set_title(f"{pool_name} — Cumulative Returns", fontsize=16, fontweight="bold")
    ax.set_ylabel("Return (%)")
    ax.legend(loc="lower left", fontsize=9, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    fig.autofmt_xdate()
    fig.tight_layout()

    fname = f"01_cumulative_returns_{pool_name.lower().replace('-', '_')}.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


def chart_2_alpha_comparison(metadata):
    """圖2: Alpha 比較柱狀圖"""
    fig, ax = plt.subplots(figsize=(12, 6))

    # Group by pool
    pools = {"WBTC-USDC": [], "USDC-ETH": []}
    for v in metadata["vaults"]:
        pools[v["pool"]].append(v)

    labels = []
    alphas = []
    colors = []

    for pool_name in ["WBTC-USDC", "USDC-ETH"]:
        for v in pools[pool_name]:
            vid = v["id"]
            label = f"{VAULT_LABELS.get(vid, vid)}\n{pool_name}"
            labels.append(label)
            alphas.append(v["full_period_alpha"] * 100)
            colors.append(VAULT_COLORS.get(vid, "#888"))

    x = np.arange(len(labels))
    bars = ax.bar(x, alphas, color=colors, width=0.6, edgecolor="#475569", linewidth=0.5)

    # 標數字
    for bar, alpha in zip(bars, alphas):
        y = bar.get_height()
        va = "bottom" if y >= 0 else "top"
        offset = 0.3 if y >= 0 else -0.3
        ax.text(bar.get_x() + bar.get_width()/2, y + offset,
                f"{alpha:+.2f}%", ha="center", va=va, fontsize=9, fontweight="bold")

    ax.axhline(y=0, color="#64748b", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Alpha (%)")
    ax.set_title("Strategy Alpha Comparison (Full Period)", fontsize=16, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()

    fname = "02_alpha_comparison.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


def chart_3_decomposition(intervals, metadata, pool_name):
    """圖3: 回報拆解 — fee income vs IL+drag"""
    fig, ax = plt.subplots(figsize=(14, 7))

    pool_vaults = [v for v in metadata["vaults"] if v["pool"] == pool_name]

    for v in pool_vaults:
        vid = v["id"]
        if vid not in intervals:
            continue
        data = intervals[vid]
        dates = ts_to_dates(data["timestamps"])

        net_alpha = [a * 100 if a is not None else 0 for a in data["net_alpha"]]
        fee_ret = [f * 100 if f is not None else 0 for f in data["realized_fee_return"]]
        drag = [d * 100 if d is not None else 0 for d in data["residual_drag"]]

        label = VAULT_LABELS.get(vid, vid)
        color = VAULT_COLORS.get(vid, "#888")

        ax.plot(dates, net_alpha, color=color, linewidth=2, label=f"{label} net alpha")

    ax.axhline(y=0, color="#64748b", linewidth=0.8)
    ax.set_title(f"{pool_name} — Net Alpha Over Time", fontsize=16, fontweight="bold")
    ax.set_ylabel("Alpha (%)")
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    fig.autofmt_xdate()
    fig.tight_layout()

    fname = f"03_alpha_timeline_{pool_name.lower().replace('-', '_')}.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


def chart_4_rebalance_comparison(metadata):
    """圖4: Rebalance 次數 vs Alpha 散佈圖"""
    fig, ax = plt.subplots(figsize=(10, 7))

    for v in metadata["vaults"]:
        vid = v["id"]
        label = f"{VAULT_LABELS.get(vid, vid)} ({v['pool']})"
        color = VAULT_COLORS.get(vid, "#888")
        alpha = v["full_period_alpha"] * 100
        rb = v["rebalance_count"]

        ax.scatter(rb, alpha, color=color, s=150, zorder=5, edgecolors="white", linewidth=1)
        ax.annotate(label, (rb, alpha), textcoords="offset points",
                    xytext=(8, 5), fontsize=8, color=color)

    ax.axhline(y=0, color="#64748b", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Rebalance Count")
    ax.set_ylabel("Alpha (%)")
    ax.set_title("Rebalance Frequency vs Alpha", fontsize=16, fontweight="bold")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    fname = "04_rebalance_vs_alpha.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


def chart_5_heatmap(windows, vault_id, pool_name):
    """圖5: Entry/Exit Alpha 熱力圖"""
    if vault_id not in windows:
        print(f"  ⚠ {vault_id} not in windows data")
        return

    data = windows[vault_id]
    dates = data["dates"]
    n = len(dates)
    wins = data["windows"]

    # Build matrix
    matrix = np.full((n, n), np.nan)
    for w in wins:
        ei, xi = w["ei"], w["xi"]
        if 0 <= ei < n and 0 <= xi < n:
            matrix[ei][xi] = w["alpha"] * 100

    fig, ax = plt.subplots(figsize=(12, 10))

    # Only show upper triangle (entry < exit)
    mask = np.tril(np.ones_like(matrix, dtype=bool), k=0)
    matrix_masked = np.ma.array(matrix, mask=mask)

    vmin, vmax = -15, 15
    im = ax.imshow(matrix_masked, cmap="RdYlGn", vmin=vmin, vmax=vmax,
                   aspect="auto", origin="upper")

    # Axis labels
    step = max(1, n // 10)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([dates[i][5:] for i in range(0, n, step)], rotation=45, fontsize=8)
    ax.set_yticks(range(0, n, step))
    ax.set_yticklabels([dates[i][5:] for i in range(0, n, step)], fontsize=8)

    ax.set_xlabel("Exit Date")
    ax.set_ylabel("Entry Date")

    label = VAULT_LABELS.get(vault_id, vault_id)
    ax.set_title(f"{label} ({pool_name}) — Entry/Exit Alpha Heatmap", fontsize=14, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Alpha (%)")
    fig.tight_layout()

    fname = f"05_heatmap_{vault_id.replace('-', '_')}.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


def chart_6_summary_table(metadata):
    """圖6: 摘要表格"""
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.axis("off")

    headers = ["Vault", "Pool", "Days", "Rebalances", "Vault Return", "HODL Return", "Alpha"]
    rows = []
    cell_colors = []

    for v in metadata["vaults"]:
        vid = v["id"]
        alpha = v["full_period_alpha"] * 100
        vr = v["full_period_vault_return"] * 100
        hr = v["full_period_hodl_return"] * 100
        rows.append([
            VAULT_LABELS.get(vid, vid),
            v["pool"],
            str(v["total_days"]),
            str(v["rebalance_count"]),
            f"{vr:+.2f}%",
            f"{hr:+.2f}%",
            f"{alpha:+.2f}%",
        ])
        # Color alpha cell
        if alpha > 0:
            row_colors = ["#1e293b"] * 6 + ["#064e3b"]
        else:
            row_colors = ["#1e293b"] * 6 + ["#7f1d1d"]
        cell_colors.append(row_colors)

    table = ax.table(
        cellText=rows, colLabels=headers,
        cellLoc="center", loc="center",
        cellColours=cell_colors,
        colColours=["#334155"] * len(headers),
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.8)

    # Style header
    for key, cell in table.get_celld().items():
        cell.set_edgecolor("#475569")
        if key[0] == 0:
            cell.set_text_props(fontweight="bold", color="#e2e8f0")
        else:
            cell.set_text_props(color="#e2e8f0")

    ax.set_title("Vault Performance Summary", fontsize=16, fontweight="bold",
                 pad=20, color="#e2e8f0")
    fig.tight_layout()

    fname = "06_summary_table.png"
    fig.savefig(OUT_DIR / fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {fname}")


def main():
    print("=" * 60)
    print("Exporting Charts")
    print(f"Output: {OUT_DIR}")
    print("=" * 60)

    intervals, metadata, windows = load_data()

    print("\n📊 Chart 1: Cumulative Returns")
    chart_1_cumulative_returns(intervals, metadata, "WBTC-USDC")
    chart_1_cumulative_returns(intervals, metadata, "USDC-ETH")

    print("\n📊 Chart 2: Alpha Comparison")
    chart_2_alpha_comparison(metadata)

    print("\n📊 Chart 3: Alpha Timeline")
    chart_3_decomposition(intervals, metadata, "WBTC-USDC")
    chart_3_decomposition(intervals, metadata, "USDC-ETH")

    print("\n📊 Chart 4: Rebalance vs Alpha")
    chart_4_rebalance_comparison(metadata)

    print("\n📊 Chart 5: Heatmaps")
    for vid in ["omnis-wbtc-usdc", "ml-wbtc-usdc", "charm-wbtc-usdc",
                "omnis-usdc-eth", "ml-usdc-eth"]:
        v = next((v for v in metadata["vaults"] if v["id"] == vid), None)
        if v:
            chart_5_heatmap(windows, vid, v["pool"])

    print("\n📊 Chart 6: Summary Table")
    chart_6_summary_table(metadata)

    print(f"\n✅ All charts exported to {OUT_DIR}")
    for f in sorted(OUT_DIR.glob("*.png")):
        print(f"   {f.name} ({f.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
