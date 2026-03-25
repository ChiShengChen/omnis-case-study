#!/usr/bin/env python3
"""
Compute performance metrics for 3 competitor vaults, matching the methodology
used for Omnis vaults in computed-metrics.json. Outputs competitor metrics JSON.
"""

import csv, json, os, sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATADIR = os.path.join(BASE, "data")

VAULTS = [
    {
        "name": "steer-competitor-usdc-eth",
        "pair_type": "usdc-eth",
        "d0": 6,
        "d1": 18,
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "t0_label": "USDC",
        "t1_label": "ETH",
    },
    {
        "name": "charm-usdc-eth",
        "pair_type": "usdc-eth",
        "d0": 6,
        "d1": 18,
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "t0_label": "USDC",
        "t1_label": "ETH",
    },
    {
        "name": "charm-wbtc-usdc",
        "pair_type": "wbtc-usdc",
        "d0": 8,
        "d1": 6,
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "t0_label": "WBTC",
        "t1_label": "USDC",
    },
]

OMNIS_VAULT_INCEPTIONS = {
    "usdc-eth": 23693484,
    "wbtc-usdc": 19208958,
}


def load_dense_csv(name):
    rows = []
    fname = os.path.join(DATADIR, f"competitor-{name}-dense.csv")
    with open(fname) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "block": int(row["block"]),
                    "timestamp": int(row["timestamp"]),
                    "amount0": float(row["amount0"]),
                    "amount1": float(row["amount1"]),
                    "total_supply": int(row["total_supply"]),
                    "price": float(row["price"]) if row["price"] else 0,
                    "tick": int(row["tick"]) if row["tick"] else 0,
                }
            )
    return rows


def tvl_usd(amt0, amt1, price, pair_type):
    if pair_type == "usdc-eth":
        eth_price_usdc = 1.0 / price if price > 0 else 0
        return amt0 + amt1 * eth_price_usdc
    elif pair_type == "wbtc-usdc":
        return amt0 * price + amt1


def underlying_price_usd(price, pair_type):
    if pair_type == "usdc-eth":
        return 1.0 / price if price > 0 else 0
    elif pair_type == "wbtc-usdc":
        return price


def share_price(row, pair_type):
    tvl = tvl_usd(row["amount0"], row["amount1"], row["price"], pair_type)
    if row["total_supply"] > 0:
        return tvl / row["total_supply"]
    return 0


def hodl_return(first, last, pair_type):
    """HODL = hold initial token composition at current prices."""
    initial_tvl = tvl_usd(first["amount0"], first["amount1"], first["price"], pair_type)
    hodl_tvl = tvl_usd(first["amount0"], first["amount1"], last["price"], pair_type)
    if initial_tvl > 0:
        return (hodl_tvl / initial_tvl) - 1
    return 0


def max_drawdown(rows, pair_type):
    peak = 0
    mdd = 0
    for row in rows:
        sp = share_price(row, pair_type)
        if sp > peak:
            peak = sp
        if peak > 0:
            dd = (sp - peak) / peak
            if dd < mdd:
                mdd = dd
    return mdd


def load_real_fees(vault_name):
    fees = {"fee0": 0, "fee1": 0, "tx_count": 0}
    fname = os.path.join(DATADIR, "competitor-real-fees.csv")
    with open(fname) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["vault"] == vault_name:
                fees["fee0"] += float(row["fee0"])
                fees["fee1"] += float(row["fee1"])
                fees["tx_count"] += 1
    return fees


def count_rebalances(vault_name):
    count = 0
    fname = os.path.join(DATADIR, "competitor-fees.csv")
    with open(fname) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["vault"] == vault_name and row["event_type"] == "Burn":
                count += 1
    return count


