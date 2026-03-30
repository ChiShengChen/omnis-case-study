#!/usr/bin/env python3
"""
Financial Astrology LP Strategy
=================================
Western financial astrology-driven CLAMM range management.

Planetary signals → LP parameters:
  1. Moon Phase      → Base width (Full=narrow/active, New=wide/passive)
  2. Mercury Retro   → Override to wide + long cooldown (confusion period)
  3. Mars Aspects     → Volatility modifier (square/opposition = wider)
  4. Jupiter Aspects  → Opportunity modifier (trine/sextile = narrower)
  5. Saturn Transit   → Risk modifier (conjunction = very wide)

No external ephemeris needed — uses simplified Keplerian orbital mechanics.
"""

import csv, math, json, os, sys
import numpy as np
from pathlib import Path
from monte_carlo import (
    load_pool_data, block_bootstrap, tick_to_price, price_to_tick, align,
    v3_amounts, v3_liquidity, POOL_FEE
)

BASE_DIR = Path(__file__).parent

# ─── Simplified Planetary Calculations ───────────────────────────────

# J2000.0 epoch = 2000-01-01 12:00 UTC = Unix timestamp 946728000
J2000_UNIX = 946728000.0

# Mean orbital elements at J2000 (simplified)
# [period_days, lon_at_j2000_deg, daily_motion_deg]
PLANETS = {
    "mercury":  {"period": 87.969,   "lon0": 252.25,  "daily": 4.0923},
    "venus":    {"period": 224.701,  "lon0": 181.98,  "daily": 1.6021},
    "mars":     {"period": 686.971,  "lon0": 355.45,  "daily": 0.5240},
    "jupiter":  {"period": 4332.59,  "lon0": 34.40,   "daily": 0.0831},
    "saturn":   {"period": 10759.22, "lon0": 49.94,   "daily": 0.0335},
    "sun":      {"period": 365.256,  "lon0": 280.46,  "daily": 0.9856},
    "moon":     {"period": 27.322,   "lon0": 218.32,  "daily": 13.1764},
}

ZODIAC = [
    "Aries", "Taurus", "Gemini", "Cancer",
    "Leo", "Virgo", "Libra", "Scorpio",
    "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

# Zodiac element mapping
ZODIAC_ELEMENT = {
    "Aries": "fire", "Leo": "fire", "Sagittarius": "fire",
    "Taurus": "earth", "Virgo": "earth", "Capricorn": "earth",
    "Gemini": "air", "Libra": "air", "Aquarius": "air",
    "Cancer": "water", "Scorpio": "water", "Pisces": "water",
}


def planet_longitude(planet, unix_ts):
    """Approximate ecliptic longitude of a planet at given time."""
    p = PLANETS[planet]
    days_since_j2000 = (unix_ts - J2000_UNIX) / 86400.0
    lon = (p["lon0"] + p["daily"] * days_since_j2000) % 360
    return lon


def get_zodiac_sign(longitude):
    """Get zodiac sign from ecliptic longitude."""
    idx = int(longitude / 30) % 12
    return ZODIAC[idx]


def moon_phase(unix_ts):
    """
    Moon phase as 0-1 (0=new, 0.5=full).
    Uses synodic period = 29.53059 days.
    Known new moon: 2000-01-06 18:14 UTC = 946922040
    """
    SYNODIC = 29.53059
    REF_NEW_MOON = 946922040.0
    days = (unix_ts - REF_NEW_MOON) / 86400.0
    phase = (days % SYNODIC) / SYNODIC
    return phase


def is_mercury_retrograde(unix_ts):
    """
    Approximate Mercury retrograde periods.
    Mercury retrogrades ~3x/year for ~21 days.
    Simplified: retrograde when Mercury is within 18° behind the Sun
    (inferior conjunction approach).
    """
    sun_lon = planet_longitude("sun", unix_ts)
    merc_lon = planet_longitude("mercury", unix_ts)
    # Angular difference (Mercury relative to Sun)
    diff = (merc_lon - sun_lon + 360) % 360
    # Mercury is retrograde-ish when it's close to inferior conjunction
    # (within ~28° either side, but strongest within 18°)
    return diff > 342 or diff < 18  # ~36° window around inferior conjunction


def aspect_angle(lon1, lon2):
    """Angular separation between two longitudes."""
    diff = abs(lon1 - lon2)
    if diff > 180:
        diff = 360 - diff
    return diff


def get_aspects(unix_ts):
    """
    Calculate major planetary aspects at given time.
    Returns list of (planet1, planet2, aspect_name, orb, strength).
    """
    ASPECT_DEFS = {
        "conjunction": (0, 8),    # angle, max orb
        "opposition": (180, 8),
        "trine": (120, 6),
        "square": (90, 6),
        "sextile": (60, 4),
    }

    planets = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]
    lons = {p: planet_longitude(p, unix_ts) for p in planets}

    aspects = []
    for i, p1 in enumerate(planets):
        for p2 in planets[i+1:]:
            angle = aspect_angle(lons[p1], lons[p2])
            for asp_name, (target, max_orb) in ASPECT_DEFS.items():
                orb = abs(angle - target)
                if orb <= max_orb:
                    strength = 1 - (orb / max_orb)  # 1=exact, 0=at orb limit
                    aspects.append((p1, p2, asp_name, round(orb, 1), round(strength, 2)))

    return aspects


