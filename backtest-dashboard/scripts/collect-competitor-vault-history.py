#!/usr/bin/env python3
"""
Competitor Vault Historical Performance Data Collector (Katana)
Uses batch JSON-RPC for 3x throughput. Outputs CSV per vault to ../data/
"""

import json, urllib.request, time, sys, os

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

VAULTS = [
    {
        "name": "steer-competitor-usdc-eth",
        "vault": "0x8ac9a899193475e2c5c55e80c826d2e433d583b3",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "d0": 6,
        "d1": 18,
    },
    {
        "name": "charm-usdc-eth",
        "vault": "0xc78c51f88adfbadcdfafcfef7f5e3d3c6c7d5129",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "d0": 6,
        "d1": 18,
    },
    {
        "name": "charm-wbtc-usdc",
        "vault": "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff",
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "d0": 8,
        "d1": 6,
    },
]

SAMPLE_INTERVAL = 10000
SEL_TA = "0xc4a7761e"
SEL_TS = "0x18160ddd"
SEL_S0 = "0x3850c7bd"
OUTDIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

rpc_idx = 0
call_count = 0


def rpc_raw(payload_bytes, retries=4):
    global rpc_idx, call_count
    for attempt in range(retries):
        ep = RPC_ENDPOINTS[rpc_idx % len(RPC_ENDPOINTS)]
        req = urllib.request.Request(ep, data=payload_bytes, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read())
                call_count += 1
                if isinstance(data, list):
                    return data
                if "error" in data:
                    rpc_idx += 1
                    if attempt < retries - 1:
                        time.sleep(0.4)
                        continue
                return data
        except Exception as e:
            rpc_idx += 1
            if attempt < retries - 1:
                time.sleep(0.5)
    return {"error": {"message": "all retries failed"}}


def rpc_single(method, params):
    payload = json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    ).encode()
    r = rpc_raw(payload)
    return r.get("result", "") if isinstance(r, dict) else ""


def rpc_batch(calls):
    batch = [
        {"jsonrpc": "2.0", "method": m, "params": p, "id": i}
        for i, (m, p) in enumerate(calls)
    ]
    payload = json.dumps(batch).encode()
    resp = rpc_raw(payload)
    if isinstance(resp, list):
        by_id = {r.get("id", -1): r.get("result", "") for r in resp}
        return [by_id.get(i, "") for i in range(len(calls))]
    return [""] * len(calls)


def decode_amounts(h, d0, d1):
    if not h or len(h) < 130 or h == "0x":
        return None, None
    try:
        return int(h[2:66], 16) / 10**d0, int(h[66:130], 16) / 10**d1
    except:
        return None, None


def decode_supply(h):
    if not h or h == "0x":
        return None
    try:
        return int(h, 16)
    except:
        return None


def decode_slot0(h, d0, d1):
    if not h or len(h) < 130 or h == "0x":
        return None, None
    try:
        sqrtP = int(h[2:66], 16)
        tick = int(h[66:130], 16)
        if tick > 2**23:
            tick -= 2**24
        sp = sqrtP / (2**96)
        return sp**2 * (10 ** (d0 - d1)), tick
    except:
        return None, None


def discover_inception(vault_addr, current_block):
    lo, hi = 17000000, current_block
    while hi - lo > 50000:
        mid = (lo + hi) // 2
        ts = rpc_single("eth_call", [{"to": vault_addr, "data": SEL_TS}, hex(mid)])
        supply = decode_supply(ts)
        if supply and supply > 0:
            hi = mid
        else:
            lo = mid + 1
        time.sleep(0.08)
    while hi - lo > 500:
        mid = (lo + hi) // 2
        ts = rpc_single("eth_call", [{"to": vault_addr, "data": SEL_TS}, hex(mid)])
        supply = decode_supply(ts)
        if supply and supply > 0:
            hi = mid
        else:
            lo = mid + 1
        time.sleep(0.08)
    return hi


def main():
    current_block = int(rpc_single("eth_blockNumber", []), 16)
    print(f"Current block: {current_block}", file=sys.stderr)
    os.makedirs(OUTDIR, exist_ok=True)

    for v in VAULTS:
        print(f"  Finding inception for {v['name']}...", file=sys.stderr)
        v["inception"] = discover_inception(v["vault"], current_block)
        print(f"    → block {v['inception']}", file=sys.stderr)

    for v in VAULTS:
        name, inception = v["name"], v["inception"]
        d0, d1 = v["d0"], v["d1"]
        blocks = list(range(inception, current_block, SAMPLE_INTERVAL))
        blocks.append(current_block)
        total = len(blocks)

        fname = os.path.join(OUTDIR, f"competitor-{name}-dense.csv")
        print(
            f"\n═══ {name}: {total} samples from block {inception} ═══", file=sys.stderr
        )
        outf = open(fname, "w")
        outf.write("block,timestamp,amount0,amount1,total_supply,price,tick\n")
        written = 0

        BATCH = 8
        for bi in range(0, total, BATCH):
            chunk = blocks[bi : bi + BATCH]

            state_calls = []
            for bn in chunk:
                bh = hex(bn)
                state_calls.append(
                    ("eth_call", [{"to": v["vault"], "data": SEL_TA}, bh])
                )
                state_calls.append(
                    ("eth_call", [{"to": v["vault"], "data": SEL_TS}, bh])
                )
                state_calls.append(
                    ("eth_call", [{"to": v["pool"], "data": SEL_S0}, bh])
                )
            state_results = rpc_batch(state_calls)

            ts_blocks = [
                bn
                for idx, bn in enumerate(chunk)
                if (bi + idx) % 15 == 0 or (bi + idx) == 0 or (bi + idx) == total - 1
            ]
            ts_map = {}
            if ts_blocks:
                ts_calls = [
                    ("eth_getBlockByNumber", [hex(bn), False]) for bn in ts_blocks
                ]
                ts_results = rpc_batch(ts_calls)
                for bn, r in zip(ts_blocks, ts_results):
                    if isinstance(r, dict) and "timestamp" in r:
                        ts_map[bn] = int(r["timestamp"], 16)

            for idx, bn in enumerate(chunk):
                ta_h = state_results[idx * 3]
                ts_h = state_results[idx * 3 + 1]
                s0_h = state_results[idx * 3 + 2]
                supply = decode_supply(ts_h)
                if not supply or supply == 0:
                    continue
                amt0, amt1 = decode_amounts(ta_h, d0, d1)
                price, tick = decode_slot0(s0_h, d0, d1)
                ts = ts_map.get(bn, 0)
                fmt0 = f"{amt0:.8f}" if amt0 is not None else ""
                if d0 == 6:
                    fmt0 = f"{amt0:.6f}" if amt0 is not None else ""
                fmt1 = f"{amt1:.18f}" if amt1 is not None else ""
                if d1 == 6:
                    fmt1 = f"{amt1:.6f}" if amt1 is not None else ""
                outf.write(
                    f"{bn},{ts},{fmt0},{fmt1},{supply},{price if price else ''},{tick if tick is not None else ''}\n"
                )
                written += 1

            done = min(bi + BATCH, total)
            if done % 100 < BATCH or done == total:
                print(
                    f"  {done}/{total} ({written} pts, {call_count} rpcs)",
                    file=sys.stderr,
                )
            time.sleep(0.1)

        outf.close()
        print(
            f"  ✅ {name}: {written} points → {os.path.basename(fname)}",
            file=sys.stderr,
        )

    print(f"\n═══ DONE. Total RPC calls: {call_count} ═══", file=sys.stderr)


if __name__ == "__main__":
    main()
