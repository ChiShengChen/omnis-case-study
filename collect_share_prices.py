#!/usr/bin/env python3
"""
採樣 vault share price 歷史 (totalAmounts / totalSupply)
========================================================
用 defi-onchain-analytics skill 方法論：eth_call at historical blocks

Vaults:
  WBTC-USDC: 0x5977767ef6324864F170318681ecCB82315f8761 (block 19.2M→27.5M)
  USDC-ETH:  0x811b8c618716ca62b092b67c09e55361ae6df429 (block 23.7M→27.5M)

採樣: 每 5000 blocks (~1.4 hrs) 一次
輸出: data/share_price_btc.csv, data_eth/share_price_eth.csv
"""
import csv, json, time, requests, math
from pathlib import Path

RPC_URLS = [
    "https://katana.drpc.org",
    "https://katana.gateway.tenderly.co",
    "https://rpc.katanarpc.com",
]

VAULTS = [
    {
        "name": "WBTC-USDC",
        "vault": "0x5977767ef6324864F170318681ecCB82315f8761",
        "pool": "0x744676b3ced942d78f9b8e9cd22246db5c32395c",
        "t0_dec": 8, "t1_dec": 6,  # token0=vbWBTC, token1=vbUSDC
        "start": 19_208_958, "end": 27_522_192,
        "output": Path(__file__).parent / "data" / "share_price_btc.csv",
        "price_fn": "direct",  # price = t1/t0 = USDC per WBTC
    },
    {
        "name": "USDC-ETH",
        "vault": "0x811b8c618716ca62b092b67c09e55361ae6df429",
        "pool": "0x2a2c512beaa8eb15495726c235472d82effb7a6b",
        "t0_dec": 6, "t1_dec": 18,  # token0=vbUSDC, token1=vbETH
        "start": 23_693_484, "end": 27_522_192,
        "output": Path(__file__).parent / "data_eth" / "share_price_eth.csv",
        "price_fn": "invert",  # price = 1/(t1/t0) = USDC per ETH
    },
]

SAMPLE_INTERVAL = 5000  # blocks

# totalAmounts selector: 0xc4a7761e (Steer vault)
# totalSupply selector: 0x18160ddd (ERC20)
# slot0 selector: 0x3850c7bd (pool)
SEL_TOTAL_AMOUNTS = "0xc4a7761e"
SEL_TOTAL_SUPPLY = "0x18160ddd"
SEL_SLOT0 = "0x3850c7bd"


class Rpc:
    def __init__(self):
        self.idx = 0
        self.last = 0
        self.calls = 0

    def call(self, method, params, retries=3):
        for attempt in range(retries):
            elapsed = time.time() - self.last
            if elapsed < 0.2:
                time.sleep(0.2 - elapsed)
            self.last = time.time()
            self.calls += 1
            try:
                r = requests.post(RPC_URLS[self.idx],
                    json={"jsonrpc": "2.0", "id": self.calls, "method": method, "params": params},
                    timeout=15)
                data = r.json()
                if "error" in data:
                    raise Exception(str(data["error"]))
                return data.get("result")
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2)
                    self.idx = (self.idx + 1) % len(RPC_URLS)
                else:
                    raise

    def batch(self, calls_list, retries=3):
        for attempt in range(retries):
            elapsed = time.time() - self.last
            if elapsed < 0.2:
                time.sleep(0.2 - elapsed)
            self.last = time.time()
            self.calls += len(calls_list)
            payloads = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                        for i, (m, p) in enumerate(calls_list)]
            try:
                r = requests.post(RPC_URLS[self.idx], json=payloads, timeout=30)
                results = r.json()
                if isinstance(results, list):
                    results.sort(key=lambda x: x.get("id", 0))
                    return [x.get("result") for x in results]
                raise Exception(f"Unexpected: {type(results)}")
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2)
                    self.idx = (self.idx + 1) % len(RPC_URLS)
                else:
                    raise


def decode_uint256(hex_str):
    if not hex_str or hex_str == "0x":
        return 0
    d = hex_str[2:] if hex_str.startswith("0x") else hex_str
    return int(d[:64], 16) if len(d) >= 64 else int(d, 16)