def astro_reading(unix_ts, price):
    """
    Complete astrological reading for LP decision.

    Returns dict with:
      width_score:  -2 (very wide) to +2 (very narrow)
      trend_score:  -1 (bearish) to +1 (bullish)
      cooldown_score: 0 (short) to 2 (very long)
      signals: list of active signals
    """
    signals = []
    width_score = 0.0
    trend_score = 0.0
    cooldown_score = 0.0

    # 1. Moon Phase
    phase = moon_phase(unix_ts)
    if 0.45 <= phase <= 0.55:  # Full moon ±2 days
        signals.append(("Full Moon", "narrow", "+1 width"))
        width_score += 1.0
    elif phase <= 0.05 or phase >= 0.95:  # New moon ±1.5 days
        signals.append(("New Moon", "wide", "-1 width"))
        width_score -= 1.0
    elif 0.2 <= phase <= 0.3:  # First quarter
        signals.append(("First Quarter", "slightly narrow", "+0.5 width"))
        width_score += 0.5
        trend_score += 0.3  # growth phase
    elif 0.7 <= phase <= 0.8:  # Last quarter
        signals.append(("Last Quarter", "slightly wide", "-0.5 width"))
        width_score -= 0.5
        trend_score -= 0.3  # decline phase

    # 2. Mercury Retrograde
    if is_mercury_retrograde(unix_ts):
        signals.append(("Mercury Retrograde", "WIDE + long cooldown", "-2 width, +2 cooldown"))
        width_score -= 2.0
        cooldown_score += 2.0

    # 3. Planetary Aspects
    aspects = get_aspects(unix_ts)
    for p1, p2, asp, orb, strength in aspects:
        # Mars square/opposition = volatility → wider
        if "mars" in (p1, p2) and asp in ("square", "opposition"):
            signals.append((f"Mars {asp} {p1 if p2=='mars' else p2}", "volatile", f"-{strength:.1f} width"))
            width_score -= strength
            cooldown_score += strength * 0.5

        # Jupiter trine/sextile = opportunity → narrower
        if "jupiter" in (p1, p2) and asp in ("trine", "sextile"):
            signals.append((f"Jupiter {asp} {p1 if p2=='jupiter' else p2}", "favorable", f"+{strength:.1f} width"))
            width_score += strength
            trend_score += strength * 0.3

        # Saturn conjunction/square = restriction → wider
        if "saturn" in (p1, p2) and asp in ("conjunction", "square"):
            signals.append((f"Saturn {asp} {p1 if p2=='saturn' else p2}", "restrictive", f"-{strength:.1f} width"))
            width_score -= strength
            cooldown_score += strength

        # Venus trine = value/stability → slightly narrower
        if "venus" in (p1, p2) and asp in ("trine", "conjunction"):
            other = p1 if p2 == "venus" else p2
            if other in ("jupiter", "sun"):
                signals.append((f"Venus {asp} {other}", "stable", f"+{strength*0.5:.1f} width"))
                width_score += strength * 0.5

        # Sun-Moon aspects affect trend
        if set((p1, p2)) == {"sun", "moon"}:
            if asp == "trine":
                trend_score += strength * 0.5
            elif asp == "square":
                trend_score -= strength * 0.3

    # 4. Moon's zodiac sign
    moon_lon = planet_longitude("moon", unix_ts)
    moon_sign = get_zodiac_sign(moon_lon)
    moon_elem = ZODIAC_ELEMENT[moon_sign]

    if moon_elem == "fire":
        signals.append((f"Moon in {moon_sign} (fire)", "active", "+0.3 width"))
        width_score += 0.3
        trend_score += 0.2
    elif moon_elem == "earth":
        signals.append((f"Moon in {moon_sign} (earth)", "stable", "+0.2 width"))
        width_score += 0.2
    elif moon_elem == "water":
        signals.append((f"Moon in {moon_sign} (water)", "emotional", "-0.3 width"))
        width_score -= 0.3
    elif moon_elem == "air":
        signals.append((f"Moon in {moon_sign} (air)", "communicative", "neutral"))

    # Clamp scores
    width_score = max(-3, min(3, width_score))
    trend_score = max(-1, min(1, trend_score))
    cooldown_score = max(0, min(3, cooldown_score))

    return {
        "width_score": round(width_score, 2),
        "trend_score": round(trend_score, 2),
        "cooldown_score": round(cooldown_score, 2),
        "signals": signals,
        "moon_phase": round(phase, 3),
        "moon_sign": moon_sign,
        "mercury_retro": is_mercury_retrograde(unix_ts),
        "n_aspects": len(aspects),
    }


