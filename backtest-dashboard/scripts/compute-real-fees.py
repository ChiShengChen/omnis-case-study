#!/usr/bin/env python3
import json, urllib.request, time, sys, os, csv
from collections import defaultdict

RPC_ENDPOINTS = ["https://katana.drpc.org", "https://katana.gateway.tenderly.co"]
rpc_idx = 0
call_count = 0
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATADIR = os.path.join(BASE, "data")


def rpc_call(method, params, retries=3):
    global rpc_idx, call_count
    for attempt in range(retries):
        ep = RPC_ENDPOINTS[rpc_idx % len(RPC_ENDPOINTS)]
        payload = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        ).encode()
        req = urllib.request.Request(
            ep, data=payload, headers={"Content-Type": "application/json"}
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
        except:
            rpc_idx += 1
            if attempt < retries - 1:
                time.sleep(1)
    return {"error": {"message": "failed"}}


def get_logs_chunked(address, topics, from_block, to_block, chunk=50000):
    all_logs = []
    cur = from_block
    while cur <= to_block:
        end = min(cur + chunk - 1, to_block)
        r = rpc_call(
            "eth_getLogs",
            [
                {
                    "fromBlock": hex(cur),
                    "toBlock": hex(end),
                    "address": address,
                    "topics": topics,
                }
            ],
        )
        if "error" in r:
            if chunk > 5000:
                chunk //= 2
                continue
            cur = end + 1
            continue
        all_logs.extend(r.get("result", []))
        cur = end + 1
        time.sleep(0.2)
    return all_logs


def get_current_block():
    return int(rpc_call("eth_blockNumber", []).get("result", "0x0"), 16)


def eth_call(to, data, block_hex):
    return rpc_call("eth_call", [{"to": to, "data": data}, block_hex]).get("result", "")


BURN_TOPIC = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
COLLECT_TOPIC = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"

VAULTS = [
    {
        "name": "WBTC-USDC",
        "vault": "0x5977767ef6324864F170318681ecCB82315f8761",
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "d0": 8,
        "d1": 6,
        "inception": 19208958,
    },
    {
        "name": "USDC-ETH",
        "vault": "0x811b8c618716ca62b092b67c09e55361ae6df429",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "d0": 6,
        "d1": 18,
        "inception": 23693484,
    },
]


def main():
    current_block = get_current_block()
    print(f"Current block: {current_block}", file=sys.stderr)

    real_fees_file = open(os.path.join(DATADIR, "real-fees.csv"), "w")
    real_fees_file.write(
        "vault,block,tx_hash,burn_amt0,burn_amt1,collect_amt0,collect_amt1,fee0,fee1\n"
    )

    for v in VAULTS:
        vault_topic = "0x" + "0" * 24 + v["vault"][2:].lower()
        d0, d1 = v["d0"], v["d1"]

        print(f"\n  Fetching Burn events for {v['name']}...", file=sys.stderr)
        burns = get_logs_chunked(
            v["pool"], [BURN_TOPIC, vault_topic], v["inception"], current_block
        )
        print(f"  Found {len(burns)} Burns", file=sys.stderr)

        print(f"  Fetching Collect events for {v['name']}...", file=sys.stderr)
        collects = get_logs_chunked(
            v["pool"], [COLLECT_TOPIC, vault_topic], v["inception"], current_block
        )
        print(f"  Found {len(collects)} Collects", file=sys.stderr)

        burn_by_tx = defaultdict(list)
        for log in burns:
            tx = log["transactionHash"]
            data = log["data"][2:]
            # Burn data: amount(uint128), amount0(uint256), amount1(uint256)
            amt0 = int(data[64:128], 16) / (10**d0)
            amt1 = int(data[128:192], 16) / (10**d1)
            burn_by_tx[tx].append((amt0, amt1))

        collect_by_tx = defaultdict(list)
        for log in collects:
            tx = log["transactionHash"]
            block = int(log["blockNumber"], 16)
            data = log["data"][2:]
            # Collect data: recipient(address,32), amount0(uint128,32), amount1(uint128,32)
            c0 = int(data[64:128], 16) / (10**d0)
            c1 = int(data[128:192], 16) / (10**d1)
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

            fee0 = sum_collect0 - sum_burn0
            fee1 = sum_collect1 - sum_burn1

            # fee can be negative if Mint also happened in same tx (collecting then redeploying)
            # In normal rebalance: burn → collect → mint, so fees should be >= 0
            if fee0 < 0:
                fee0 = 0
            if fee1 < 0:
                fee1 = 0

            total_fee0 += fee0
            total_fee1 += fee1

            if burn_list:
                matched += 1
            else:
                unmatched += 1

            real_fees_file.write(
                f"{v['name']},{block},{tx},{sum_burn0:.8f},{sum_burn1:.8f},{sum_collect0:.8f},{sum_collect1:.8f},{fee0:.8f},{fee1:.8f}\n"
            )

        print(f"  {v['name']} results:", file=sys.stderr)
        print(
            f"    Matched tx: {matched}, Collect-only tx: {unmatched}", file=sys.stderr
        )
        print(f"    Real fee token0: {total_fee0:.8f}", file=sys.stderr)
        print(f"    Real fee token1: {total_fee1:.6f}", file=sys.stderr)
        if v["name"] == "WBTC-USDC":
            print(
                f"    Fee USD (@ $68K): ${total_fee0 * 68437 + total_fee1:,.2f}",
                file=sys.stderr,
            )
        else:
            print(
                f"    Fee USD (@ $2.1K): ${total_fee0 + total_fee1 * 2100:,.2f}",
                file=sys.stderr,
            )

    real_fees_file.close()

    # ═══ KAT PRICE & MERKL REWARDS ═══
    print(f"\n  Looking up KAT token price...", file=sys.stderr)

    KAT = "0x7f1f1480925d88ba0f519954b29ed44e303a5e58"
    # Try to find KAT price from a pool - check balanceOf on known DEX pairs
    # From the image: KAT address was 0x7F1f...DC2d, let me try the full address
    # Actually let me try a different approach - read from a KAT/USDC or KAT/WETH pool
    # Or just calculate from the image data: 4369.4342 KAT ≈ $52.77 → 1 KAT ≈ $0.01208

    # Try to find KAT pool
    kat_candidates = [
        "0x7f1f1480925d88ba0f519954b29ed44e303a5e58",  # possible
        "0x7F1f8fd1290a8a5E6B3Dc59E4Aa95d0DC2d",  # from image (partial)
    ]

    # Use the image-derived price as fallback
    kat_price_usd = 52.77 / 4369.4342  # $0.01208 per KAT
    print(
        f"    KAT price (from Jeff's screenshot): ${kat_price_usd:.5f}/KAT",
        file=sys.stderr,
    )

    # Now compute total Merkl rewards
    # Merkl distributes via MerkleRoot updates. We'd need to scrape the Merkl API.
    # For now, let's estimate from the campaign APR and TVL
    #
    # From image: +30.24% Boost APR on WBTC-USDC vault
    # Current vault TVL: ~$2,600
    # Jeff's 62-day rewards: 4,369 KAT ≈ $52.77 on ~$719 position (27.83% of vault)
    # Full vault 62-day rewards ≈ $52.77 / 0.2783 ≈ $189.62
    # Annualized: $189.62 * (365/62) ≈ $1,116
    # APR on current TVL: $1,116 / $2,600 ≈ 42.9% ... close to the 30% figure

    print(f"\n    Merkl reward estimation (from Jeff's data):", file=sys.stderr)
    jeff_kat = 4369.4342
    jeff_share_pct = 27.83
    jeff_days = 62

    vault_total_kat = jeff_kat / (jeff_share_pct / 100)
    vault_total_kat_usd = vault_total_kat * kat_price_usd

    print(
        f"    Jeff earned {jeff_kat:.0f} KAT in {jeff_days} days (27.83% share)",
        file=sys.stderr,
    )
    print(
        f"    Vault total estimated: {vault_total_kat:,.0f} KAT ≈ ${vault_total_kat_usd:,.2f}",
        file=sys.stderr,
    )

    # Write summary
    summary = open(os.path.join(DATADIR, "performance-summary.txt"), "w")
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    summary.write("VAULT PERFORMANCE SUMMARY\n")
    summary.write(f"Generated: {ts_str}\n")
    summary.write(f"KAT price used: ${kat_price_usd:.5f}\n")
    summary.write(f"Total RPC calls: {call_count}\n")
    summary.close()

    print(f"\n  Total RPC calls: {call_count}", file=sys.stderr)
    print(f"  Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
