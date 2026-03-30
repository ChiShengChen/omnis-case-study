#!/usr/bin/env python3
"""Compute 5 CLAMM-specific metrics from intervals.json + metadata.json."""

import json, math, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "data"

with open(ROOT / "intervals.json") as f:
    intervals = json.load(f)

with open(ROOT / "metadata.json") as f:
    metadata = json.load(f)

# Build a lookup: vault_id -> rebalance_count, total_days
meta_lookup = {}
for v in metadata["vaults"]:
    meta_lookup[v["id"]] = v

results = {}

for vault_id, series in intervals.items():
    meta = meta_lookup.get(vault_id)
    if not meta:
        continue

    net_alpha = series["net_alpha"]
    realized_fee = series["realized_fee_return"]
    residual_drag = series["residual_drag"]
    n_days = meta["total_days"]
    n_rebalances = meta["rebalance_count"]

    # --- a) Fee/IL Ratio ---
    total_fee = realized_fee[-1]              # cumulative fee as fraction of NAV
    total_il = abs(residual_drag[-1])         # IL+drag (residual_drag is negative)
    if total_fee == 0 and total_il == 0:
        fee_il_ratio = 0.0
    elif total_il == 0:
        fee_il_ratio = float("inf")
    else:
        fee_il_ratio = total_fee / total_il

    # --- b) Max Drawdown (on net_alpha) ---
    running_max = -float("inf")
    max_dd = 0.0
    for a in net_alpha:
        if a > running_max:
            running_max = a
        dd = running_max - a
        if dd > max_dd:
            max_dd = dd

    # --- c) Sharpe Ratio (annualised, from daily alpha diffs) ---
    # Compute daily diffs of net_alpha
    diffs = [net_alpha[i] - net_alpha[i - 1] for i in range(1, len(net_alpha))]
    if len(diffs) > 1:
        mean_d = sum(diffs) / len(diffs)
        var_d = sum((x - mean_d) ** 2 for x in diffs) / (len(diffs) - 1)
        std_d = math.sqrt(var_d)
        if std_d > 0:
            sharpe = (mean_d / std_d) * math.sqrt(365)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # --- d) Capital Efficiency (bps / day) ---
    if n_days > 0:
        cap_efficiency = (realized_fee[-1] / n_days) * 10000  # bps per day
    else:
        cap_efficiency = 0.0

    # --- e) IL per Rebalance (bps) ---
    total_il_bps = abs(residual_drag[-1]) * 10000
    if n_rebalances > 0:
        il_per_rb = total_il_bps / n_rebalances
    else:
        il_per_rb = 0.0

    results[vault_id] = {
        "fee_il_ratio": fee_il_ratio if not math.isinf(fee_il_ratio) else "Infinity",
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "cap_efficiency_bps_day": round(cap_efficiency, 2),
        "il_per_rebalance_bps": round(il_per_rb, 1),
    }

out_path = ROOT / "clamm-metrics.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)

print(f"Wrote {len(results)} vaults to {out_path}")
for vid, m in results.items():
    print(f"  {vid}: {m}")