def astro_to_params(reading):
    """
    Convert astrological reading to LP parameters.

    width_score [-3, +3] → width [±3%, ±20%]
    trend_score [-1, +1] → asymmetric shift
    cooldown_score [0, 3] → cooldown [3000, 20000]
    """
    # Width: score +3 = ±3% (very narrow), score -3 = ±20% (very wide)
    # Linear interpolation
    w_score = reading["width_score"]
    width_pct = 0.115 - w_score * 0.028  # center ±11.5%, range ±3% to ±20%
    width_pct = max(0.03, min(0.20, width_pct))

    # Trend shift
    t_score = reading["trend_score"]
    if t_score > 0.2:
        shift_up, shift_down = 1.0 + t_score * 0.4, 1.0 - t_score * 0.4
    elif t_score < -0.2:
        shift_up, shift_down = 1.0 + t_score * 0.4, 1.0 - t_score * 0.4
    else:
        shift_up, shift_down = 1.0, 1.0

    # Cooldown
    cd_score = reading["cooldown_score"]
    cooldown = int(3000 + cd_score * 5667)  # 3000 to 20000
    cooldown = max(3000, min(20000, cooldown))

    return {
        "width_pct": round(width_pct, 4),
        "shift_up": round(max(0.5, shift_up), 3),
        "shift_down": round(max(0.5, shift_down), 3),
        "cooldown": cooldown,
    }


# ─── Strategy Simulation ────────────────────────────────────────────

def run_astro(prices, swap_tick_agg, cfg, init_usd, params):
    """Run financial astrology strategy. MC-compatible."""
    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    base_ts = params.get("base_ts", 1765951769)
    base_block = params.get("base_block", prices[0][0])

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    position = None
    fee_usdc = 0.0
    n_rb = 0
    last_rb_block = 0
    total_fee_usdc = 0.0
    current_cooldown = 5000

    for block, tick, price in prices:
        timestamp = base_ts + (block - base_block)

        should_rb = False
        if position is None:
            should_rb = True
        elif block - last_rb_block >= current_cooldown:
            pa, pb = position[3], position[4]
            if price < pa or price > pb:
                should_rb = True
            elif pb > pa:
                pct = (price - pa) / (pb - pa)
                if pct < 0.05 or pct > 0.95:
                    should_rb = True

        if should_rb:
            if position:
                b, u = v3_amounts(position[2], price, position[3], position[4])
                base_bal += b
                usdc_bal += u
                usdc_bal += fee_usdc
                total_fee_usdc += fee_usdc
                if n_rb > 0:
                    total_val = base_bal * price + usdc_bal
                    usdc_bal -= total_val * 0.5 * 0.0015
            fee_usdc = 0.0

            # Astrological reading
            reading = astro_reading(timestamp, price)
            ap = astro_to_params(reading)
            current_cooldown = ap["cooldown"]

            wh = price * ap["width_pct"]
            lo = price - wh * ap["shift_down"]
            hi = price + wh * ap["shift_up"]

            tl = align(price_to_tick(max(0.01, lo), t0, t1, inv), ts)
            tu = align(price_to_tick(hi, t0, t1, inv), ts)
            pa = tick_to_price(tl, t0, t1, inv)
            pb = tick_to_price(tu, t0, t1, inv)
            if pa > pb: pa, pb = pb, pa

            L = v3_liquidity(base_bal, usdc_bal, price, pa, pb)
            if L > 0:
                used_b, used_u = v3_amounts(L, price, pa, pb)
                base_bal -= used_b
                usdc_bal -= used_u
            position = (tl, tu, L, pa, pb)
            last_rb_block = block
            n_rb += 1

        if position and block in swap_tick_agg:
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                if min(position[0], position[1]) <= tick_bucket < max(position[0], position[1]) and position[2] > 0:
                    fee_usdc += vol_u * POOL_FEE * fee_share

    p_end = prices[-1][2]
    if position:
        pos_b, pos_u = v3_amounts(position[2], p_end, position[3], position[4])
    else:
        pos_b, pos_u = 0, 0
    final_val = (pos_b + base_bal) * p_end + pos_u + usdc_bal + fee_usdc
    total_fee_usdc += fee_usdc

    vault_return = (final_val - init_usd) / init_usd
    hodl_return = ((init_usd / 2 / p0) * p_end + init_usd / 2 - init_usd) / init_usd

    return {
        "alpha": vault_return - hodl_return,
        "vault_return": vault_return,
        "hodl_return": hodl_return,
        "fee_bps": total_fee_usdc / init_usd * 10000,
        "rebalances": n_rb,
    }


