#!/usr/bin/env python3
"""
WBTC-USDC Pool 細粒度數據收集腳本
===================================
目標：收集 Katana 上 WBTC-USDC pool 的完整歷史數據用於回測

數據範圍：
  Pool:  0x744676b3ced942d78f9b8e9cd22246db5c32395c (SushiSwap V3, 5bps)
  Omnis: 0x5977767ef6324864F170318681ecCB82315f8761
  Charm: 0xbc2ae38ce7127854b08ec5956f8a31547f6390ff
  Block: 19,208,958 → 27,522,192 (~96 天, 2025-12-17 → 2026-03-23)
  Token0: vbWBTC (8 dec), Token1: vbUSDC (6 dec)

收集項目：
  1. 池子價格時間序列 (slot0 每 2000 block 採樣 → ~4,150 點)
  2. 所有 Swap 事件 (計算不同區間下的 fee 收入)
  3. Omnis + Charm vault 的 Burn/Collect/Mint 事件 (重建 rebalance 歷史)

方法論參考：defi-onchain-analytics skill (CLAMM vault analytics pattern)
"""

import json
import csv
import time
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import requests

# ─── 配置 ───────────────────────────────────────────────────────────────────

POOL = "0x744676b3ced942d78f9b8e9cd22246db5c32395c"
OMNIS_VAULT = "0x5977767ef6324864F170318681ecCB82315f8761"
CHARM_VAULT = "0xbc2ae38ce7127854b08ec5956f8a31547f6390ff"

TOKEN0_DECIMALS = 8   # vbWBTC
TOKEN1_DECIMALS = 6   # vbUSDC

START_BLOCK = 19_208_958
END_BLOCK = 27_522_192

# 採樣間隔（每 2000 block ≈ 33 分鐘）
PRICE_SAMPLE_INTERVAL = 2000

# getLogs 分塊大小（Katana public RPC 通常支持 10K block）
LOG_CHUNK_SIZE = 10_000

# Katana RPC 端點（依 skill registry 排序：S tier 優先）
RPC_ENDPOINTS = [
    "https://katana.drpc.org",
    "https://katana.gateway.tenderly.co",
    "https://rpc.katanarpc.com",
    "https://747474.rpc.thirdweb.com",
    "https://rpc.katana.network",
]

# Event topics (Uniswap V3 / SushiSwap V3)
TOPICS = {
    "swap":    "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
    "burn":    "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c",
    "collect": "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0",
    "mint":    "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde",
}

# 輸出目錄
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

# Checkpoint
CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint.json"


# ─── RPC 客戶端 ─────────────────────────────────────────────────────────────