def decode_two_uint256(hex_str):
    """Decode totalAmounts() → (amount0, amount1)"""
    if not hex_str or len(hex_str) < 130:
        return 0, 0
    d = hex_str[2:] if hex_str.startswith("0x") else hex_str
    return int(d[0:64], 16), int(d[64:128], 16)


def decode_slot0_price(hex_str, t0_dec, t1_dec, price_fn):
    """Decode slot0 → price in USDC terms"""
    if not hex_str or len(hex_str) < 130:
        return 0
    d = hex_str[2:] if hex_str.startswith("0x") else hex_str
    sqrtP = int(d[0:64], 16)
    Q96 = 2**96
    price_raw = (sqrtP / Q96) ** 2
    price_human = price_raw * (10 ** (t0_dec - t1_dec))
    if price_fn == "invert":
        return 1.0 / price_human if price_human > 0 else 0
    return price_human


def collect_vault(rpc, cfg):
    name = cfg["name"]
    vault = cfg["vault"]
    pool = cfg["pool"]
    start, end = cfg["start"], cfg["end"]
    out_file = cfg["output"]
    t0_dec, t1_dec = cfg["t0_dec"], cfg["t1_dec"]
    price_fn = cfg["price_fn"]

    blocks = list(range(start, end + 1, SAMPLE_INTERVAL))
    print(f"\n📊 {name}: {len(blocks)} samples (block {start:,}→{end:,})")

    with open(out_file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["block", "amount0", "amount1", "totalSupply", "price",
                     "share_price_usd", "vault_value_usd"])

        BATCH = 3  # 3 calls per block (totalAmounts, totalSupply, slot0)
        for i in range(0, len(blocks), 4):  # 4 blocks per batch = 12 RPC calls
            batch_blocks = blocks[i:i+4]
            calls = []
            for b in batch_blocks:
                bh = hex(b)
                calls.append(("eth_call", [{"to": vault, "data": SEL_TOTAL_AMOUNTS}, bh]))
                calls.append(("eth_call", [{"to": vault, "data": SEL_TOTAL_SUPPLY}, bh]))
                calls.append(("eth_call", [{"to": pool, "data": SEL_SLOT0}, bh]))

            try:
                results = rpc.batch(calls)
                for j, b in enumerate(batch_blocks):
                    ta_hex = results[j*3]
                    ts_hex = results[j*3+1]
                    s0_hex = results[j*3+2]

                    a0, a1 = decode_two_uint256(ta_hex)
                    total_supply = decode_uint256(ts_hex)
                    price = decode_slot0_price(s0_hex, t0_dec, t1_dec, price_fn)

                    if total_supply > 0 and price > 0:
                        a0_human = a0 / (10 ** t0_dec)
                        a1_human = a1 / (10 ** t1_dec)

                        if price_fn == "invert":
                            vault_usd = a0_human + a1_human * price
                        else:
                            vault_usd = a0_human * price + a1_human

                        # share_price = vault_usd / totalSupply (raw, 不除 1e18)
                        # Steer vault shares 用 decimals=18 但 supply 的 raw 值很小
                        share_price = vault_usd / total_supply

                        w.writerow([b, a0, a1, total_supply, f"{price:.2f}",
                                    f"{share_price:.6f}", f"{vault_usd:.2f}"])

                f.flush()
                done = min(i + 4, len(blocks))
                if done % 100 == 0 or done >= len(blocks):
                    print(f"  [{done}/{len(blocks)}] {done/len(blocks)*100:.0f}%")

            except Exception as e:
                print(f"  ❌ Batch at block {batch_blocks[0]}: {e}")
                time.sleep(2)

    lines = sum(1 for _ in open(out_file)) - 1
    print(f"  ✅ {out_file.name}: {lines} rows")


def main():
    print("=" * 60)
    print("Vault Share Price History Collection")
    print("=" * 60)

    rpc = Rpc()

    tip = int(rpc.call("eth_blockNumber", []), 16)
    print(f"Connected (tip: {tip:,})")

    for cfg in VAULTS:
        collect_vault(rpc, cfg)

    print(f"\n✅ Done! Total RPC calls: {rpc.calls:,}")


if __name__ == "__main__":
    main()