def simulate_astro_full(pool_key):
    """Full simulation with astrological log."""
    prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    base_ts = 1765951769 if pool_key == "wbtc-usdc" else 1765951769 + (23693484 - 19208958)
    base_block = 19208958 if pool_key == "wbtc-usdc" else 23693484

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2

    position = None
    fee_usdc = 0.0
    n_rb = 0
    last_rb_block = 0
    total_fee_usdc = 0.0
    current_cooldown = 5000
    astro_log = []

    for block, tick, price in prices:
        timestamp = base_ts + (block - base_block)

        should_rb = False
        if position is None:
            should_rb = True
        elif block - last_rb_block >= current_cooldown:
            pa, pb = position[3], position[4]
            if price < pa or price > pb:
                should_rb = True
            elif pb > pa:
                pct = (price - pa) / (pb - pa)
                if pct < 0.05 or pct > 0.95:
                    should_rb = True

        if should_rb:
            if position:
                b, u = v3_amounts(position[2], price, position[3], position[4])
                base_bal += b
                usdc_bal += u
                usdc_bal += fee_usdc
                total_fee_usdc += fee_usdc
                if n_rb > 0:
                    total_val = base_bal * price + usdc_bal
                    usdc_bal -= total_val * 0.5 * 0.0015
            fee_usdc = 0.0

            reading = astro_reading(timestamp, price)
            ap = astro_to_params(reading)
            current_cooldown = ap["cooldown"]

            import datetime
            dt = datetime.datetime.utcfromtimestamp(timestamp)
            astro_log.append({
                "block": block,
                "date": dt.strftime("%Y-%m-%d %H:%M"),
                "price": round(price, 2),
                "moon_phase": f"{reading['moon_phase']:.2f}",
                "moon_sign": reading["moon_sign"],
                "mercury_retro": reading["mercury_retro"],
                "width_score": reading["width_score"],
                "trend_score": reading["trend_score"],
                "width": f"±{ap['width_pct']*100:.1f}%",
                "cooldown": ap["cooldown"],
                "signals": [s[0] for s in reading["signals"][:4]],
            })

            wh = price * ap["width_pct"]
            lo = price - wh * ap["shift_down"]
            hi = price + wh * ap["shift_up"]

            tl = align(price_to_tick(max(0.01, lo), t0, t1, inv), ts)
            tu = align(price_to_tick(hi, t0, t1, inv), ts)
            pa = tick_to_price(tl, t0, t1, inv)
            pb = tick_to_price(tu, t0, t1, inv)
            if pa > pb: pa, pb = pb, pa

            L = v3_liquidity(base_bal, usdc_bal, price, pa, pb)
            if L > 0:
                used_b, used_u = v3_amounts(L, price, pa, pb)
                base_bal -= used_b
                usdc_bal -= used_u
            position = (tl, tu, L, pa, pb)
            last_rb_block = block
            n_rb += 1

        if position and block in swap_tick_agg:
            for tick_bucket, vol_u in swap_tick_agg[block].items():
                if min(position[0], position[1]) <= tick_bucket < max(position[0], position[1]) and position[2] > 0:
                    fee_usdc += vol_u * POOL_FEE * fee_share

    p_end = prices[-1][2]
    if position:
        pos_b, pos_u = v3_amounts(position[2], p_end, position[3], position[4])
    else:
        pos_b, pos_u = 0, 0
    final_val = (pos_b + base_bal) * p_end + pos_u + usdc_bal + fee_usdc
    total_fee_usdc += fee_usdc

    vault_return = (final_val - init_usd) / init_usd
    hodl_return = ((init_usd / 2 / p0) * p_end + init_usd / 2 - init_usd) / init_usd

    return {
        "alpha": vault_return - hodl_return,
        "vault_return": vault_return,
        "hodl_return": hodl_return,
        "fee_bps": total_fee_usdc / init_usd * 10000,
        "rebalances": n_rb,
        "astro_log": astro_log,
    }


