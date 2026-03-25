#!/usr/bin/env python3
"""
USDC-ETH Pool 數據收集腳本
===========================
Pool:  0x2a2c512beaa8eb15495726c235472d82effb7a6b (SushiSwap V3, 5bps)
Omnis: 0x811b8c618716ca62b092b67c09e55361ae6df429
Token0: vbUSDC (6 dec), Token1: vbETH (18 dec)
Block: 23,693,484 → 27,522,192 (~70 天)

複用 collect_wbtc_usdc_data.py 的 RPC 架構，改池子參數
"""
import json, csv, time, sys, requests
from pathlib import Path

POOL = "0x2a2c512beaa8eb15495726c235472d82effb7a6b"
OMNIS_VAULT = "0x811b8c618716ca62b092b67c09e55361ae6df429"
TOKEN0_DECIMALS = 6   # vbUSDC
TOKEN1_DECIMALS = 18  # vbETH
START_BLOCK = 23_693_484
END_BLOCK = 27_522_192
PRICE_SAMPLE_INTERVAL = 2000
LOG_CHUNK_SIZE = 10_000

OUTPUT_DIR = Path(__file__).parent / "data_eth"
OUTPUT_DIR.mkdir(exist_ok=True)
CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint.json"

RPC_ENDPOINTS = [
    "https://katana.drpc.org",
    "https://katana.gateway.tenderly.co",
    "https://rpc.katanarpc.com",
    "https://747474.rpc.thirdweb.com",
    "https://rpc.katana.network",
]

TOPICS = {
    "swap":    "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
    "burn":    "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c",
    "collect": "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0",
    "mint":    "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde",
}

# ── RPC Client (simplified from WBTC version) ──

class RpcClient:
    def __init__(self, endpoints, rps=5):
        self.endpoints = endpoints
        self.idx = 0
        self.interval = 1.0 / rps
        self.last = 0
        self.calls = 0
        self.errors = 0

    @property
    def url(self):
        return self.endpoints[self.idx]

    def rotate(self):
        self.idx = (self.idx + 1) % len(self.endpoints)

    def call(self, method, params, retries=3):
        for attempt in range(retries):
            elapsed = time.time() - self.last
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last = time.time()
            self.calls += 1
            try:
                r = requests.post(self.url, json={"jsonrpc": "2.0", "id": self.calls,
                                  "method": method, "params": params}, timeout=15)
                data = r.json()
                if "error" in data:
                    raise ValueError(str(data["error"]))
                return data.get("result")
            except Exception as e:
                self.errors += 1
                if attempt < retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    if attempt >= 1:
                        self.rotate()
                else:
                    raise

# ── Decoders ──

def hex_int(h, signed=False):
    if not h or h == "0x": return 0
    v = int(h, 16)
    if signed and v >= 2**255: v -= 2**256
    return v

def decode_slot0(result):
    if not result or len(result) < 130: return None
    d = result[2:] if result.startswith("0x") else result
    sqrtP = int(d[0:64], 16)
    tick = int(d[64:128], 16)
    if tick > 2**23: tick -= 2**24
    Q96 = 2**96
    price_raw = (sqrtP / Q96) ** 2
    # token0=USDC(6), token1=ETH(18)
    # price_raw = ETH per USDC → invert for USDC per ETH
    price_t1_per_t0 = price_raw * (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))
    price_usdc_per_eth = 1.0 / price_t1_per_t0 if price_t1_per_t0 > 0 else 0
    return {"sqrtPriceX96": sqrtP, "tick": tick, "price": price_usdc_per_eth}

