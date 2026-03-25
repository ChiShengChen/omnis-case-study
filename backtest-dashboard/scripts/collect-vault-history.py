#!/usr/bin/env python3
"""
Steer Vault Historical Performance Data Collector

Collects time-series data for two Katana Steer vaults:
  Vault 1: 0x5977... (WBTC/USDC)
  Vault 2: 0x811b... (USDC/vbETH)

For each sample point, queries:
  - totalAmounts (0xc4a7761e) → vault's total token holdings
  - totalSupply (0x18160ddd) → vault share supply
  - slot0 (0x3850c7bd) → pool price

Outputs CSV to stdout.
"""

import json
import urllib.request
import time
import sys
import math

# === CONFIG ===
RPC_ENDPOINTS = [
    "https://katana.drpc.org",
    "https://katana.gateway.tenderly.co",
]

VAULTS = [
    {
        "name": "WBTC-USDC",
        "vault": "0x5977767ef6324864F170318681ecCB82315f8761",
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "token0": "WBTC",
        "token1": "USDC",
        "token0_decimals": 8,
        "token1_decimals": 6,
        "inception_block": 19208958,
    },
    {
        "name": "USDC-ETH",
        "vault": "0x811b8c618716ca62b092b67c09e55361ae6df429",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "token0": "USDC",
        "token1": "vbETH",
        "token0_decimals": 6,
        "token1_decimals": 18,
        "inception_block": None,  # will discover
    },
]

# Sample every N blocks (~14 hours at 1 block/sec)
SAMPLE_INTERVAL = 50000

# Selectors
SEL_TOTAL_AMOUNTS = "0xc4a7761e"
SEL_TOTAL_SUPPLY = "0x18160ddd"
SEL_SLOT0 = "0x3850c7bd"

# === RPC HELPERS ===
rpc_idx = 0
call_count = 0