# ─── Dense CSV output for dashboard ─────────────────────────────────

def simulate_astro_dense(pool_key, strategy_name):
    """Output dense CSV rows for dashboard integration."""
    prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)

    t0, t1, inv = cfg["t0_dec"], cfg["t1_dec"], cfg["invert"]
    ts_spacing = cfg["tick_spacing"]
    fee_share = cfg["fee_share"]

    base_ts = 1765951769 if pool_key == "wbtc-usdc" else 1765951769 + (23693484 - 19208958)
    base_block = 19208958 if pool_key == "wbtc-usdc" else 23693484

    p0 = prices[0][2]
    base_bal = (init_usd / 2) / p0
    usdc_bal = init_usd / 2
    FAKE_SUPPLY = 1_000_000_000

    position = None
    fee_usdc = 0.0
    si = 0
    n_rb = 0
    last_rb_block = 0
    current_cooldown = 5000

    # Rebuild raw swaps for sequential scanning
    data_dir = cfg.get("data_dir", BASE_DIR / ("data" if pool_key == "wbtc-usdc" else "data_eth"))
    if not hasattr(data_dir, 'exists'):
        from pathlib import Path as P
        data_dir = P(data_dir)
    swaps = []
    with open(data_dir / "swaps.csv") as f:
        for row in csv.DictReader(f):
            if inv:
                vol_usdc = abs(int(row["amount0"])) / (10**t0)
            else:
                vol_usdc = abs(int(row["amount1"])) / (10**t1)
            swaps.append((int(row["block"]), int(row["tick"]), vol_usdc))
    swaps.sort()

    output_rows = []
    fee_events = []

    for block, tick, price in prices:
        timestamp = base_ts + (block - base_block)

        should_rb = False
        if position is None:
            should_rb = True
        elif block - last_rb_block >= current_cooldown:
            pa, pb = position[3], position[4]
            if price < pa or price > pb:
                should_rb = True
            elif pb > pa:
                pct = (price - pa) / (pb - pa)
                if pct < 0.05 or pct > 0.95:
                    should_rb = True

        if should_rb:
            if position:
                b, u = v3_amounts(position[2], price, position[3], position[4])
                base_bal += b
                usdc_bal += u
                usdc_bal += fee_usdc
                if n_rb > 0 and fee_usdc > 0:
                    fee_events.append({
                        "block": block,
                        "fee0": fee_usdc if inv else 0,
                        "fee1": 0 if inv else fee_usdc,
                    })
                if n_rb > 0:
                    total_val = base_bal * price + usdc_bal
                    usdc_bal -= total_val * 0.5 * 0.0015
            fee_usdc = 0.0

            reading = astro_reading(timestamp, price)
            ap = astro_to_params(reading)
            current_cooldown = ap["cooldown"]

            wh = price * ap["width_pct"]
            lo = price - wh * ap["shift_down"]
            hi = price + wh * ap["shift_up"]

            tl = align(price_to_tick(max(0.01, lo), t0, t1, inv), ts_spacing)
            tu = align(price_to_tick(hi, t0, t1, inv), ts_spacing)
            pa = tick_to_price(tl, t0, t1, inv)
            pb = tick_to_price(tu, t0, t1, inv)
            if pa > pb: pa, pb = pb, pa

            L = v3_liquidity(base_bal, usdc_bal, price, pa, pb)
            if L > 0:
                used_b, used_u = v3_amounts(L, price, pa, pb)
                base_bal -= used_b
                usdc_bal -= used_u
            position = (tl, tu, L, pa, pb)
            last_rb_block = block
            n_rb += 1

        # Fees (sequential swap scan)
        if position:
            tl_p, tu_p = position[0], position[1]
            L_p = position[2]
            while si < len(swaps) and swaps[si][0] <= block:
                _, stk, vol_u = swaps[si]
                if min(tl_p, tu_p) <= stk < max(tl_p, tu_p) and L_p > 0:
                    fee_usdc += vol_u * POOL_FEE * fee_share
                si += 1

        if position:
            pos_b, pos_u = v3_amounts(position[2], price, position[3], position[4])
        else:
            pos_b, pos_u = 0, 0

        total_base_now = pos_b + base_bal
        total_usdc_now = pos_u + usdc_bal + fee_usdc
        ts_est = base_ts + (block - base_block)

        if inv:
            output_rows.append({"block": block, "timestamp": ts_est,
                "amount0": total_usdc_now, "amount1": total_base_now,
                "total_supply": FAKE_SUPPLY, "price": 1.0/price if price > 0 else 0, "tick": tick})
        else:
            output_rows.append({"block": block, "timestamp": ts_est,
                "amount0": total_base_now, "amount1": total_usdc_now,
                "total_supply": FAKE_SUPPLY, "price": price, "tick": tick})

    print(f"  {strategy_name} ({pool_key}): {len(output_rows)} rows, {n_rb} rebalances, {len(fee_events)} fee events")
    return output_rows, fee_events


