#!/usr/bin/env python3
"""分析 Charm.fi 實際的三層資金分配和策略參數"""
import csv, math, bisect
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

def tick_to_price(tick):
    return (1.0001 ** tick) * (10 ** (8 - 6))

# Load prices
prices = {}
with open(DATA_DIR / "price_series.csv") as f:
    for row in csv.DictReader(f):
        prices[int(row["block"])] = float(row["price"])
price_blocks = sorted(prices.keys())

def get_price(block):
    idx = bisect.bisect_right(price_blocks, block) - 1
    return prices[price_blocks[max(0, idx)]]

# Load Charm rebalances
charm = "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff"
tx_burns, tx_mints = {}, {}
with open(DATA_DIR / "burns.csv") as f:
    for row in csv.DictReader(f):
        if row["owner"] == charm:
            tx_burns.setdefault(row["tx_hash"], []).append(row)
with open(DATA_DIR / "mints.csv") as f:
    for row in csv.DictReader(f):
        if row["owner"] == charm:
            tx_mints.setdefault(row["tx_hash"], []).append(row)

rebalances = []
for tx in sorted(set(tx_burns) & set(tx_mints), key=lambda t: int(tx_mints[t][0]["block"])):
    mints = sorted(tx_mints[tx], key=lambda m: int(m["tickLower"]))
    block = int(mints[0]["block"])
    positions = []
    for m in mints:
        positions.append({
            "tl": int(m["tickLower"]), "tu": int(m["tickUpper"]),
            "a0": int(m["amount0"]), "a1": int(m["amount1"]),
            "liq": int(m["liquidity"]),
        })
    rebalances.append({"block": block, "positions": positions})

print(f"Charm rebalances: {len(rebalances)}")
print()

# Analyze USD allocation per layer
header = f"{'Block':>12}  {'BTC Price':>10}  {'Full-range':>12}  {'Wide':>12}  {'Narrow':>12}  {'FR%':>5}  {'W%':>5}  {'N%':>5}"
print(header)
print("-" * len(header))

all_ratios = []
all_totals = []
all_wide_widths = []
all_narrow_widths = []
intervals = []

for i, rb in enumerate(rebalances):
    btc_price = get_price(rb["block"])
    vals = []
    for p in rb["positions"]:
        usd = (p["a0"] / 1e8) * btc_price + (p["a1"] / 1e6)
        vals.append(usd)

    total = sum(vals)
    all_totals.append(total)
    if total > 0:
        pcts = [v / total * 100 for v in vals]
        all_ratios.append(pcts)

    # Wide/narrow widths
    if len(rb["positions"]) == 3:
        p2 = rb["positions"][1]  # wide
        p3 = rb["positions"][2]  # narrow
        pl2, pu2 = tick_to_price(p2["tl"]), tick_to_price(p2["tu"])
        pl3, pu3 = tick_to_price(p3["tl"]), tick_to_price(p3["tu"])
        all_wide_widths.append((pu2 - pl2) / ((pu2 + pl2) / 2) * 100)
        all_narrow_widths.append((pu3 - pl3) / ((pu3 + pl3) / 2) * 100)

    if i > 0:
        intervals.append(rb["block"] - rebalances[i - 1]["block"])

    if i < 15 or i == len(rebalances) - 1:
        if total > 0:
            print(f"{rb['block']:>12}  ${btc_price:>9,.0f}  ${vals[0]:>11,.2f}  ${vals[1]:>11,.2f}  ${vals[2]:>11,.2f}  {pcts[0]:>4.1f}%  {pcts[1]:>4.1f}%  {pcts[2]:>4.1f}%")

arr = np.array(all_ratios)
print()
print("=" * 60)
print("Charm 策略參數統計 (101 rebalances)")
print("=" * 60)
print(f"  資金分配:")
print(f"    Full-range:  {np.mean(arr[:,0]):>5.1f}% ± {np.std(arr[:,0]):.1f}%")
print(f"    Wide:        {np.mean(arr[:,1]):>5.1f}% ± {np.std(arr[:,1]):.1f}%")
print(f"    Narrow:      {np.mean(arr[:,2]):>5.1f}% ± {np.std(arr[:,2]):.1f}%")
print(f"  區間寬度:")
print(f"    Wide:    {np.mean(all_wide_widths):.1f}% (固定)")
print(f"    Narrow:  {np.mean(all_narrow_widths):.1f}% (固定)")
print(f"  Rebalance 間隔:")
print(f"    Mean: {np.mean(intervals):,.0f} blocks ({np.mean(intervals)/3600:.1f} hrs)")
print(f"    Median: {np.median(intervals):,.0f} blocks ({np.median(intervals)/3600:.1f} hrs)")
print(f"    Min: {np.min(intervals):,} blocks")
print(f"    Max: {np.max(intervals):,} blocks")
print(f"  TVL per rebalance: ${np.mean(all_totals):,.0f} (mean)")