def decode_swap(log):
    d = log["data"][2:]
    amount0 = hex_int("0x" + d[0:64], signed=True)
    amount1 = hex_int("0x" + d[64:128], signed=True)
    sqrtP = hex_int("0x" + d[128:192])
    liquidity = hex_int("0x" + d[192:256])
    tick = hex_int("0x" + d[256:320], signed=True)
    Q96 = 2**96
    p_raw = (sqrtP / Q96) ** 2
    p_t1t0 = p_raw * (10 ** (TOKEN0_DECIMALS - TOKEN1_DECIMALS))
    price = 1.0 / p_t1t0 if p_t1t0 > 0 else 0
    return {"block": hex_int(log["blockNumber"]), "tx_hash": log["transactionHash"],
            "log_index": hex_int(log["logIndex"]), "amount0": amount0, "amount1": amount1,
            "sqrtPriceX96": sqrtP, "liquidity": liquidity, "tick": tick, "price": price}

def decode_burn(log):
    owner = "0x" + log["topics"][1][-40:]
    tl = hex_int(log["topics"][2], signed=True)
    tu = hex_int(log["topics"][3], signed=True)
    d = log["data"][2:]
    return {"block": hex_int(log["blockNumber"]), "tx_hash": log["transactionHash"],
            "log_index": hex_int(log["logIndex"]), "event": "Burn",
            "owner": owner.lower(), "tickLower": tl, "tickUpper": tu,
            "liquidity": hex_int("0x" + d[0:64]),
            "amount0": hex_int("0x" + d[64:128]), "amount1": hex_int("0x" + d[128:192])}

def decode_collect(log):
    owner = "0x" + log["topics"][1][-40:]
    tl = hex_int(log["topics"][2], signed=True)
    tu = hex_int(log["topics"][3], signed=True)
    d = log["data"][2:]
    return {"block": hex_int(log["blockNumber"]), "tx_hash": log["transactionHash"],
            "log_index": hex_int(log["logIndex"]), "event": "Collect",
            "owner": owner.lower(), "recipient": "0x" + d[0:64][-40:].lower(),
            "tickLower": tl, "tickUpper": tu,
            "amount0": hex_int("0x" + d[64:128]), "amount1": hex_int("0x" + d[128:192])}

def decode_mint(log):
    owner = "0x" + log["topics"][1][-40:]
    tl = hex_int(log["topics"][2], signed=True)
    tu = hex_int(log["topics"][3], signed=True)
    d = log["data"][2:]
    return {"block": hex_int(log["blockNumber"]), "tx_hash": log["transactionHash"],
            "log_index": hex_int(log["logIndex"]), "event": "Mint",
            "sender": "0x" + d[0:64][-40:].lower(), "owner": owner.lower(),
            "tickLower": tl, "tickUpper": tu, "liquidity": hex_int("0x" + d[64:128]),
            "amount0": hex_int("0x" + d[128:192]), "amount1": hex_int("0x" + d[192:256])}

# ── Collection ──

def load_checkpoint():
    return json.loads(CHECKPOINT_FILE.read_text()) if CHECKPOINT_FILE.exists() else {}

def save_checkpoint(cp):
    CHECKPOINT_FILE.write_text(json.dumps(cp, indent=2))