def load_pool_swap_volume(pool_name, from_block, to_block):
    total_swaps = 0
    total_vol0 = 0
    total_vol1 = 0

    for fname in ["swaps-extended.csv", "swaps-summary.csv"]:
        fpath = os.path.join(DATADIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            reader = csv.DictReader(f)
            name_col = "pool" if "pool" in reader.fieldnames else "vault"
            for row in reader:
                rname = row.get(name_col, "")
                if rname != pool_name:
                    continue
                bs = int(row["block_start"])
                be = int(row["block_end"])
                if bs >= from_block and be <= to_block:
                    total_swaps += int(row["num_swaps"])
                    total_vol0 += float(row["vol_token0"])
                    total_vol1 += float(row["vol_token1"])

    return total_swaps, total_vol0, total_vol1


def compute(v):
    name = v["name"]
    pair_type = v["pair_type"]
    print(f"\n═══ {name} ═══", file=sys.stderr)

    rows = load_dense_csv(name)
    if len(rows) < 2:
        print(f"  ⚠ Not enough data points", file=sys.stderr)
        return None

    first, last = rows[0], rows[-1]
    inception_block = first["block"]
    current_block = last["block"]

    days_active = (
        (last["timestamp"] - first["timestamp"]) / 86400
        if last["timestamp"] > 0 and first["timestamp"] > 0
        else 0
    )

    sp_first = share_price(first, pair_type)
    sp_last = share_price(last, pair_type)
    vault_return = (sp_last / sp_first) - 1 if sp_first > 0 else 0

    hodl_ret = hodl_return(first, last, pair_type)
    alpha = vault_return - hodl_ret

    mdd = max_drawdown(rows, pair_type)

    asset_price_inception = underlying_price_usd(first["price"], pair_type)
    asset_price_current = underlying_price_usd(last["price"], pair_type)
    asset_price_change = (
        (asset_price_current / asset_price_inception) - 1
        if asset_price_inception > 0
        else 0
    )

    tvl_inception = tvl_usd(
        first["amount0"], first["amount1"], first["price"], pair_type
    )
    tvl_current = tvl_usd(last["amount0"], last["amount1"], last["price"], pair_type)

    fees = load_real_fees(name)
    rebalance_count = count_rebalances(name)

    if pair_type == "usdc-eth":
        real_fee_usd = fees["fee0"] + fees["fee1"] * asset_price_current
        pool_name = "USDC-ETH"
    else:
        real_fee_usd = fees["fee0"] * asset_price_current + fees["fee1"]
        pool_name = "WBTC-USDC"

    total_swaps, vol0, vol1 = load_pool_swap_volume(
        pool_name, inception_block, current_block
    )
    if pair_type == "usdc-eth":
        pool_total_volume_usdc = vol0
    else:
        pool_total_volume_usdc = vol1

    pool_total_fees_usd = pool_total_volume_usdc * 0.0005

    avg_tvl = (tvl_inception + tvl_current) / 2

    pool_tvl_map = {"usdc-eth": 5230000, "wbtc-usdc": 2270000}
    pool_tvl = pool_tvl_map.get(pair_type, 1)
    tvl_share = avg_tvl / pool_tvl if pool_tvl > 0 else 0
    fee_capture_pct = (
        real_fee_usd / pool_total_fees_usd if pool_total_fees_usd > 0 else 0
    )
    fee_capture_mult = fee_capture_pct / tvl_share if tvl_share > 0 else 0

    # === Matched-period metrics (from Omnis vault inception) ===
    omnis_inception = OMNIS_VAULT_INCEPTIONS.get(pair_type)
    matched_rows = (
        [r for r in rows if r["block"] >= omnis_inception] if omnis_inception else []
    )
    matched = {}
    if len(matched_rows) >= 2:
        mfirst, mlast = matched_rows[0], matched_rows[-1]
        m_sp_first = share_price(mfirst, pair_type)
        m_sp_last = share_price(mlast, pair_type)
        matched["from_block"] = mfirst["block"]
        matched["vault_return_pct"] = (
            round(((m_sp_last / m_sp_first) - 1) * 100, 2) if m_sp_first > 0 else 0
        )
        matched["hodl_return_pct"] = round(
            hodl_return(mfirst, mlast, pair_type) * 100, 2
        )
        matched["alpha_pct"] = round(
            matched["vault_return_pct"] - matched["hodl_return_pct"], 2
        )
        if mlast["timestamp"] > 0 and mfirst["timestamp"] > 0:
            matched["days"] = round(
                (mlast["timestamp"] - mfirst["timestamp"]) / 86400, 1
            )
        else:
            matched["days"] = round((mlast["block"] - mfirst["block"]) / 86400, 1)

    result = {
        "inception_block": inception_block,
        "current_block": current_block,
        "data_points": len(rows),
        "days_active": round(days_active, 1),
        "asset_price_inception": round(asset_price_inception, 2),
        "asset_price_current": round(asset_price_current, 2),
        "asset_price_change_pct": round(asset_price_change * 100, 2),
        "tvl_inception": round(tvl_inception, 2),
        "tvl_current": round(tvl_current, 2),
        "vault_return_pct": round(vault_return * 100, 2),
        "hodl_return_pct": round(hodl_ret * 100, 2),
        "alpha_raw_pct": round(alpha * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "real_fee_token0": round(fees["fee0"], 8),
        "real_fee_token1": round(fees["fee1"], 8),
        "real_fee_usd": round(real_fee_usd, 2),
        "rebalance_count": rebalance_count,
        "pool_total_swaps": total_swaps,
        "pool_total_volume_usdc": round(pool_total_volume_usdc, 2),
        "pool_total_fees_usd": round(pool_total_fees_usd, 2),
        "fee_capture_pct": round(fee_capture_pct * 100, 4),
        "tvl_share_of_pool_pct": round(tvl_share * 100, 4),
        "fee_capture_multiplier": round(fee_capture_mult, 2),
        "matched_period": matched,
    }

    print(f"  Days: {days_active:.0f}", file=sys.stderr)
    print(f"  TVL: ${tvl_inception:,.0f} → ${tvl_current:,.0f}", file=sys.stderr)
    print(
        f"  Asset: {v['t0_label'] if pair_type == 'wbtc-usdc' else v['t1_label']} {asset_price_change * 100:+.1f}%",
        file=sys.stderr,
    )
    print(f"  Vault return: {vault_return * 100:.2f}%", file=sys.stderr)
    print(f"  HODL return: {hodl_ret * 100:.2f}%", file=sys.stderr)
    print(f"  Alpha: {alpha * 100:.2f}%", file=sys.stderr)
    print(f"  Max DD: {mdd * 100:.2f}%", file=sys.stderr)
    print(f"  Real fee: ${real_fee_usd:,.2f}", file=sys.stderr)
    print(f"  Rebalances: {rebalance_count}", file=sys.stderr)
    print(
        f"  Fee capture: {fee_capture_pct * 100:.4f}% (pool fee ${pool_total_fees_usd:,.0f})",
        file=sys.stderr,
    )
    print(f"  Fee multiplier: {fee_capture_mult:.2f}x", file=sys.stderr)
    if matched:
        print(
            f"  Matched period ({matched['days']:.0f}d): vault {matched['vault_return_pct']:.2f}%, hodl {matched['hodl_return_pct']:.2f}%, alpha {matched['alpha_pct']:.2f}%",
            file=sys.stderr,
        )

    return result


def main():
    results = {}
    for v in VAULTS:
        key = v["name"].replace("-", "_")
        result = compute(v)
        if result:
            results[key] = result

    outpath = os.path.join(DATADIR, "computed-metrics-competitors.json")
    with open(outpath, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✅ Saved to {outpath}", file=sys.stderr)


if __name__ == "__main__":
    main()
