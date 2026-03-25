#!/usr/bin/env python3
"""
Collect Burn+Collect events for 3 competitor vaults + extended swap volume
from block 17M (competitor inception) for both pools.
Outputs: competitor-fees.csv, competitor-real-fees.csv, swaps-extended.csv
"""

import json, urllib.request, time, sys, os
from collections import defaultdict

RPC_ENDPOINTS = [
    "https://lb.drpc.live/katana/AvfmCE6mEEFUj4Xz0ihu_lGdy-GpGI0R8Z0HtuZZzRRv",
    "https://katana.gateway.tenderly.co",
    "https://katana.drpc.org",
    "https://rpc.katanarpc.com",
    "https://rpc.katana.network",
]
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}

OUTDIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

rpc_idx = 0
call_count = 0

VAULTS = [
    {
        "name": "steer-competitor-usdc-eth",
        "vault": "0x8ac9a899193475e2c5c55e80c826d2e433d583b3",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "d0": 6,
        "d1": 18,
        "inception": 17000322,
    },
    {
        "name": "charm-usdc-eth",
        "vault": "0xc78c51f88adfbadcdfafcfef7f5e3d3c6c7d5129",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "d0": 6,
        "d1": 18,
        "inception": 17000322,
    },
    {
        "name": "charm-wbtc-usdc",
        "vault": "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff",
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "d0": 8,
        "d1": 6,
        "inception": 17000322,
    },
]

COLLECT_TOPIC = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"
BURN_TOPIC = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

POOLS = [
    {
        "name": "USDC-ETH",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "d0": 6,
        "d1": 18,
    },
    {
        "name": "WBTC-USDC",
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "d0": 8,
        "d1": 6,
    },
]


def rpc_call(method, params, retries=4):
    global rpc_idx, call_count
    for attempt in range(retries):
        ep = RPC_ENDPOINTS[rpc_idx % len(RPC_ENDPOINTS)]
        payload = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        ).encode()
        req = urllib.request.Request(ep, data=payload, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read())
                call_count += 1
                if "error" in data:
                    rpc_idx += 1
                    if attempt < retries - 1:
                        time.sleep(0.4)
                        continue
                return data
        except Exception as e:
            rpc_idx += 1
            if attempt < retries - 1:
                time.sleep(0.6)
    return {"error": {"message": "all retries failed"}}


def get_current_block():
    return int(rpc_call("eth_blockNumber", []).get("result", "0x0"), 16)


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
        if isinstance(result, dict) and "error" in result:
            if chunk_size > 5000:
                chunk_size = chunk_size // 2
                continue
            else:
                print(
                    f"    ⚠ Log fetch failed at {current}-{end}: {result['error']}",
                    file=sys.stderr,
                )
                current = end + 1
                continue
        logs = result.get("result", [])
        all_logs.extend(logs)
        current = end + 1
        time.sleep(0.12)
    return all_logs