def collect_events(rpc, cp, name, topic, address, out_file, decoder, cp_key, fields):
    last = cp.get(cp_key, START_BLOCK)
    total = END_BLOCK - last
    print(f"\n📡 {name}: {total:,} blocks to scan")
    exists = out_file.exists() and last > START_BLOCK
    count = 0
    with open(out_file, "a" if exists else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists: w.writeheader()
        fb = last
        chunk = LOG_CHUNK_SIZE
        while fb < END_BLOCK:
            tb = min(fb + chunk - 1, END_BLOCK)
            try:
                logs = rpc.call("eth_getLogs", [{"address": address, "fromBlock": hex(fb),
                                                  "toBlock": hex(tb), "topics": [topic]}])
                if logs:
                    for log in logs:
                        try:
                            w.writerow(decoder(log))
                            count += 1
                        except: pass
                    f.flush()
                cp[cp_key] = tb + 1
                pct = (tb - START_BLOCK) / (END_BLOCK - START_BLOCK) * 100
                if count % 2000 < 50 or tb >= END_BLOCK:
                    print(f"  {pct:.0f}% block {tb:,} — {count:,} events")
                    save_checkpoint(cp)
                fb = tb + 1
                chunk = LOG_CHUNK_SIZE
            except ValueError:
                chunk = max(1000, chunk // 2)
            except Exception as e:
                print(f"  ❌ {e}")
                time.sleep(3)
                rpc.rotate()
    save_checkpoint(cp)
    print(f"  ✅ {name}: {count:,} events → {out_file}")

def main():
    print("=" * 60)
    print("USDC-ETH Pool Data Collection (Katana)")
    print(f"Pool:   {POOL}")
    print(f"Omnis:  {OMNIS_VAULT}")
    print(f"Blocks: {START_BLOCK:,} → {END_BLOCK:,} ({END_BLOCK-START_BLOCK:,})")
    print("=" * 60)

    rpc = RpcClient(RPC_ENDPOINTS)
    cp = load_checkpoint()

    tip = rpc.call("eth_blockNumber", [])
    print(f"✅ Connected (tip: {hex_int(tip):,})")

    # 1. Price series from swaps
    # (collect swaps first, then build price series)

    # 2. Swaps
    collect_events(rpc, cp, "Swaps", TOPICS["swap"], POOL,
                   OUTPUT_DIR / "swaps.csv", decode_swap, "swap_last",
                   ["block","tx_hash","log_index","amount0","amount1","sqrtPriceX96","liquidity","tick","price"])

    # 3. Burns
    collect_events(rpc, cp, "Burns", TOPICS["burn"], POOL,
                   OUTPUT_DIR / "burns.csv", decode_burn, "burn_last",
                   ["block","tx_hash","log_index","event","owner","tickLower","tickUpper","liquidity","amount0","amount1"])

    # 4. Collects
    collect_events(rpc, cp, "Collects", TOPICS["collect"], POOL,
                   OUTPUT_DIR / "collects.csv", decode_collect, "collect_last",
                   ["block","tx_hash","log_index","event","owner","recipient","tickLower","tickUpper","amount0","amount1"])

    # 5. Mints
    collect_events(rpc, cp, "Mints", TOPICS["mint"], POOL,
                   OUTPUT_DIR / "mints.csv", decode_mint, "mint_last",
                   ["block","tx_hash","log_index","event","sender","owner","tickLower","tickUpper","liquidity","amount0","amount1"])

    # 6. Build price series from swaps
    print("\n📊 Building price series from swap data...")
    swaps = []
    with open(OUTPUT_DIR / "swaps.csv") as f:
        for row in csv.DictReader(f):
            swaps.append((int(row["block"]), int(row["tick"]), float(row["price"])))
    swaps.sort()

    prices = {}
    si = 0
    for target in range(START_BLOCK, END_BLOCK + 1, PRICE_SAMPLE_INTERVAL):
        while si < len(swaps) - 1 and swaps[si + 1][0] <= target:
            si += 1
        if si < len(swaps) and swaps[si][0] <= target:
            prices[target] = swaps[si]

    with open(OUTPUT_DIR / "price_series.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["block", "sqrtPriceX96", "tick", "price"])
        for b in sorted(prices.keys()):
            _, tick, price = prices[b]
            w.writerow([b, "", tick, f"{price:.2f}"])

    print(f"  ✅ price_series.csv: {len(prices)} rows")
    if prices:
        first_b = min(prices.keys())
        last_b = max(prices.keys())
        print(f"     ${prices[first_b][2]:,.2f} → ${prices[last_b][2]:,.2f}")

    # Summary
    print("\n" + "=" * 60)
    print(f"✅ Done! RPC calls: {rpc.calls:,}, errors: {rpc.errors}")
    for f in sorted(OUTPUT_DIR.glob("*.csv")):
        lines = sum(1 for _ in open(f)) - 1
        print(f"   {f.name}: {lines:,} rows ({f.stat().st_size/1024:.0f} KB)")
    print("=" * 60)

if __name__ == "__main__":
    main()