class RpcClient:
    """帶端點輪換和重試的 JSON-RPC 客戶端"""

    def __init__(self, endpoints: List[str], requests_per_second: float = 5):
        self.endpoints = endpoints
        self.current_idx = 0
        self.min_interval = 1.0 / requests_per_second
        self.last_call_time = 0
        self.call_count = 0
        self.error_count = 0

    @property
    def current(self) -> str:
        return self.endpoints[self.current_idx]

    def rotate(self):
        self.current_idx = (self.current_idx + 1) % len(self.endpoints)
        print(f"  ↻ Rotated to: {self.current[:50]}...")

    def _rate_limit(self):
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()

    def call(self, method: str, params: list, retries: int = 3) -> dict:
        """執行單一 RPC 調用"""
        for attempt in range(retries):
            self._rate_limit()
            payload = {
                "jsonrpc": "2.0",
                "id": self.call_count,
                "method": method,
                "params": params,
            }
            self.call_count += 1
            try:
                resp = requests.post(
                    self.current, json=payload, timeout=15,
                    headers={"Content-Type": "application/json"}
                )
                data = resp.json()
                if "error" in data:
                    err = data["error"]
                    msg = err.get("message", str(err))
                    # getLogs 範圍太大，縮小
                    if any(code in str(err.get("code", "")) for code in ["-32005", "-32602", "-32614"]):
                        raise ValueError(f"Range too large: {msg}")
                    raise Exception(f"RPC error: {msg}")
                return data.get("result")
            except (requests.Timeout, requests.ConnectionError, Exception) as e:
                self.error_count += 1
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  ⚠ {method} failed ({e}), retry in {wait}s...")
                    time.sleep(wait)
                    if attempt >= 1:
                        self.rotate()
                else:
                    raise

    def batch_call(self, calls: List[Tuple[str, list]], retries: int = 3) -> List:
        """批次 RPC 調用"""
        for attempt in range(retries):
            self._rate_limit()
            payloads = [
                {"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                for i, (m, p) in enumerate(calls)
            ]
            self.call_count += len(calls)
            try:
                resp = requests.post(
                    self.current, json=payloads, timeout=30,
                    headers={"Content-Type": "application/json"}
                )
                results = resp.json()
                if isinstance(results, list):
                    results.sort(key=lambda r: r.get("id", 0))
                    return [r.get("result") for r in results]
                raise Exception(f"Unexpected batch response: {type(results)}")
            except Exception as e:
                self.error_count += 1
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  ⚠ Batch failed ({e}), retry in {wait}s...")
                    time.sleep(wait)
                    self.rotate()
                else:
                    raise


# ─── 數據解碼 ────────────────────────────────────────────────────────────────

def hex_to_int(h: str, signed: bool = False) -> int:
    """十六進制轉整數"""
    if not h or h == "0x":
        return 0
    val = int(h, 16)
    if signed and val >= 2**255:
        val -= 2**256
    return val

def decode_slot0(result: str) -> dict:
    """解碼 slot0() 回傳值"""
    if not result or len(result) < 130:
        return None
    data = result[2:] if result.startswith("0x") else result
    sqrt_price_x96 = int(data[0:64], 16)
    tick_raw = int(data[64:128], 16)
    if tick_raw > 2**23:
        tick_raw -= 2**24

    Q96 = 2**96
    price_raw = (sqrt_price_x96 / Q96) ** 2
    # token0=vbWBTC(8dec), token1=vbUSDC(6dec)
    # price = token1/token0 (USDC per WBTC)
    price_usdc_per_wbtc = price_raw * (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))

    return {
        "sqrtPriceX96": sqrt_price_x96,
        "tick": tick_raw,
        "price": price_usdc_per_wbtc,
    }

def decode_swap_log(log: dict) -> dict:
    """解碼 Swap 事件"""
    data = log["data"][2:] if log["data"].startswith("0x") else log["data"]
    # Swap(sender, recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
    # topics[1] = sender (indexed), topics[2] = recipient (indexed)
    # data = amount0(256) + amount1(256) + sqrtPriceX96(256) + liquidity(256) + tick(256)
    amount0 = hex_to_int("0x" + data[0:64], signed=True)
    amount1 = hex_to_int("0x" + data[64:128], signed=True)
    sqrt_price_x96 = hex_to_int("0x" + data[128:192])
    liquidity = hex_to_int("0x" + data[192:256])
    tick_raw = hex_to_int("0x" + data[256:320], signed=True)

    Q96 = 2**96
    price_raw = (sqrt_price_x96 / Q96) ** 2
    price = price_raw * (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))

    return {
        "block": hex_to_int(log["blockNumber"]),
        "tx_hash": log["transactionHash"],
        "log_index": hex_to_int(log["logIndex"]),
        "amount0": amount0,  # vbWBTC (8 dec)
        "amount1": amount1,  # vbUSDC (6 dec)
        "sqrtPriceX96": sqrt_price_x96,
        "liquidity": liquidity,
        "tick": tick_raw,
        "price": price,
    }