def main():
    current_block = get_current_block()
    print(f"Current block: {current_block}", file=sys.stderr)
    os.makedirs(OUTDIR, exist_ok=True)

    # ═══ PART 1: COLLECT + BURN EVENTS FOR COMPETITOR VAULTS ═══
    fee_file = open(os.path.join(OUTDIR, "competitor-fees.csv"), "w")
    fee_file.write(
        "vault,event_type,block,tx_hash,tick_lower,tick_upper,amount0,amount1\n"
    )

    real_fees_file = open(os.path.join(OUTDIR, "competitor-real-fees.csv"), "w")
    real_fees_file.write(
        "vault,block,tx_hash,burn_amt0,burn_amt1,collect_amt0,collect_amt1,fee0,fee1\n"
    )

    for v in VAULTS:
        name = v["name"]
        vault_topic = "0x" + "0" * 24 + v["vault"][2:].lower()
        d0, d1 = v["d0"], v["d1"]
        pool = v["pool"]
        inception = v["inception"]

        print(f"\n═══ {name} ═══", file=sys.stderr)

        print(f"  Fetching Burn events...", file=sys.stderr)
        burns = get_logs_chunked(
            pool, [BURN_TOPIC, vault_topic], inception, current_block
        )
        print(f"  → {len(burns)} Burns", file=sys.stderr)

        print(f"  Fetching Collect events...", file=sys.stderr)
        collects = get_logs_chunked(
            pool, [COLLECT_TOPIC, vault_topic], inception, current_block
        )
        print(f"  → {len(collects)} Collects", file=sys.stderr)

        for log in burns:
            block = int(log["blockNumber"], 16)
            tx = log["transactionHash"]
            tl = int(log["topics"][2], 16)
            if tl > 2**23:
                tl -= 2**24
            tu = int(log["topics"][3], 16)
            if tu > 2**23:
                tu -= 2**24
            data = log["data"][2:]
            amt0 = int(data[64:128], 16) / 10**d0
            amt1 = int(data[128:192], 16) / 10**d1
            fee_file.write(
                f"{name},Burn,{block},{tx},{tl},{tu},{amt0:.8f},{amt1:.18f}\n"
            )

        for log in collects:
            block = int(log["blockNumber"], 16)
            tx = log["transactionHash"]
            tl = int(log["topics"][2], 16)
            if tl > 2**23:
                tl -= 2**24
            tu = int(log["topics"][3], 16)
            if tu > 2**23:
                tu -= 2**24
            data = log["data"][2:]
            c0 = int(data[64:128], 16) / 10**d0
            c1 = int(data[128:192], 16) / 10**d1
            fee_file.write(
                f"{name},Collect,{block},{tx},{tl},{tu},{c0:.8f},{c1:.18f}\n"
            )

        burn_by_tx = defaultdict(list)
        for log in burns:
            tx = log["transactionHash"]
            data = log["data"][2:]
            amt0 = int(data[64:128], 16) / 10**d0
            amt1 = int(data[128:192], 16) / 10**d1
            burn_by_tx[tx].append((amt0, amt1))

        collect_by_tx = defaultdict(list)
        for log in collects:
            tx = log["transactionHash"]
            block = int(log["blockNumber"], 16)
            data = log["data"][2:]
            c0 = int(data[64:128], 16) / 10**d0
            c1 = int(data[128:192], 16) / 10**d1
            collect_by_tx[tx].append((block, c0, c1))

        total_fee0, total_fee1 = 0, 0
        matched, unmatched = 0, 0

        for tx, collect_list in collect_by_tx.items():
            burn_list = burn_by_tx.get(tx, [])
            sum_burn0 = sum(b[0] for b in burn_list)
            sum_burn1 = sum(b[1] for b in burn_list)
            sum_collect0 = sum(c[1] for c in collect_list)
            sum_collect1 = sum(c[2] for c in collect_list)
            block = collect_list[0][0]

            fee0 = max(0, sum_collect0 - sum_burn0)
            fee1 = max(0, sum_collect1 - sum_burn1)
            total_fee0 += fee0
            total_fee1 += fee1

            if burn_list:
                matched += 1
            else:
                unmatched += 1

            real_fees_file.write(
                f"{name},{block},{tx},{sum_burn0:.8f},{sum_burn1:.18f},"
                f"{sum_collect0:.8f},{sum_collect1:.18f},{fee0:.8f},{fee1:.18f}\n"
            )

        print(f"  Matched tx: {matched}, Collect-only: {unmatched}", file=sys.stderr)
        print(f"  Real fee token0: {total_fee0:.8f}", file=sys.stderr)
        print(f"  Real fee token1: {total_fee1:.8f}", file=sys.stderr)

        if "wbtc" in name:
            usd_fee = total_fee0 * 70000 + total_fee1
            print(f"  Fee USD estimate: ${usd_fee:,.2f}", file=sys.stderr)
        else:
            usd_fee = total_fee0 + total_fee1 * 2100
            print(f"  Fee USD estimate: ${usd_fee:,.2f}", file=sys.stderr)

    fee_file.close()
    real_fees_file.close()

    # ═══ PART 2: EXTENDED SWAP VOLUME (block 17M → existing data start) ═══
    print(f"\n═══ EXTENDED SWAP VOLUME ═══", file=sys.stderr)
    existing_start_wbtc = 19208958
    existing_start_eth = 23693484
    competitor_start = 17000322

    swap_file = open(os.path.join(OUTDIR, "swaps-extended.csv"), "w")
    swap_file.write("pool,block_start,block_end,num_swaps,vol_token0,vol_token1\n")

    for pool_info in POOLS:
        pname = pool_info["name"]
        pool_addr = pool_info["pool"]
        d0, d1 = pool_info["d0"], pool_info["d1"]

        if "ETH" in pname:
            end_block = existing_start_eth
        else:
            end_block = existing_start_wbtc

        print(f"  {pname}: blocks {competitor_start} → {end_block}", file=sys.stderr)

        window = 10000
        current = competitor_start
        windows_done = 0
        while current < end_block:
            end = min(current + window - 1, end_block - 1)
            params = {
                "fromBlock": hex(current),
                "toBlock": hex(end),
                "address": pool_addr,
                "topics": [SWAP_TOPIC],
            }
            result = rpc_call("eth_getLogs", [params])

            if isinstance(result, dict) and "error" in result:
                if window > 5000:
                    window = window // 2
                    continue
                current = end + 1
                continue

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
                vol0 = total0 / 10**d0
                vol1 = total1 / 10**d1
                swap_file.write(
                    f"{pname},{current},{end},{len(logs)},{vol0:.8f},{vol1:.8f}\n"
                )

            current = end + 1
            windows_done += 1
            if windows_done % 50 == 0:
                print(
                    f"    {pname}: {windows_done} windows ({call_count} rpcs)",
                    file=sys.stderr,
                )
            time.sleep(0.1)

        print(f"  ✅ {pname}: {windows_done} windows done", file=sys.stderr)

    swap_file.close()
    print(f"\n═══ DONE. Total RPC calls: {call_count} ═══", file=sys.stderr)


if __name__ == "__main__":
    main()
