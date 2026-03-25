#!/usr/bin/env python3
"""
Collect fee (Collect events) and swap volume data for both Katana Steer vaults.
Also does dense vault state sampling for USDC-ETH vault.

Outputs 3 CSV files:
  - fees.csv: all Collect events (fees earned by each vault)
  - swaps-summary.csv: swap volume per 10k-block window
  - vault2-dense.csv: dense state sampling for USDC-ETH vault
"""

import json, urllib.request, time, sys, os

RPC_ENDPOINTS = [
    "https://katana.drpc.org",
    "https://katana.gateway.tenderly.co",
]
rpc_idx = 0
call_count = 0
OUTDIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)


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
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
                call_count += 1
                if "error" in data:
                    rpc_idx += 1
                    if attempt < retries - 1:
                        time.sleep(0.5)
                        continue
                return data
        except Exception as e:
            rpc_idx += 1
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return {"error": {"message": str(e)}}
    return {"error": {"message": "all retries failed"}}


def eth_call(to, data, block_hex):
    r = rpc_call("eth_call", [{"to": to, "data": data}, block_hex])
    return r.get("result", "")


def get_logs_chunked(address, topics, from_block, to_block, chunk_size=50000):
    all_logs = []
    current = from_block
    while current <= to_block:
        end = min(current + chunk_size - 1, to_block)
        params = {
            "fromBlock": hex(current),
            "toBlock": hex(end),
            "address": address,
            "topics": topics,
        }
        result = rpc_call("eth_getLogs", [params])
        if "error" in result:
            if chunk_size > 5000:
                chunk_size = chunk_size // 2
                continue
            else:
                print(
                    f"  ⚠ Log fetch failed at {current}-{end}: {result['error']}",
                    file=sys.stderr,
                )
                current = end + 1
                continue
        logs = result.get("result", [])
        all_logs.extend(logs)
        current = end + 1
        time.sleep(0.2)
    return all_logs


def get_current_block():
    r = rpc_call("eth_blockNumber", [])
    return int(r.get("result", "0x0"), 16)


def get_block_timestamp(block_hex):
    r = rpc_call("eth_getBlockByNumber", [block_hex, False])
    b = r.get("result", {})
    return int(b["timestamp"], 16) if b and "timestamp" in b else 0


VAULTS = [
    {
        "name": "WBTC-USDC",
        "vault": "0x5977767ef6324864F170318681ecCB82315f8761",
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "t0": "WBTC",
        "t1": "USDC",
        "d0": 8,
        "d1": 6,
        "inception": 19208958,
    },
    {
        "name": "USDC-ETH",
        "vault": "0x811b8c618716ca62b092b67c09e55361ae6df429",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "t0": "USDC",
        "t1": "vbETH",
        "d0": 6,
        "d1": 18,
        "inception": 23693484,
    },
]

# Collect event: keccak256("Collect(address,address,int24,int24,uint128,uint128)")
COLLECT_TOPIC = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


