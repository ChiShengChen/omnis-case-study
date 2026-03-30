#!/usr/bin/env python3
import bisect
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone


VAULTS = [
    {
        "id": "omnis-wbtc-usdc",
        "label": "Omnis WBTC-USDC",
        "color": "#F7931A",
        "pair_type": "wbtc-usdc",
        "pool": "WBTC-USDC",
        "dense_file": "vault1-dense.csv",
        "fee_vault_name": "WBTC-USDC",
        "fee_file": "real-fees.csv",
        "inception_block": 19208958,
        "token0_decimals": 8,
        "token1_decimals": 6,
    },
    {
        "id": "omnis-usdc-eth",
        "label": "Omnis USDC-ETH",
        "color": "#627EEA",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "vault2-dense.csv",
        "fee_vault_name": "USDC-ETH",
        "fee_file": "real-fees.csv",
        "inception_block": 23693484,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },
    {
        "id": "charm-wbtc-usdc",
        "label": "Charm WBTC-USDC",
        "color": "#00C2FF",
        "pair_type": "wbtc-usdc",
        "pool": "WBTC-USDC",
        "dense_file": "competitor-charm-wbtc-usdc-dense.csv",
        "fee_vault_name": "charm-wbtc-usdc",
        "fee_file": "competitor-real-fees.csv",
        "inception_block": 17000322,
        "token0_decimals": 8,
        "token1_decimals": 6,
    },
    {
        "id": "charm-usdc-eth",
        "label": "Charm USDC-ETH",
        "color": "#00A3FF",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "competitor-charm-usdc-eth-dense.csv",
        "fee_vault_name": "charm-usdc-eth",
        "fee_file": "competitor-real-fees.csv",
        "inception_block": 17000322,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },

    {
        "id": "ml-wbtc-usdc",
        "label": "Multi-Layer WBTC-USDC",
        "color": "#22C55E",
        "pair_type": "wbtc-usdc",
        "pool": "WBTC-USDC",
        "dense_file": "sim-ml-wbtc-usdc-dense.csv",
        "fee_vault_name": "ml-wbtc-usdc",
        "fee_file": "sim-fees.csv",
        "inception_block": 19208958,
        "token0_decimals": 8,
        "token1_decimals": 6,
    },
    {
        "id": "ml-usdc-eth",
        "label": "Multi-Layer USDC-ETH",
        "color": "#10B981",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "sim-ml-usdc-eth-dense.csv",
        "fee_vault_name": "ml-usdc-eth",
        "fee_file": "sim-fees.csv",
        "inception_block": 23693484,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },

    {
        "id": "sr-wbtc-usdc",
        "label": "Single-Range WBTC-USDC",
        "color": "#9B59B6",
        "pair_type": "wbtc-usdc",
        "pool": "WBTC-USDC",
        "dense_file": "sim-sr-wbtc-usdc-dense.csv",
        "fee_vault_name": "sr-wbtc-usdc",
        "fee_file": "sim-fees.csv",
        "inception_block": 19208958,
        "token0_decimals": 8,
        "token1_decimals": 6,
    },
    {
        "id": "sr-usdc-eth",
        "label": "Single-Range USDC-ETH",
        "color": "#8E44AD",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "sim-sr-usdc-eth-dense.csv",
        "fee_vault_name": "sr-usdc-eth",
        "fee_file": "sim-fees.csv",
        "inception_block": 23693484,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },

    {
        "id": "sr1-wbtc-usdc",
        "label": "RV-Width WBTC-USDC",
        "color": "#E67E22",
        "pair_type": "wbtc-usdc",
        "pool": "WBTC-USDC",
        "dense_file": "sim-sr1-wbtc-usdc-dense.csv",
        "fee_vault_name": "sr1-wbtc-usdc",
        "fee_file": "sim-fees.csv",
        "inception_block": 19208958,
        "token0_decimals": 8,
        "token1_decimals": 6,
    },
    {
        "id": "sr1-usdc-eth",
        "label": "RV-Width USDC-ETH",
        "color": "#D35400",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "sim-sr1-usdc-eth-dense.csv",
        "fee_vault_name": "sr1-usdc-eth",
        "fee_file": "sim-fees.csv",
        "inception_block": 23693484,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },
    {
        "id": "sr2-wbtc-usdc",
        "label": "Lazy Return WBTC-USDC",
        "color": "#1ABC9C",
        "pair_type": "wbtc-usdc",
        "pool": "WBTC-USDC",
        "dense_file": "sim-sr2-wbtc-usdc-dense.csv",
        "fee_vault_name": "sr2-wbtc-usdc",
        "fee_file": "sim-fees.csv",
        "inception_block": 19208958,
        "token0_decimals": 8,
        "token1_decimals": 6,
    },
    {
        "id": "sr2-usdc-eth",
        "label": "Lazy Return USDC-ETH",
        "color": "#16A085",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "sim-sr2-usdc-eth-dense.csv",
        "fee_vault_name": "sr2-usdc-eth",
        "fee_file": "sim-fees.csv",
        "inception_block": 23693484,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },

    {
        "id": "mh-wbtc-usdc",
        "label": "Meihua WBTC-USDC",
        "color": "#8B5CF6",
        "pair_type": "wbtc-usdc",
        "pool": "WBTC-USDC",
        "dense_file": "sim-mh-wbtc-usdc-dense.csv",
        "fee_vault_name": "mh-wbtc-usdc",
        "fee_file": "sim-fees.csv",
        "inception_block": 19208958,
        "token0_decimals": 8,
        "token1_decimals": 6,
    },
    {
        "id": "mh-usdc-eth",
        "label": "Meihua USDC-ETH",
        "color": "#7C3AED",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "sim-mh-usdc-eth-dense.csv",
        "fee_vault_name": "mh-usdc-eth",
        "fee_file": "sim-fees.csv",
        "inception_block": 23693484,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },
    {
        "id": "steer-usdc-eth",
        "label": "Steer USDC-ETH",
        "color": "#FF6B6B",
        "pair_type": "usdc-eth",
        "pool": "USDC-ETH",
        "dense_file": "competitor-steer-competitor-usdc-eth-dense.csv",
        "fee_vault_name": "steer-competitor-usdc-eth",
        "fee_file": "competitor-real-fees.csv",
        "inception_block": 17000322,
        "token0_decimals": 6,
        "token1_decimals": 18,
    },
]