def decode_burn_log(log: dict) -> dict:
    """解碼 Burn 事件"""
    # Burn(address indexed owner, int24 indexed tickLower, int24 indexed tickUpper, uint128 amount, uint256 amount0, uint256 amount1)
    owner = "0x" + log["topics"][1][-40:]
    tick_lower = hex_to_int(log["topics"][2], signed=True)
    tick_upper = hex_to_int(log["topics"][3], signed=True)

    data = log["data"][2:] if log["data"].startswith("0x") else log["data"]
    amount = hex_to_int("0x" + data[0:64])
    amount0 = hex_to_int("0x" + data[64:128])
    amount1 = hex_to_int("0x" + data[128:192])

    return {
        "block": hex_to_int(log["blockNumber"]),
        "tx_hash": log["transactionHash"],
        "log_index": hex_to_int(log["logIndex"]),
        "event": "Burn",
        "owner": owner.lower(),
        "tickLower": tick_lower,
        "tickUpper": tick_upper,
        "liquidity": amount,
        "amount0": amount0,
        "amount1": amount1,
    }

def decode_collect_log(log: dict) -> dict:
    """解碼 Collect 事件"""
    # Collect(address indexed owner, address recipient, int24 indexed tickLower, int24 indexed tickUpper, uint128 amount0, uint128 amount1)
    owner = "0x" + log["topics"][1][-40:]
    tick_lower = hex_to_int(log["topics"][2], signed=True)
    tick_upper = hex_to_int(log["topics"][3], signed=True)

    data = log["data"][2:] if log["data"].startswith("0x") else log["data"]
    recipient = "0x" + data[0:64][-40:]
    amount0 = hex_to_int("0x" + data[64:128])
    amount1 = hex_to_int("0x" + data[128:192])

    return {
        "block": hex_to_int(log["blockNumber"]),
        "tx_hash": log["transactionHash"],
        "log_index": hex_to_int(log["logIndex"]),
        "event": "Collect",
        "owner": owner.lower(),
        "recipient": recipient.lower(),
        "tickLower": tick_lower,
        "tickUpper": tick_upper,
        "amount0": amount0,
        "amount1": amount1,
    }

def decode_mint_log(log: dict) -> dict:
    """解碼 Mint 事件"""
    # Mint(address sender, address indexed owner, int24 indexed tickLower, int24 indexed tickUpper, uint128 amount, uint256 amount0, uint256 amount1)
    owner = "0x" + log["topics"][1][-40:]
    tick_lower = hex_to_int(log["topics"][2], signed=True)
    tick_upper = hex_to_int(log["topics"][3], signed=True)

    data = log["data"][2:] if log["data"].startswith("0x") else log["data"]
    sender = "0x" + data[0:64][-40:]
    amount = hex_to_int("0x" + data[64:128])
    amount0 = hex_to_int("0x" + data[128:192])
    amount1 = hex_to_int("0x" + data[192:256])

    return {
        "block": hex_to_int(log["blockNumber"]),
        "tx_hash": log["transactionHash"],
        "log_index": hex_to_int(log["logIndex"]),
        "event": "Mint",
        "sender": sender.lower(),
        "owner": owner.lower(),
        "tickLower": tick_lower,
        "tickUpper": tick_upper,
        "liquidity": amount,
        "amount0": amount0,
        "amount1": amount1,
    }


# ─── Checkpoint ──────────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {}

def save_checkpoint(data: dict):
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2))


# ─── 收集函數 ────────────────────────────────────────────────────────────────