def rpc_call(method, params, retries=3):
    global rpc_idx, call_count
    for attempt in range(retries):
        endpoint = RPC_ENDPOINTS[rpc_idx % len(RPC_ENDPOINTS)]
        payload = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        ).encode()
        req = urllib.request.Request(
            endpoint, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                call_count += 1
                if "error" in data:
                    # Rotate endpoint on error
                    rpc_idx += 1
                    if attempt < retries - 1:
                        time.sleep(0.5)
                        continue
                    return data
                return data
        except Exception as e:
            rpc_idx += 1
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return {"error": {"message": str(e)}}
    return {"error": {"message": "all retries failed"}}


def eth_call(to, data, block_hex):
    result = rpc_call("eth_call", [{"to": to, "data": data}, block_hex])
    return result.get("result", "")


def get_block_timestamp(block_hex):
    result = rpc_call("eth_getBlockByNumber", [block_hex, False])
    block = result.get("result", {})
    if block and "timestamp" in block:
        return int(block["timestamp"], 16)
    return 0


def get_current_block():
    result = rpc_call("eth_blockNumber", [])
    return int(result.get("result", "0x0"), 16)


# === DATA EXTRACTION ===
def decode_total_amounts(hex_result, dec0, dec1):
    """Decode (uint256, uint256) from totalAmounts call"""
    if not hex_result or len(hex_result) < 130 or hex_result == "0x":
        return None, None
    try:
        t0 = int(hex_result[2:66], 16) / (10**dec0)
        t1 = int(hex_result[66:130], 16) / (10**dec1)
        return t0, t1
    except:
        return None, None


def decode_total_supply(hex_result):
    if not hex_result or hex_result == "0x":
        return None
    try:
        return int(hex_result, 16)
    except:
        return None


def decode_slot0(hex_result, dec0, dec1):
    """Decode sqrtPriceX96 and tick from slot0, return human price"""
    if not hex_result or len(hex_result) < 130 or hex_result == "0x":
        return None, None
    try:
        sqrt_price_x96 = int(hex_result[2:66], 16)
        tick_raw = int(hex_result[66:130], 16)
        if tick_raw > 2**23:
            tick_raw -= 2**24

        sqrt_price = sqrt_price_x96 / (2**96)
        raw_price = sqrt_price**2  # token1/token0 in raw units
        # Adjust for decimals: human_price = raw_price * 10^(dec0 - dec1)
        human_price = raw_price * (10 ** (dec0 - dec1))
        return human_price, tick_raw
    except:
        return None, None


def sample_vault(vault_cfg, block_num):
    """Sample one vault at one block. Returns dict of data."""
    block_hex = hex(block_num)
    vault_addr = vault_cfg["vault"]
    pool_addr = vault_cfg["pool"]
    dec0 = vault_cfg["token0_decimals"]
    dec1 = vault_cfg["token1_decimals"]

    # totalAmounts
    ta_result = eth_call(vault_addr, SEL_TOTAL_AMOUNTS, block_hex)
    amt0, amt1 = decode_total_amounts(ta_result, dec0, dec1)

    # totalSupply
    ts_result = eth_call(vault_addr, SEL_TOTAL_SUPPLY, block_hex)
    total_supply = decode_total_supply(ts_result)

    # slot0 (pool price)
    s0_result = eth_call(pool_addr, SEL_SLOT0, block_hex)
    price, tick = decode_slot0(s0_result, dec0, dec1)

    return {
        "amount0": amt0,
        "amount1": amt1,
        "total_supply": total_supply,
        "price": price,
        "tick": tick,
    }


# === MAIN ===
def main():
    current_block = get_current_block()
    print(f"# Current block: {current_block}", file=sys.stderr)
    print(f"# Sample interval: {SAMPLE_INTERVAL} blocks", file=sys.stderr)

    # Discover vault 2 inception by checking totalSupply at various blocks
    print("# Discovering Vault 2 inception...", file=sys.stderr)
    v2_inception = None
    # Binary search: find first block where totalSupply > 0
    lo, hi = 19000000, current_block
    while lo < hi:
        mid = (lo + hi) // 2
        ts = eth_call(VAULTS[1]["vault"], SEL_TOTAL_SUPPLY, hex(mid))
        supply = decode_total_supply(ts)
        if supply and supply > 0:
            hi = mid
        else:
            lo = mid + 1
        if hi - lo < SAMPLE_INTERVAL:
            break
    VAULTS[1]["inception_block"] = lo
    print(f"# Vault 2 inception: ~block {lo}", file=sys.stderr)

    # Print CSV header
    print("vault,block,timestamp,amount0,amount1,total_supply,price,tick")

    for vault_cfg in VAULTS:
        name = vault_cfg["name"]
        inception = vault_cfg["inception_block"]
        print(f"# Processing {name} from block {inception}...", file=sys.stderr)

        # Generate sample points
        blocks = list(range(inception, current_block, SAMPLE_INTERVAL))
        blocks.append(current_block)  # always include latest

        total = len(blocks)
        for i, block_num in enumerate(blocks):
            data = sample_vault(vault_cfg, block_num)

            # Get timestamp (but only every 5th sample to reduce calls)
            ts = 0
            if i % 5 == 0 or i == total - 1:
                ts = get_block_timestamp(hex(block_num))

            # Skip if vault not yet active
            if data["total_supply"] is None or data["total_supply"] == 0:
                continue

            amt0 = f"{data['amount0']:.8f}" if data["amount0"] is not None else ""
            amt1 = f"{data['amount1']:.6f}" if data["amount1"] is not None else ""
            price = f"{data['price']:.6f}" if data["price"] is not None else ""
            tick = str(data["tick"]) if data["tick"] is not None else ""

            print(
                f"{name},{block_num},{ts},{amt0},{amt1},{data['total_supply']},{price},{tick}"
            )

            if (i + 1) % 10 == 0:
                print(
                    f"# {name}: {i + 1}/{total} samples done ({call_count} RPC calls total)",
                    file=sys.stderr,
                )

            # Rate limiting
            time.sleep(0.3)

    print(f"# Done. Total RPC calls: {call_count}", file=sys.stderr)


if __name__ == "__main__":
    main()