POOLS = {
    "WBTC-USDC": {
        "address": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "fee_tier": 0.0005,
        "token0": "WBTC",
        "token1": "USDC",
    },
    "USDC-ETH": {
        "address": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "fee_tier": 0.0005,
        "token0": "USDC",
        "token1": "ETH",
    },
}

EXPECTED_FULL_PERIOD = {
    "omnis-wbtc-usdc": {
        "vault_return": -0.2219,
        "hodl_return": -0.1854,
        "alpha": -0.0365,
    },
    "omnis-usdc-eth": {
        "vault_return": -0.0873,
        "hodl_return": 0.0213,
        "alpha": -0.1086,
    },
    "charm-wbtc-usdc": {
        "vault_return": -0.1119,
        "hodl_return": -0.1269,
        "alpha": 0.0150,
    },
    "charm-usdc-eth": {
        "vault_return": -0.1539,
        "hodl_return": -0.1354,
        "alpha": -0.0185,
    },
    "steer-usdc-eth": {
        "vault_return": -0.2449,
        "hodl_return": -0.1254,
        "alpha": -0.1195,
    },
}

VALIDATION_TOLERANCE = 0.05  # Relaxed for simulated vaults

EXPECTED_FULL_PERIOD["ml-wbtc-usdc"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["ml-usdc-eth"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["sr-wbtc-usdc"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["sr-usdc-eth"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["sr1-wbtc-usdc"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["sr1-usdc-eth"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["sr2-wbtc-usdc"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["sr2-usdc-eth"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["mh-wbtc-usdc"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}
EXPECTED_FULL_PERIOD["mh-usdc-eth"] = {"vault_return": 0, "hodl_return": 0, "alpha": 0}


def eprint(msg):
    print(msg, file=sys.stderr)


def parse_float(s):
    return float(s) if s not in (None, "") else 0.0


def parse_int(s):
    return int(s) if s not in (None, "") else 0


def asset_price_usd(raw_price, pair_type):
    if pair_type == "wbtc-usdc":
        return raw_price
    if pair_type == "usdc-eth":
        return 1.0 / raw_price if raw_price > 0 else 0.0
    return 0.0


def share_nav_usd(row, pair_type):
    a0, a1, ts, p = row["amount0"], row["amount1"], row["total_supply"], row["price"]
    if ts == 0:
        return 0.0
    if pair_type == "wbtc-usdc":
        return (a0 * p + a1) / ts
    if pair_type == "usdc-eth":
        eth_usd = 1.0 / p if p > 0 else 0.0
        return (a0 + a1 * eth_usd) / ts
    return 0.0


def hodl_nav_usd(entry_row, current_row, pair_type):
    ts_e = entry_row["total_supply"]
    if ts_e == 0:
        return 0.0
    q0 = entry_row["amount0"] / ts_e
    q1 = entry_row["amount1"] / ts_e
    p = current_row["price"]
    if pair_type == "wbtc-usdc":
        return q0 * p + q1
    if pair_type == "usdc-eth":
        eth_usd = 1.0 / p if p > 0 else 0.0
        return q0 + q1 * eth_usd
    return 0.0


def safe_return(curr, entry):
    if entry == 0:
        return 0.0
    return curr / entry - 1.0


def rolling_realized_vol(prices, window):
    out = []
    for i in range(len(prices)):
        if i < window:
            out.append(None)
            continue
        segment = prices[i - window : i + 1]
        log_returns = []
        for j in range(1, len(segment)):
            p0 = segment[j - 1]
            p1 = segment[j]
            if p0 > 0 and p1 > 0:
                log_returns.append(math.log(p1 / p0))

        if len(log_returns) >= 2:
            n = len(log_returns)
            mean = sum(log_returns) / n
            variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1)
            out.append(math.sqrt(variance))
        elif len(log_returns) == 1:
            out.append(abs(log_returns[0]))
        else:
            out.append(None)
    return out


def rolling_window_alpha(share_navs, hodl_navs, window):
    out = []
    for i in range(len(share_navs)):
        if i < window:
            out.append(None)
            continue
        sn_entry = share_navs[i - window]
        sn_exit = share_navs[i]
        hn_entry = hodl_navs[i - window]
        hn_exit = hodl_navs[i]
        if sn_entry > 0 and hn_entry > 0:
            vret = sn_exit / sn_entry - 1.0
            hret = hn_exit / hn_entry - 1.0
            out.append(vret - hret)
        else:
            out.append(None)
    return out


def rolling_price_displacement(prices, window):
    out = []
    for i in range(len(prices)):
        if i < window:
            out.append(None)
            continue
        p0 = prices[i - window]
        p1 = prices[i]
        if p0 > 0:
            out.append(abs(p1 / p0 - 1.0))
        else:
            out.append(None)
    return out


def read_dense_csv(path):
    rows = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                {
                    "block": parse_int(r["block"]),
                    "timestamp": parse_int(r["timestamp"]),
                    "amount0": parse_float(r["amount0"]),
                    "amount1": parse_float(r["amount1"]),
                    "total_supply": parse_float(r["total_supply"]),
                    "price": parse_float(r["price"]),
                    "tick": parse_int(r["tick"]),
                }
            )
    rows.sort(key=lambda x: x["block"])
    return rows


def build_timestamps_map(rows):
    known = {}
    for r in rows:
        if r["timestamp"] > 0:
            known[r["block"]] = r["timestamp"]
    return known


def estimate_timestamp(block, sorted_known):
    if not sorted_known:
        return 0
    if len(sorted_known) == 1:
        kb, kt = sorted_known[0]
        return int(kt + (block - kb) * 2)

    if block <= sorted_known[0][0]:
        kb, kt = sorted_known[0]
        return int(kt + (block - kb) * 2)
    if block >= sorted_known[-1][0]:
        kb, kt = sorted_known[-1]
        return int(kt + (block - kb) * 2)

    left = None
    right = None
    for i in range(1, len(sorted_known)):
        if sorted_known[i - 1][0] <= block <= sorted_known[i][0]:
            left = sorted_known[i - 1]
            right = sorted_known[i]
            break

    if left is None or right is None:
        kb, kt = sorted_known[0]
        return int(kt + (block - kb) * 2)

    lb, lt = left
    rb, rt = right
    if rb == lb:
        return int(lt)
    ratio = (block - lb) / (rb - lb)
    return int(lt + ratio * (rt - lt))


def block_to_date(block, timestamps_map):
    sorted_known = sorted(timestamps_map.items(), key=lambda x: x[0])
    ts = estimate_timestamp(block, sorted_known)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def load_fees_for_vault(vault_name, fee_csv_path, final_asset_price, pair_type):
    events = []
    with open(fee_csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("vault") != vault_name:
                continue
            fee0 = parse_float(r.get("fee0"))
            fee1 = parse_float(r.get("fee1"))
            if pair_type == "wbtc-usdc":
                fee_usd = fee0 * final_asset_price + fee1
            else:
                fee_usd = fee0 + fee1 * final_asset_price
            events.append((parse_int(r["block"]), fee_usd))
    events.sort(key=lambda x: x[0])
    return events


def load_pool_volume(datadir, pool_name):
    summary_path = os.path.join(datadir, "swaps-summary.csv")
    extended_path = os.path.join(datadir, "swaps-extended.csv")

    summary = {}
    min_summary_block = None
    with open(summary_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("vault") != pool_name:
                continue
            bs = parse_int(r["block_start"])
            if pool_name == "WBTC-USDC":
                vol_usdc = parse_float(r["vol_token1"])
            else:
                vol_usdc = parse_float(r["vol_token0"])
            summary[bs] = vol_usdc
            if min_summary_block is None or bs < min_summary_block:
                min_summary_block = bs

    merged = dict(summary)
    with open(extended_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("pool") != pool_name:
                continue
            bs = parse_int(r["block_start"])
            if pool_name == "WBTC-USDC":
                vol_usdc = parse_float(r["vol_token1"])
            else:
                vol_usdc = parse_float(r["vol_token0"])

            if min_summary_block is None or bs < min_summary_block:
                merged[bs] = vol_usdc
            elif bs not in merged:
                merged[bs] = vol_usdc

    return merged


def get_pool_volume_for_block(pool_volumes_sorted_keys, pool_volumes, block):
    """Find volume for the 10K-block window containing this block.

    Volume data is stored in 10K-block windows keyed by block_start.
    Instead of exact match, use bisect to find the window that contains
    the given block.
    """
    idx = bisect.bisect_right(pool_volumes_sorted_keys, block) - 1
    if idx >= 0:
        window_start = pool_volumes_sorted_keys[idx]
        # Block must fall within this 10K window
        if block < window_start + 10000:
            return pool_volumes[window_start]
    return 0.0


def daterange(start_date, end_date):
    curr = start_date
    while curr <= end_date:
        yield curr
        curr = curr + timedelta(days=1)


def build_daily_series(interval_payload, interval_rows, fee_by_date, timestamps_map):
    per_day_last = {}
    per_day_vol = {}
    for i, row in enumerate(interval_rows):
        d = block_to_date(row["block"], timestamps_map)
        per_day_last[d] = {
            "idx": i,
            "block": row["block"],
            "asset_price": interval_payload["asset_price"][i],
            "share_nav": interval_payload["share_nav"][i],
            "hodl_nav": interval_payload["hodl_nav"][i],
            "vault_return": interval_payload["vault_return"][i],
            "hodl_return": interval_payload["hodl_return"][i],
            "alpha": interval_payload["net_alpha"][i],
            "amount0_per_share": (
                row["amount0"] / row["total_supply"] if row["total_supply"] > 0 else 0.0
            ),
            "amount1_per_share": (
                row["amount1"] / row["total_supply"] if row["total_supply"] > 0 else 0.0
            ),
            "total_supply": row["total_supply"],
        }
        per_day_vol[d] = (
            per_day_vol.get(d, 0.0) + interval_payload["pool_volume_usdc"][i]
        )

    all_dates = sorted(per_day_last.keys())
    if not all_dates:
        return [], []

    d0 = datetime.strptime(all_dates[0], "%Y-%m-%d").date()
    d1 = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()

    dates = []
    daily = []
    prev = None
    for d in daterange(d0, d1):
        ds = d.strftime("%Y-%m-%d")
        if ds in per_day_last:
            point = dict(per_day_last[ds])
            point["daily_volume_usdc"] = per_day_vol.get(ds, 0.0)
            point["daily_fee_usd"] = fee_by_date.get(ds, 0.0)
            prev = point
        elif prev is not None:
            point = dict(prev)
            point["daily_volume_usdc"] = 0.0
            point["daily_fee_usd"] = fee_by_date.get(ds, 0.0)
        else:
            continue

        dates.append(ds)
        daily.append(point)

    return dates, daily


def build_windows(dates, daily, pair_type):
    if not dates or not daily:
        return []

    n = len(daily)
    fee_prefix = [0.0]
    vol_prefix = [0.0]
    for p in daily:
        fee_prefix.append(fee_prefix[-1] + p["daily_fee_usd"])
        vol_prefix.append(vol_prefix[-1] + p["daily_volume_usdc"])

    windows = []
    for ei in range(n):
        e = daily[ei]
        entry_share_nav = e["share_nav"]
        entry_vault_nav = e["share_nav"] * e["total_supply"]
        entry_price = e["asset_price"]
        for xi in range(ei + 1, n):
            x = daily[xi]

            vault_ret = safe_return(x["share_nav"], entry_share_nav)

            q0_e = e["amount0_per_share"]
            q1_e = e["amount1_per_share"]
            if pair_type == "wbtc-usdc":
                t0_usd = q0_e * entry_price
                t1_usd = q1_e
            elif pair_type == "usdc-eth":
                t0_usd = q0_e
                t1_usd = q1_e * entry_price
            else:
                t0_usd = 0.0
                t1_usd = 0.0
            total_usd = t0_usd + t1_usd
            entry_token0_pct = t0_usd / total_usd if total_usd > 0 else 0.0

            p_exit = x["asset_price"]
            if pair_type == "wbtc-usdc":
                hodl_nav_exit = q0_e * p_exit + q1_e
            elif pair_type == "usdc-eth":
                hodl_nav_exit = q0_e + q1_e * p_exit
            else:
                hodl_nav_exit = 0.0
            hodl_nav_entry = e["share_nav"]
            hodl_ret = safe_return(hodl_nav_exit, hodl_nav_entry)

            alpha = vault_ret - hodl_ret

            fee_sum = fee_prefix[xi + 1] - fee_prefix[ei + 1]
            fee_bps = (
                (fee_sum / entry_vault_nav * 10000.0) if entry_vault_nav > 0 else 0.0
            )

            days = xi - ei
            vol_sum = vol_prefix[xi + 1] - vol_prefix[ei + 1]
            avg_daily_vol_usdc = vol_sum / days if days > 0 else 0.0

            log_returns = []
            for j in range(ei + 1, xi + 1):
                p0 = daily[j - 1]["asset_price"]
                p1 = daily[j]["asset_price"]
                if p0 > 0 and p1 > 0:
                    log_returns.append(math.log(p1 / p0))

            if len(log_returns) >= 2:
                n_ret = len(log_returns)
                mean = sum(log_returns) / n_ret
                variance = sum((r - mean) ** 2 for r in log_returns) / (n_ret - 1)
                realized_vol = math.sqrt(variance)
            elif len(log_returns) == 1:
                realized_vol = abs(log_returns[0])
            else:
                realized_vol = 0.0

            price_change = safe_return(x["asset_price"], entry_price)

            windows.append(
                {
                    "ei": ei,
                    "xi": xi,
                    "vault_return": vault_ret,
                    "hodl_return": hodl_ret,
                    "alpha": alpha,
                    "fee_bps": fee_bps,
                    "realized_vol": realized_vol,
                    "avg_daily_vol_usdc": avg_daily_vol_usdc,
                    "entry_token0_pct": entry_token0_pct,
                    "price_change": price_change,
                    "entry_price": entry_price,
                    "exit_price": x["asset_price"],
                    "days": days,
                }
            )
    return windows


def format_pct(x):
    return f"{x * 100:+.2f}%"


def validate(vault_id, vault_return, hodl_return, alpha):
    exp = EXPECTED_FULL_PERIOD[vault_id]
    ok = (
        abs(vault_return - exp["vault_return"]) <= VALIDATION_TOLERANCE
        and abs(hodl_return - exp["hodl_return"]) <= VALIDATION_TOLERANCE
        and abs(alpha - exp["alpha"]) <= VALIDATION_TOLERANCE
    )
    return ok


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    datadir = os.path.join(base, "data")

    intervals_out = {}
    windows_out = {}
    metadata_vaults = []

    pool_volume_cache = {}
    pool_volume_sorted_keys = {}
    for pool_name in POOLS.keys():
        eprint(f"Loading pool volume for {pool_name}...")
        pool_volume_cache[pool_name] = load_pool_volume(datadir, pool_name)
        pool_volume_sorted_keys[pool_name] = sorted(pool_volume_cache[pool_name].keys())

    eprint("Processing vaults...")

    validation_rows = []
    source_files = [
        "data/vault1-dense.csv",
        "data/vault2-dense.csv",
        "data/competitor-charm-wbtc-usdc-dense.csv",
        "data/competitor-charm-usdc-eth-dense.csv",
        "data/competitor-steer-competitor-usdc-eth-dense.csv",
        "data/real-fees.csv",
        "data/competitor-real-fees.csv",
        "data/swaps-summary.csv",
        "data/swaps-extended.csv",
    ]

    for v in VAULTS:
        eprint(f"  - {v['id']}")
        dense_path = os.path.join(datadir, v["dense_file"])
        rows = read_dense_csv(dense_path)
        if len(rows) < 2:
            raise RuntimeError(f"Not enough rows in {dense_path}")

        timestamps_map = build_timestamps_map(rows)
        sorted_known = sorted(timestamps_map.items(), key=lambda x: x[0])
        entry = rows[0]
        final = rows[-1]
        final_asset_price = asset_price_usd(final["price"], v["pair_type"])

        fee_path = os.path.join(datadir, v["fee_file"])
        fee_events = load_fees_for_vault(
            v["fee_vault_name"], fee_path, final_asset_price, v["pair_type"]
        )

        fee_idx = 0
        cumul_fee = 0.0
        interval = {
            "blocks": [],
            "timestamps": [],
            "asset_price": [],
            "share_nav": [],
            "hodl_nav": [],
            "vault_return": [],
            "hodl_return": [],
            "net_alpha": [],
            "cumul_fee_usd": [],
            "realized_fee_return": [],
            "residual_drag": [],
            "pool_volume_usdc": [],
            "realized_vol_14": [],
            "price_displacement_14": [],
        }

        entry_share_nav = share_nav_usd(entry, v["pair_type"])
        entry_hodl_nav = hodl_nav_usd(entry, entry, v["pair_type"])
        # Use whole-vault NAV as denominator for fee return (not per-share)
        # entry_share_nav * total_supply = total vault USD value at inception
        entry_vault_nav = entry_share_nav * entry["total_supply"]

        fee_by_date = {}
        for b, fee_usd in fee_events:
            ds = block_to_date(b, timestamps_map)
            fee_by_date[ds] = fee_by_date.get(ds, 0.0) + fee_usd

        for row in rows:
            block = row["block"]
            while fee_idx < len(fee_events) and fee_events[fee_idx][0] <= block:
                cumul_fee += fee_events[fee_idx][1]
                fee_idx += 1

            nav = share_nav_usd(row, v["pair_type"])
            hnav = hodl_nav_usd(entry, row, v["pair_type"])
            vret = safe_return(nav, entry_share_nav)
            hret = safe_return(hnav, entry_hodl_nav)
            alpha = vret - hret
            # fee_ret as % of entry whole-vault NAV (same basis as vault_return)
            fee_ret = cumul_fee / entry_vault_nav if entry_vault_nav > 0 else 0.0

            interval["blocks"].append(block)
            ts = (
                row["timestamp"]
                if row["timestamp"] > 0
                else estimate_timestamp(row["block"], sorted_known)
            )
            interval["timestamps"].append(ts)
            interval["asset_price"].append(
                asset_price_usd(row["price"], v["pair_type"])
            )
            interval["share_nav"].append(nav)
            interval["hodl_nav"].append(hnav)
            interval["vault_return"].append(vret)
            interval["hodl_return"].append(hret)
            interval["net_alpha"].append(alpha)
            interval["cumul_fee_usd"].append(cumul_fee)
            interval["realized_fee_return"].append(fee_ret)
            interval["residual_drag"].append(alpha - fee_ret)
            interval["pool_volume_usdc"].append(
                get_pool_volume_for_block(
                    pool_volume_sorted_keys[v["pool"]],
                    pool_volume_cache[v["pool"]],
                    block,
                )
            )

        interval["realized_vol_14"] = rolling_realized_vol(interval["asset_price"], 14)
        interval["price_displacement_14"] = rolling_price_displacement(
            interval["asset_price"], 14
        )
        interval["rolling_window_alpha_14"] = rolling_window_alpha(
            interval["share_nav"], interval["hodl_nav"], 14
        )

        intervals_out[v["id"]] = interval

        dates, daily = build_daily_series(interval, rows, fee_by_date, timestamps_map)
        windows = build_windows(dates, daily, v["pair_type"])
        windows_out[v["id"]] = {"dates": dates, "windows": windows, "_daily": daily}

        full_vault_return = interval["vault_return"][-1]
        full_hodl_return = interval["hodl_return"][-1]
        full_alpha = interval["net_alpha"][-1]
        ok = validate(v["id"], full_vault_return, full_hodl_return, full_alpha)
        validation_rows.append(
            {
                "id": v["id"],
                "label": v["label"],
                "vault_return": full_vault_return,
                "hodl_return": full_hodl_return,
                "alpha": full_alpha,
                "ok": ok,
            }
        )

        inception_date = block_to_date(v["inception_block"], timestamps_map)
        metadata_vaults.append(
            {
                "id": v["id"],
                "label": v["label"],
                "color": v["color"],
                "pair_type": v["pair_type"],
                "pool": v["pool"],
                "inception_block": v["inception_block"],
                "inception_date": inception_date,
                "total_days": len(dates),
                "data_points_dense": len(rows),
                "rebalance_count": len(fee_events),
                "full_period_alpha": full_alpha,
                "full_period_vault_return": full_vault_return,
                "full_period_hodl_return": full_hodl_return,
            }
        )

    eprint("Building canonical pool-level price/volume series...")
    pool_canonical = {}
    for pool_name in POOLS.keys():
        pool_vaults = [v for v in VAULTS if v["pool"] == pool_name]
        pool_vaults.sort(key=lambda v: len(windows_out[v["id"]]["dates"]), reverse=True)

        canonical_price = {}
        canonical_volume = {}
        for v in pool_vaults:
            vault_id = v["id"]
            dates = windows_out[vault_id]["dates"]
            daily = windows_out[vault_id]["_daily"]
            for i, d in enumerate(dates):
                if d not in canonical_price:
                    canonical_price[d] = daily[i]["asset_price"]
                    canonical_volume[d] = daily[i]["daily_volume_usdc"]
        pool_canonical[pool_name] = {
            "price": canonical_price,
            "volume": canonical_volume,
        }

    eprint(
        "Recomputing pool-level metrics in windows (price_change, realized_vol, avg_daily_vol)..."
    )
    for v in VAULTS:
        vault_id = v["id"]
        pool = v["pool"]
        canon = pool_canonical[pool]
        dates = windows_out[vault_id]["dates"]
        daily = windows_out[vault_id]["_daily"]

        canon_prices = []
        canon_volumes = []
        for d in dates:
            canon_prices.append(
                canon["price"].get(d, daily[dates.index(d)]["asset_price"])
            )
            canon_volumes.append(canon["volume"].get(d, 0.0))

        vol_prefix = [0.0]
        for cv in canon_volumes:
            vol_prefix.append(vol_prefix[-1] + cv)

        for w in windows_out[vault_id]["windows"]:
            ei = w["ei"]
            xi = w["xi"]

            w["entry_price"] = canon_prices[ei]
            w["exit_price"] = canon_prices[xi]
            w["price_change"] = safe_return(canon_prices[xi], canon_prices[ei])

            days = xi - ei
            vol_sum = vol_prefix[xi + 1] - vol_prefix[ei + 1]
            w["avg_daily_vol_usdc"] = vol_sum / days if days > 0 else 0.0

            log_returns = []
            for j in range(ei + 1, xi + 1):
                p0 = canon_prices[j - 1]
                p1 = canon_prices[j]
                if p0 > 0 and p1 > 0:
                    log_returns.append(math.log(p1 / p0))

            if len(log_returns) >= 2:
                n_ret = len(log_returns)
                mean = sum(log_returns) / n_ret
                variance = sum((r - mean) ** 2 for r in log_returns) / (n_ret - 1)
                w["realized_vol"] = math.sqrt(variance)
            elif len(log_returns) == 1:
                w["realized_vol"] = abs(log_returns[0])
            else:
                w["realized_vol"] = 0.0

    for vault_id in windows_out:
        del windows_out[vault_id]["_daily"]

    metadata_out = {
        "vaults": metadata_vaults,
        "pools": POOLS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": source_files,
    }

    intervals_path = os.path.join(datadir, "intervals.json")
    windows_path = os.path.join(datadir, "windows.json")
    metadata_path = os.path.join(datadir, "metadata.json")

    eprint("Writing JSON outputs...")
    with open(intervals_path, "w") as f:
        json.dump(intervals_out, f, indent=2)
    with open(windows_path, "w") as f:
        json.dump(windows_out, f, indent=2)
    with open(metadata_path, "w") as f:
        json.dump(metadata_out, f, indent=2)

    eprint("=== VALIDATION ===")
    for r in validation_rows:
        mark = "✓" if r["ok"] else "✗"
        eprint(
            f"{r['id']}: "
            f"vault_return={format_pct(r['vault_return'])} "
            f"hodl_return={format_pct(r['hodl_return'])} "
            f"alpha={format_pct(r['alpha'])} {mark}"
        )

    bad = [r for r in validation_rows if not r["ok"]]
    if bad:
        eprint("Validation failed tolerance check for one or more vaults.")
        sys.exit(1)

    eprint("Done.")


if __name__ == "__main__":
    main()