# ─── Main ────────────────────────────────────────────────────────────

def main():
    os.makedirs(BASE_DIR / "charts", exist_ok=True)
    results = {}

    for pool_key in ["wbtc-usdc", "usdc-eth"]:
        pool_label = pool_key.upper()
        print(f"\n{'='*60}")
        print(f"  Financial Astrology LP — {pool_label}")
        print(f"{'='*60}")

        r = simulate_astro_full(pool_key)
        print(f"\n  Baseline:")
        print(f"    Alpha:      {r['alpha']*100:+.2f}%")
        print(f"    Vault Return: {r['vault_return']*100:+.2f}%")
        print(f"    Fee:        {r['fee_bps']:.0f} bps")
        print(f"    Rebalances: {r['rebalances']}")

        print(f"\n  Astro Log:")
        print(f"    {'Date':>16} {'Price':>10} {'Moon':>6} {'Sign':>12} {'MercRx':>7} {'Width':>8} {'Signals'}")
        for a in r["astro_log"][:15]:
            sigs = ", ".join(a["signals"][:3]) if a["signals"] else "—"
            print(f"    {a['date']:>16} {a['price']:>10} {a['moon_phase']:>6} {a['moon_sign']:>12} {'YES' if a['mercury_retro'] else 'no':>7} {a['width']:>8} {sigs}")

        # Bootstrap
        print(f"\n  Block Bootstrap (500 paths)...")
        prices, swap_agg, swap_tick_agg, cfg, init_usd = load_pool_data(pool_key)
        paths = block_bootstrap(prices, swap_tick_agg, cfg, block_hours=4, n_paths=500)

        boot_alphas = []
        for i, (sp, sa, sta) in enumerate(paths):
            if len(sp) < 10: continue
            br = run_astro(sp, sta, cfg, init_usd, {})
            boot_alphas.append(br["alpha"])
            if (i+1) % 200 == 0:
                print(f"    {i+1}/500...")
        boot_alphas = np.array(boot_alphas)

        bp = np.mean(boot_alphas > 0) * 100
        bmed = np.median(boot_alphas) * 100

        print(f"\n  Bootstrap: P(α>0)={bp:.1f}%, Median={bmed:+.2f}%")

        results[pool_key] = {
            "baseline_alpha": round(r["alpha"] * 100, 2),
            "vault_return": round(r["vault_return"] * 100, 2),
            "fee_bps": round(r["fee_bps"], 1),
            "rebalances": r["rebalances"],
            "astro_log": r["astro_log"],
            "bootstrap": {
                "p_positive": round(bp, 1),
                "median": round(bmed, 2),
                "pct5": round(np.percentile(boot_alphas, 5) * 100, 2),
                "pct95": round(np.percentile(boot_alphas, 95) * 100, 2),
            },
        }

    with open(BASE_DIR / "astro_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print("  Done! → astro_results.json")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