def collect_price_series(rpc: RpcClient, checkpoint: dict) -> str:
    """收集池子價格時間序列（slot0 批次採樣）"""
    output_file = OUTPUT_DIR / "price_series.csv"
    last_block = checkpoint.get("price_last_block", START_BLOCK)

    # 計算所有需要採樣的 block
    sample_blocks = list(range(last_block, END_BLOCK + 1, PRICE_SAMPLE_INTERVAL))
    total = len(sample_blocks)
    print(f"\n📊 Price Series: {total} samples (every {PRICE_SAMPLE_INTERVAL} blocks)")

    # 如果有既有數據，追加模式
    file_exists = output_file.exists() and last_block > START_BLOCK
    mode = "a" if file_exists else "w"

    with open(output_file, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["block", "sqrtPriceX96", "tick", "price"])
        if not file_exists:
            writer.writeheader()

        # 批次查詢 slot0（每批 8 個，避免過大）
        BATCH_SIZE = 8
        for i in range(0, total, BATCH_SIZE):
            batch_blocks = sample_blocks[i:i + BATCH_SIZE]
            calls = [
                ("eth_call", [
                    {"to": POOL, "data": "0x3850c7bd"},  # slot0()
                    hex(b)
                ])
                for b in batch_blocks
            ]

            try:
                results = rpc.batch_call(calls)
                for block_num, result in zip(batch_blocks, results):
                    if result and len(result) >= 130:
                        decoded = decode_slot0(result)
                        if decoded:
                            writer.writerow({
                                "block": block_num,
                                "sqrtPriceX96": decoded["sqrtPriceX96"],
                                "tick": decoded["tick"],
                                "price": f"{decoded['price']:.2f}",
                            })
                f.flush()
                checkpoint["price_last_block"] = batch_blocks[-1]

                done = min(i + BATCH_SIZE, total)
                if done % 200 == 0 or done == total:
                    pct = done / total * 100
                    print(f"  [{done}/{total}] {pct:.1f}% — block {batch_blocks[-1]}")
                    save_checkpoint(checkpoint)

            except Exception as e:
                print(f"  ❌ Batch failed at block {batch_blocks[0]}: {e}")
                save_checkpoint(checkpoint)
                # 降級為單筆查詢
                for block_num in batch_blocks:
                    try:
                        result = rpc.call("eth_call", [
                            {"to": POOL, "data": "0x3850c7bd"},
                            hex(block_num)
                        ])
                        if result and len(result) >= 130:
                            decoded = decode_slot0(result)
                            if decoded:
                                writer.writerow({
                                    "block": block_num,
                                    "sqrtPriceX96": decoded["sqrtPriceX96"],
                                    "tick": decoded["tick"],
                                    "price": f"{decoded['price']:.2f}",
                                })
                    except Exception as e2:
                        print(f"    ⚠ Skip block {block_num}: {e2}")

    save_checkpoint(checkpoint)
    print(f"  ✅ Price series saved to {output_file}")
    return str(output_file)


