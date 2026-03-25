#!/usr/bin/env python3
"""從 swap 事件建構價格時間序列，缺漏部分用 RPC slot0 補充"""
import csv
import requests
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
POOL = "0x744676b3ced942d78f9b8e9cd22246db5c32395c"
START = 19_208_958
END = 27_522_192
INTERVAL = 2000

RPC_URLS = [
    "https://katana.drpc.org",
    "https://katana.gateway.tenderly.co",
    "https://rpc.katanarpc.com",
]

def main():
    # 1. 從 swap 事件中提取價格
    print("Loading swap events...")
    swaps = []
    with open(DATA_DIR / "swaps.csv") as f:
        for row in csv.DictReader(f):
            swaps.append((int(row["block"]), int(row["tick"]), float(row["price"])))
    print(f"  Total swaps: {len(swaps)}")

    # 每 INTERVAL block 取最近一筆 swap 的價格
    prices = {}
    swap_idx = 0
    for target_block in range(START, END + 1, INTERVAL):
        while swap_idx < len(swaps) - 1 and swaps[swap_idx + 1][0] <= target_block:
            swap_idx += 1
        if swap_idx < len(swaps) and swaps[swap_idx][0] <= target_block:
            prices[target_block] = swaps[swap_idx]
    print(f"  Price points from swaps: {len(prices)}")

    # 2. 用 RPC 補充 swap 稀疏的區間
    missing = [b for b in range(START, END + 1, INTERVAL) if b not in prices]
    print(f"  Missing blocks to fill via RPC: {len(missing)}")

    rpc_idx = 0
    filled = 0
    for i, block in enumerate(missing):
        for attempt in range(3):
            try:
                r = requests.post(
                    RPC_URLS[rpc_idx],
                    json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": POOL, "data": "0x3850c7bd"}, hex(block)]},
                    timeout=10,
                )
                result = r.json().get("result")
                if result and len(result) >= 130:
                    data = result[2:]
                    sqrtP = int(data[0:64], 16)
                    tick = int(data[64:128], 16)
                    if tick > 2**23:
                        tick -= 2**24
                    Q96 = 2**96
                    price = (sqrtP / Q96) ** 2 * (10 ** (8 - 6))
                    prices[block] = (block, tick, price)
                    filled += 1
                    break
            except Exception:
                rpc_idx = (rpc_idx + 1) % len(RPC_URLS)
                time.sleep(1)
        if (i + 1) % 50 == 0:
            print(f"  RPC fill: {i+1}/{len(missing)} ({filled} ok)")
        time.sleep(0.15)

    print(f"  RPC filled: {filled}")

    # 3. 寫入 CSV
    with open(DATA_DIR / "price_series.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["block", "sqrtPriceX96", "tick", "price"])
        for block in sorted(prices.keys()):
            _, tick, price = prices[block]
            writer.writerow([block, "", tick, f"{price:.2f}"])

    total = len(prices)
    first_b = min(prices.keys())
    last_b = max(prices.keys())
    print(f"\n✅ price_series.csv: {total} rows")
    print(f"   First: block {first_b}, price ${prices[first_b][2]:.2f}")
    print(f"   Last:  block {last_b}, price ${prices[last_b][2]:.2f}")


if __name__ == "__main__":
    main()