def main():
    current_block = get_current_block()
    print(f"Current block: {current_block}", file=sys.stderr)

    # ═══ PART 1: COLLECT EVENTS (FEES) ═══
    print("\n═══ COLLECTING FEE DATA ═══", file=sys.stderr)
    fee_file = open(os.path.join(OUTDIR, "fees.csv"), "w")
    fee_file.write("vault,block,tx_hash,tick_lower,tick_upper,fee0,fee1\n")

    for v in VAULTS:
        vault_topic = "0x" + "0" * 24 + v["vault"][2:].lower()
        print(f"  Fetching Collect events for {v['name']}...", file=sys.stderr)
        logs = get_logs_chunked(
            v["pool"], [COLLECT_TOPIC, vault_topic], v["inception"], current_block
        )
        print(f"  Found {len(logs)} Collect events for {v['name']}", file=sys.stderr)

        for log in logs:
            block = int(log["blockNumber"], 16)
            tx = log["transactionHash"]
            tl = int(log["topics"][2], 16)
            if tl > 2**23:
                tl -= 2**24
            tu = int(log["topics"][3], 16)
            if tu > 2**23:
                tu -= 2**24
            data = log["data"][2:]
            # data: recipient(address,32) + amount0(uint128,32) + amount1(uint128,32)
            fee0 = int(data[64:128], 16) / (10 ** v["d0"])
            fee1 = int(data[128:192], 16) / (10 ** v["d1"])
            fee_file.write(
                f"{v['name']},{block},{tx},{tl},{tu},{fee0:.8f},{fee1:.8f}\n"
            )

    fee_file.close()
    print(f"  Fee data saved.", file=sys.stderr)

    # ═══ PART 2: SWAP VOLUME (summarized per 10k blocks) ═══
    print("\n═══ COLLECTING SWAP VOLUME ═══", file=sys.stderr)
    swap_file = open(os.path.join(OUTDIR, "swaps-summary.csv"), "w")
    swap_file.write("vault,block_start,block_end,num_swaps,vol_token0,vol_token1\n")

    for v in VAULTS:
        print(f"  Fetching Swap events for {v['name']}...", file=sys.stderr)
        window = 10000
        current = v["inception"]
        while current <= current_block:
            end = min(current + window - 1, current_block)
            params = {
                "fromBlock": hex(current),
                "toBlock": hex(end),
                "address": v["pool"],
                "topics": [SWAP_TOPIC],
            }
            result = rpc_call("eth_getLogs", [params])
            logs = result.get("result", [])

            if logs:
                total0, total1 = 0, 0
                for log in logs:
                    data = log["data"][2:]
                    a0 = int(data[0:64], 16)
                    if a0 > 2**255:
                        a0 -= 2**256
                    a1 = int(data[64:128], 16)
                    if a1 > 2**255:
                        a1 -= 2**256
                    total0 += abs(a0)
                    total1 += abs(a1)
                vol0 = total0 / (10 ** v["d0"])
                vol1 = total1 / (10 ** v["d1"])
                swap_file.write(
                    f"{v['name']},{current},{end},{len(logs)},{vol0:.8f},{vol1:.8f}\n"
                )

            current = end + 1
            time.sleep(0.15)

        print(f"  Swap volume done for {v['name']}", file=sys.stderr)

    swap_file.close()
    print(f"  Swap data saved.", file=sys.stderr)

    # ═══ PART 3: DENSE STATE SAMPLING FOR USDC-ETH ═══
    print("\n═══ DENSE SAMPLING USDC-ETH ═══", file=sys.stderr)
    v2 = VAULTS[1]
    dense_file = open(os.path.join(OUTDIR, "vault2-dense.csv"), "w")
    dense_file.write("block,timestamp,amount0,amount1,total_supply,price,tick\n")

    interval = 10000  # every ~2.8 hours
    blocks = list(range(v2["inception"], current_block, interval))
    blocks.append(current_block)
    total = len(blocks)

    for i, bn in enumerate(blocks):
        bh = hex(bn)
        ta = eth_call(v2["vault"], "0xc4a7761e", bh)
        ts_r = eth_call(v2["vault"], "0x18160ddd", bh)
        s0 = eth_call(v2["pool"], "0x3850c7bd", bh)

        supply = int(ts_r, 16) if ts_r and ts_r != "0x" else 0
        if supply == 0:
            continue

        amt0 = int(ta[2:66], 16) / (10 ** v2["d0"]) if ta and len(ta) >= 130 else 0
        amt1 = int(ta[66:130], 16) / (10 ** v2["d1"]) if ta and len(ta) >= 130 else 0

        price, tick = 0, 0
        if s0 and len(s0) > 130:
            sqrtP = int(s0[2:66], 16)
            tick = int(s0[66:130], 16)
            if tick > 2**23:
                tick -= 2**24
            sp = sqrtP / (2**96)
            price = sp**2 * (10 ** (v2["d0"] - v2["d1"]))

        ts = 0
        if i % 10 == 0 or i == total - 1:
            ts = get_block_timestamp(bh)

        dense_file.write(
            f"{bn},{ts},{amt0:.6f},{amt1:.18f},{supply},{price:.18f},{tick}\n"
        )

        if (i + 1) % 50 == 0:
            print(
                f"  USDC-ETH dense: {i + 1}/{total} ({call_count} calls)",
                file=sys.stderr,
            )
        time.sleep(0.25)

    dense_file.close()
    print(f"  Dense sampling done.", file=sys.stderr)

    # ═══ PART 4: DENSE STATE SAMPLING FOR WBTC-USDC TOO ═══
    print("\n═══ DENSE SAMPLING WBTC-USDC ═══", file=sys.stderr)
    v1 = VAULTS[0]
    dense1_file = open(os.path.join(OUTDIR, "vault1-dense.csv"), "w")
    dense1_file.write("block,timestamp,amount0,amount1,total_supply,price,tick\n")

    blocks1 = list(range(v1["inception"], current_block, interval))
    blocks1.append(current_block)
    total1 = len(blocks1)

    for i, bn in enumerate(blocks1):
        bh = hex(bn)
        ta = eth_call(v1["vault"], "0xc4a7761e", bh)
        ts_r = eth_call(v1["vault"], "0x18160ddd", bh)
        s0 = eth_call(v1["pool"], "0x3850c7bd", bh)

        supply = int(ts_r, 16) if ts_r and ts_r != "0x" else 0
        if supply == 0:
            continue

        amt0 = int(ta[2:66], 16) / (10 ** v1["d0"]) if ta and len(ta) >= 130 else 0
        amt1 = int(ta[66:130], 16) / (10 ** v1["d1"]) if ta and len(ta) >= 130 else 0

        price, tick = 0, 0
        if s0 and len(s0) > 130:
            sqrtP = int(s0[2:66], 16)
            tick = int(s0[66:130], 16)
            if tick > 2**23:
                tick -= 2**24
            sp = sqrtP / (2**96)
            price = sp**2 * (10 ** (v1["d0"] - v1["d1"]))

        ts = 0
        if i % 10 == 0 or i == total1 - 1:
            ts = get_block_timestamp(bh)

        dense1_file.write(
            f"{bn},{ts},{amt0:.8f},{amt1:.6f},{supply},{price:.6f},{tick}\n"
        )

        if (i + 1) % 50 == 0:
            print(
                f"  WBTC-USDC dense: {i + 1}/{total1} ({call_count} calls)",
                file=sys.stderr,
            )
        time.sleep(0.25)

    dense1_file.close()
    print(f"\n═══ ALL DONE. Total RPC calls: {call_count} ═══", file=sys.stderr)


if __name__ == "__main__":
    main()