def collect_events(rpc: RpcClient, checkpoint: dict, event_type: str,
                   topic: str, address: str, output_file: Path,
                   decoder, checkpoint_key: str,
                   fieldnames: List[str]) -> str:
    """通用事件收集函數"""
    last_block = checkpoint.get(checkpoint_key, START_BLOCK)
    total_blocks = END_BLOCK - last_block
    chunks = (total_blocks // LOG_CHUNK_SIZE) + 1
    print(f"\n📡 {event_type}: scanning {total_blocks} blocks in {chunks} chunks")

    file_exists = output_file.exists() and last_block > START_BLOCK
    mode = "a" if file_exists else "w"
    event_count = 0

    with open(output_file, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        from_block = last_block
        chunk_idx = 0
        chunk_size = LOG_CHUNK_SIZE

        while from_block < END_BLOCK:
            to_block = min(from_block + chunk_size - 1, END_BLOCK)
            chunk_idx += 1

            filter_obj = {
                "address": address,
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "topics": [topic],
            }

            try:
                logs = rpc.call("eth_getLogs", [filter_obj])
                if logs:
                    for log in logs:
                        try:
                            decoded = decoder(log)
                            writer.writerow(decoded)
                            event_count += 1
                        except Exception as e:
                            print(f"    ⚠ Decode error: {e}")
                    f.flush()

                checkpoint[checkpoint_key] = to_block + 1
                if chunk_idx % 20 == 0 or to_block >= END_BLOCK:
                    pct = (to_block - START_BLOCK) / (END_BLOCK - START_BLOCK) * 100
                    print(f"  [{chunk_idx}] {pct:.1f}% — block {to_block}, {event_count} events")
                    save_checkpoint(checkpoint)

                from_block = to_block + 1
                chunk_size = LOG_CHUNK_SIZE  # 恢復正常 chunk size

            except ValueError as e:
                # 範圍太大，縮小
                if "Range too large" in str(e) or "range" in str(e).lower():
                    chunk_size = max(1000, chunk_size // 2)
                    print(f"  ↓ Reduced chunk to {chunk_size} blocks")
                else:
                    raise
            except Exception as e:
                print(f"  ❌ Error at block {from_block}: {e}")
                save_checkpoint(checkpoint)
                time.sleep(5)
                rpc.rotate()

    save_checkpoint(checkpoint)
    print(f"  ✅ {event_type}: {event_count} events → {output_file}")
    return str(output_file)


# ─── 主程序 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("WBTC-USDC Pool Data Collection (Katana)")
    print(f"Pool:    {POOL}")
    print(f"Omnis:   {OMNIS_VAULT}")
    print(f"Charm:   {CHARM_VAULT}")
    print(f"Blocks:  {START_BLOCK:,} → {END_BLOCK:,} ({(END_BLOCK-START_BLOCK):,} blocks)")
    print(f"Output:  {OUTPUT_DIR}")
    print("=" * 60)

    rpc = RpcClient(RPC_ENDPOINTS, requests_per_second=5)
    checkpoint = load_checkpoint()

    # 測試連接
    try:
        tip = rpc.call("eth_blockNumber", [])
        print(f"\n✅ Connected to {rpc.current[:50]}... (tip: {hex_to_int(tip):,})")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    # ── 1. 價格時間序列 ──
    collect_price_series(rpc, checkpoint)

    # ── 2. Swap 事件 ──
    collect_events(
        rpc, checkpoint,
        event_type="Swap Events",
        topic=TOPICS["swap"],
        address=POOL,
        output_file=OUTPUT_DIR / "swaps.csv",
        decoder=decode_swap_log,
        checkpoint_key="swap_last_block",
        fieldnames=["block", "tx_hash", "log_index", "amount0", "amount1",
                     "sqrtPriceX96", "liquidity", "tick", "price"],
    )

    # ── 3. Vault Burn 事件（Omnis + Charm 都在同一個 pool 上） ──
    # Pool 的 Burn 事件，之後按 owner 過濾
    collect_events(
        rpc, checkpoint,
        event_type="Burn Events (all vaults)",
        topic=TOPICS["burn"],
        address=POOL,
        output_file=OUTPUT_DIR / "burns.csv",
        decoder=decode_burn_log,
        checkpoint_key="burn_last_block",
        fieldnames=["block", "tx_hash", "log_index", "event", "owner",
                     "tickLower", "tickUpper", "liquidity", "amount0", "amount1"],
    )

    # ── 4. Collect 事件 ──
    collect_events(
        rpc, checkpoint,
        event_type="Collect Events (all vaults)",
        topic=TOPICS["collect"],
        address=POOL,
        output_file=OUTPUT_DIR / "collects.csv",
        decoder=decode_collect_log,
        checkpoint_key="collect_last_block",
        fieldnames=["block", "tx_hash", "log_index", "event", "owner", "recipient",
                     "tickLower", "tickUpper", "amount0", "amount1"],
    )

    # ── 5. Mint 事件 ──
    collect_events(
        rpc, checkpoint,
        event_type="Mint Events (all vaults)",
        topic=TOPICS["mint"],
        address=POOL,
        output_file=OUTPUT_DIR / "mints.csv",
        decoder=decode_mint_log,
        checkpoint_key="mint_last_block",
        fieldnames=["block", "tx_hash", "log_index", "event", "sender", "owner",
                     "tickLower", "tickUpper", "liquidity", "amount0", "amount1"],
    )

    # ── 完成 ──
    print("\n" + "=" * 60)
    print(f"✅ 數據收集完成！")
    print(f"   RPC 調用次數: {rpc.call_count:,}")
    print(f"   錯誤次數: {rpc.error_count}")
    print(f"   輸出目錄: {OUTPUT_DIR}")
    print()
    for f in sorted(OUTPUT_DIR.glob("*.csv")):
        lines = sum(1 for _ in open(f)) - 1  # 扣掉 header
        size_kb = f.stat().st_size / 1024
        print(f"   {f.name}: {lines:,} rows ({size_kb:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
