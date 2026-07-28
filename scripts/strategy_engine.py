#!/usr/bin/env python3
"""
NEXYROTH Multi-Strategy Signal Engine v1.0
==========================================
Combines 5 proven strategies into a unified scoring system.
Each strategy votes LONG/SHORT/NEUTRAL with a confidence weight.
Final signal fires only when combined score exceeds threshold.

Strategies:
1. Funding Rate Arbitrage (weight: 30%) — Lowest risk, highest consistency
2. RSI Divergence (weight: 25%) — Mean reversion on oversold/overbought
3. VWAP Bounce/Reject (weight: 20%) — Institutional price level
4. EMA Crossover + Volume (weight: 15%) — Trend confirmation
5. Momentum Breakout (weight: 10%) — Breakout continuation

Position Sizing: Modified Kelly Criterion
Risk Management: Max 5% account risk per trade, 2x leverage cap
"""

import os
import sys
import json
import time
import requests
import numpy as np
import pandas as pd
import ta
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

BITUNIX_API = "https://fapi.bitunix.com"
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")
LOG_FILE = "/home/ubuntu/trading_sniper/strategy_engine.log"
SIGNALS_FILE = "/home/ubuntu/trading_sniper/data/signals_history.json"

WATCHLIST_FILE = "/home/ubuntu/trading_sniper/watchlist.json"

def load_ev_config():
    """Load EV tiers and avoid list from watchlist.json."""
    try:
        with open(WATCHLIST_FILE) as f:
            data = json.load(f)
        symbols = list(dict.fromkeys(
            data.get("priority_watchlist", []) +
            data.get("added_high_value", [])
        ))
        ev_boost = {}
        for tier_name, tier_data in data.get("ev_tiers", {}).items():
            for sym in tier_data.get("symbols", []):
                ev_boost[sym] = tier_data.get("ev_boost", 0.0)
        avoid = set(data.get("avoid_symbols", []))
        return symbols, ev_boost, avoid
    except:
        return ([
            "BTCUSDT", "ETHUSDT", "XRPUSDT", "DOGEUSDT",
            "HYPEUSDT", "AGLDUSDT", "FARTCOINUSDT", "PIPPINUSDT", "JUPUSDT",
            "PEPEUSDT", "BNBUSDT", "LINKUSDT", "AVAXUSDT",
            "WIFUSDT", "BONKUSDT", "AAVEUSDT", "APTUSDT",
            "XAUTUSDT", "RIVERUSDT", "LTCUSDT", "NEARUSDT",
        ], {}, set())

# Watchlist — loaded dynamically from watchlist.json
WATCHLIST, _EV_BOOST_DEFAULTS, _AVOID_DEFAULTS = load_ev_config()

# Strategy weights (must sum to 1.0)
WEIGHTS = {
    "funding_rate": 0.30,
    "rsi_divergence": 0.25,
    "vwap": 0.20,
    "ema_crossover": 0.15,
    "momentum": 0.10,
}

# Signal threshold — only fire when combined score >= this
SIGNAL_THRESHOLD = 0.45  # 45% confidence minimum (aggressive for small accounts)
SCALP_THRESHOLD = 0.35   # 35% for scalp-mode alerts (informational only)

# Risk parameters
MAX_RISK_PCT = 0.05       # 5% of account per trade
MAX_LEVERAGE = 2          # Never exceed 2x
MIN_RR_RATIO = 1.5        # Minimum risk:reward ratio

# ═══════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def fetch_klines(symbol, interval="15m", limit=100):
    """Fetch OHLCV candles from Bitunix."""
    try:
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/market/kline",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        data = r.json().get("data", [])
        if not data:
            return None
        df = pd.DataFrame(data)
        # Bitunix kline format: {open, high, low, close, quoteVol, baseVol, time}
        # Rename to standard OHLCV columns
        rename_map = {"quoteVol": "volume", "baseVol": "base_volume", "time": "timestamp"}
        df = df.rename(columns=rename_map)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
            df = df.sort_values("timestamp").reset_index(drop=True)
        return df
    except Exception as e:
        log(f"  Kline fetch error {symbol}: {e}")
        return None

def fetch_funding_rate(symbol):
    """Get current funding rate."""
    try:
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/market/funding_rate",
            params={"symbol": symbol},
            timeout=5,
        )
        return float(r.json().get("data", {}).get("fundingRate", 0))
    except:
        return 0.0

def fetch_ticker(symbol):
    """Get current ticker data."""
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/tickers", timeout=10)
        tickers = {t["symbol"]: t for t in r.json().get("data", [])}
        return tickers.get(symbol)
    except:
        return None

# ═══════════════════════════════════════════════════════════════
# STRATEGY 1: FUNDING RATE ARBITRAGE
# ═══════════════════════════════════════════════════════════════

def strategy_funding_rate(symbol, funding_rate):
    """
    Negative FR = shorts pay longs → LONG signal
    Positive FR = longs pay shorts → SHORT signal (if extreme)
    Magnitude determines confidence.
    """
    fr_pct = funding_rate * 100  # Convert to percentage

    if fr_pct < -0.5:
        # Strong negative — very confident LONG
        confidence = min(1.0, abs(fr_pct) / 2.0)
        return ("LONG", confidence, f"FR={fr_pct:+.4f}% (shorts paying longs)")
    elif fr_pct < -0.1:
        # Mild negative — moderate LONG
        confidence = abs(fr_pct) / 1.0
        return ("LONG", confidence, f"FR={fr_pct:+.4f}% (mild neg)")
    elif fr_pct > 1.5:
        # Extreme positive — SHORT signal (longs overextended)
        confidence = min(1.0, fr_pct / 3.0)
        return ("SHORT", confidence, f"FR={fr_pct:+.4f}% (longs overextended)")
    elif fr_pct > 0.5:
        # Moderate positive — mild SHORT
        confidence = fr_pct / 2.0
        return ("SHORT", confidence * 0.5, f"FR={fr_pct:+.4f}% (mild pos)")
    else:
        return ("NEUTRAL", 0.0, f"FR={fr_pct:+.4f}% (neutral)")

# ═══════════════════════════════════════════════════════════════
# STRATEGY 2: RSI DIVERGENCE
# ═══════════════════════════════════════════════════════════════

def strategy_rsi_divergence(df):
    """
    Bullish divergence: Price makes lower low, RSI makes higher low → LONG
    Bearish divergence: Price makes higher high, RSI makes lower high → SHORT
    Also: RSI < 25 = oversold (LONG), RSI > 75 = overbought (SHORT)
    """
    if df is None or len(df) < 30:
        return ("NEUTRAL", 0.0, "Insufficient data")

    rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    current_rsi = rsi.iloc[-1]

    # Simple oversold/overbought
    if current_rsi < 25:
        confidence = (25 - current_rsi) / 25
        return ("LONG", min(1.0, confidence * 1.5), f"RSI={current_rsi:.1f} OVERSOLD")
    elif current_rsi < 35:
        confidence = (35 - current_rsi) / 20
        return ("LONG", confidence * 0.6, f"RSI={current_rsi:.1f} near oversold")
    elif current_rsi > 75:
        confidence = (current_rsi - 75) / 25
        return ("SHORT", min(1.0, confidence * 1.5), f"RSI={current_rsi:.1f} OVERBOUGHT")
    elif current_rsi > 65:
        confidence = (current_rsi - 65) / 20
        return ("SHORT", confidence * 0.6, f"RSI={current_rsi:.1f} near overbought")

    # Check for divergence (last 20 candles)
    lookback = 20
    prices = df["close"].iloc[-lookback:].values
    rsi_vals = rsi.iloc[-lookback:].values

    # Find local lows for bullish divergence
    price_lows = []
    rsi_lows = []
    for i in range(2, len(prices) - 2):
        if prices[i] < prices[i-1] and prices[i] < prices[i-2] and prices[i] < prices[i+1] and prices[i] < prices[i+2]:
            price_lows.append((i, prices[i]))
            rsi_lows.append((i, rsi_vals[i]))

    if len(price_lows) >= 2:
        # Check if price made lower low but RSI made higher low
        if price_lows[-1][1] < price_lows[-2][1] and rsi_lows[-1][1] > rsi_lows[-2][1]:
            return ("LONG", 0.8, f"RSI BULLISH DIVERGENCE (RSI={current_rsi:.1f})")

    # Find local highs for bearish divergence
    price_highs = []
    rsi_highs = []
    for i in range(2, len(prices) - 2):
        if prices[i] > prices[i-1] and prices[i] > prices[i-2] and prices[i] > prices[i+1] and prices[i] > prices[i+2]:
            price_highs.append((i, prices[i]))
            rsi_highs.append((i, rsi_vals[i]))

    if len(price_highs) >= 2:
        if price_highs[-1][1] > price_highs[-2][1] and rsi_highs[-1][1] < rsi_highs[-2][1]:
            return ("SHORT", 0.8, f"RSI BEARISH DIVERGENCE (RSI={current_rsi:.1f})")

    return ("NEUTRAL", 0.0, f"RSI={current_rsi:.1f} (no signal)")

# ═══════════════════════════════════════════════════════════════
# STRATEGY 3: VWAP BOUNCE/REJECT
# ═══════════════════════════════════════════════════════════════

def strategy_vwap(df):
    """
    Price bounces off VWAP from above → LONG (support)
    Price rejects at VWAP from below → SHORT (resistance)
    Distance from VWAP indicates mean reversion potential.
    """
    if df is None or len(df) < 20:
        return ("NEUTRAL", 0.0, "Insufficient data")

    # Calculate VWAP
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum()
    vwap = cumulative_tp_vol / cumulative_vol

    current_price = df["close"].iloc[-1]
    current_vwap = vwap.iloc[-1]
    prev_price = df["close"].iloc[-2]

    if current_vwap == 0:
        return ("NEUTRAL", 0.0, "VWAP=0")

    # Distance from VWAP as percentage
    dist_pct = ((current_price - current_vwap) / current_vwap) * 100

    # Price crossed above VWAP (was below, now above) → LONG
    prev_vwap = vwap.iloc[-2]
    if prev_price < prev_vwap and current_price > current_vwap:
        confidence = min(1.0, 0.7 + abs(dist_pct) / 5)
        return ("LONG", confidence, f"VWAP CROSS UP (dist={dist_pct:+.2f}%)")

    # Price crossed below VWAP (was above, now below) → SHORT
    if prev_price > prev_vwap and current_price < current_vwap:
        confidence = min(1.0, 0.7 + abs(dist_pct) / 5)
        return ("SHORT", confidence, f"VWAP CROSS DOWN (dist={dist_pct:+.2f}%)")

    # Price far below VWAP → mean reversion LONG
    if dist_pct < -2.0:
        confidence = min(1.0, abs(dist_pct) / 5)
        return ("LONG", confidence, f"Below VWAP {dist_pct:.2f}% (mean reversion)")

    # Price far above VWAP → mean reversion SHORT
    if dist_pct > 2.0:
        confidence = min(1.0, dist_pct / 5)
        return ("SHORT", confidence, f"Above VWAP +{dist_pct:.2f}% (mean reversion)")

    return ("NEUTRAL", 0.0, f"VWAP dist={dist_pct:+.2f}% (neutral zone)")

# ═══════════════════════════════════════════════════════════════
# STRATEGY 4: EMA CROSSOVER + VOLUME
# ═══════════════════════════════════════════════════════════════

def strategy_ema_crossover(df):
    """
    9 EMA crosses above 21 EMA with volume spike → LONG
    9 EMA crosses below 21 EMA with volume spike → SHORT
    """
    if df is None or len(df) < 30:
        return ("NEUTRAL", 0.0, "Insufficient data")

    ema9 = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
    ema21 = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()

    # Current and previous EMA positions
    curr_9 = ema9.iloc[-1]
    curr_21 = ema21.iloc[-1]
    prev_9 = ema9.iloc[-2]
    prev_21 = ema21.iloc[-2]

    # Volume check — is current volume above 1.5x average?
    avg_vol = df["volume"].iloc[-20:].mean()
    curr_vol = df["volume"].iloc[-1]
    vol_spike = curr_vol > avg_vol * 1.5 if avg_vol > 0 else False

    # Bullish crossover: 9 EMA was below 21, now above
    if prev_9 <= prev_21 and curr_9 > curr_21:
        confidence = 0.8 if vol_spike else 0.5
        vol_str = "VOL CONFIRMED" if vol_spike else "low vol"
        return ("LONG", confidence, f"EMA9/21 GOLDEN CROSS ({vol_str})")

    # Bearish crossover: 9 EMA was above 21, now below
    if prev_9 >= prev_21 and curr_9 < curr_21:
        confidence = 0.8 if vol_spike else 0.5
        vol_str = "VOL CONFIRMED" if vol_spike else "low vol"
        return ("SHORT", confidence, f"EMA9/21 DEATH CROSS ({vol_str})")

    # Trend continuation — 9 above 21 = bullish trend
    if curr_9 > curr_21:
        gap_pct = ((curr_9 - curr_21) / curr_21) * 100
        if gap_pct > 0.5:
            return ("LONG", 0.3, f"EMA bullish trend (gap={gap_pct:.2f}%)")
    elif curr_9 < curr_21:
        gap_pct = ((curr_21 - curr_9) / curr_21) * 100
        if gap_pct > 0.5:
            return ("SHORT", 0.3, f"EMA bearish trend (gap={gap_pct:.2f}%)")

    return ("NEUTRAL", 0.0, "EMA flat/no crossover")

# ═══════════════════════════════════════════════════════════════
# STRATEGY 5: MOMENTUM BREAKOUT
# ═══════════════════════════════════════════════════════════════

def strategy_momentum(df, ticker_data):
    """
    Price breaks above 24h high with volume → LONG
    Price breaks below 24h low with volume → SHORT
    24h % change > 5% with volume = strong momentum.
    """
    if df is None or len(df) < 10:
        return ("NEUTRAL", 0.0, "Insufficient data")

    if not ticker_data:
        return ("NEUTRAL", 0.0, "No ticker data")

    try:
        price = float(ticker_data.get("lastPrice", 0))
        high_24h = float(ticker_data.get("high", 0))
        low_24h = float(ticker_data.get("low", 0))
        open_24h = float(ticker_data.get("open", 0))
    except:
        return ("NEUTRAL", 0.0, "Parse error")

    if open_24h == 0 or high_24h == 0:
        return ("NEUTRAL", 0.0, "Zero price data")

    pct_change = ((price - open_24h) / open_24h) * 100
    dist_from_high = ((high_24h - price) / high_24h) * 100
    dist_from_low = ((price - low_24h) / low_24h) * 100 if low_24h > 0 else 0

    # Strong upward momentum
    if pct_change > 8:
        confidence = min(1.0, pct_change / 15)
        return ("LONG", confidence, f"STRONG MOMENTUM +{pct_change:.1f}%")
    elif pct_change > 5 and dist_from_high < 1:
        confidence = 0.7
        return ("LONG", confidence, f"Near 24h high, momentum +{pct_change:.1f}%")

    # Strong downward momentum (potential short or avoid)
    if pct_change < -8:
        confidence = min(1.0, abs(pct_change) / 15)
        return ("SHORT", confidence, f"DUMP MOMENTUM {pct_change:.1f}%")

    # Near daily low — potential bounce (contrarian)
    if dist_from_low < 1.0 and pct_change < -3:
        return ("LONG", 0.3, f"Near daily low ({dist_from_low:.1f}% above)")

    return ("NEUTRAL", 0.0, f"24h={pct_change:+.1f}% (no breakout)")

# ═══════════════════════════════════════════════════════════════
# SIGNAL COMBINER — THE BRAIN
# ═══════════════════════════════════════════════════════════════

def combine_signals(strategies):
    """
    Combine all strategy signals into a final weighted score.
    Uses GROSS directional score (not net) — opposing signals don't cancel.
    RSI Divergence override: if RSI divergence fires at 70%+ confidence,
    it acts as a strong reversal signal that boosts the overall score.
    Returns: (direction, confidence, details)
    """
    long_score = 0.0
    short_score = 0.0
    long_count = 0
    short_count = 0
    details = []
    rsi_override = False
    rsi_direction = None

    for name, (direction, confidence, reason) in strategies.items():
        weight = WEIGHTS.get(name, 0)
        weighted = confidence * weight

        if direction == "LONG":
            long_score += weighted
            long_count += 1
        elif direction == "SHORT":
            short_score += weighted
            short_count += 1

        if confidence > 0:
            details.append(f"  {name}: {direction} ({confidence:.0%}) — {reason}")

        # RSI Divergence override — strong reversal signal
        if name == "rsi_divergence" and confidence >= 0.70:
            rsi_override = True
            rsi_direction = direction

    # RSI Divergence boost: if RSI divergence fires strongly and
    # at least one other strategy agrees, boost the score by 0.15
    if rsi_override:
        if rsi_direction == "LONG" and long_count >= 2:
            long_score += 0.15
            details.append(f"  [BOOST] RSI Divergence override +15%")
        elif rsi_direction == "SHORT" and short_count >= 2:
            short_score += 0.15
            details.append(f"  [BOOST] RSI Divergence override +15%")

    # Majority agreement bonus: if 3+ strategies agree, add 0.10
    if long_count >= 3:
        long_score += 0.10
        details.append(f"  [BOOST] Majority agreement ({long_count} strategies LONG) +10%")
    if short_count >= 3:
        short_score += 0.10
        details.append(f"  [BOOST] Majority agreement ({short_count} strategies SHORT) +10%")

    # Use gross score (dominant direction) — don't subtract opposing
    if long_score > short_score and long_score >= SIGNAL_THRESHOLD:
        return ("LONG", long_score, details)
    elif short_score > long_score and short_score >= SIGNAL_THRESHOLD:
        return ("SHORT", short_score, details)
    else:
        return ("NEUTRAL", max(long_score, short_score), details)

# ═══════════════════════════════════════════════════════════════
# POSITION SIZING (Modified Kelly Criterion)
# ═══════════════════════════════════════════════════════════════

def calculate_position(account_balance, confidence, current_price):
    """
    Kelly-inspired position sizing:
    - Higher confidence → larger position (up to MAX_RISK_PCT)
    - Always cap at 2x leverage
    - Never risk more than 5% of account
    """
    # Kelly fraction: f = (bp - q) / b
    # Simplified: risk_pct = confidence * MAX_RISK_PCT
    risk_pct = confidence * MAX_RISK_PCT
    risk_amount = account_balance * risk_pct

    # Position size at 2x leverage
    position_size = account_balance * MAX_LEVERAGE

    # Stop loss distance (2% for tight, 3% for wider)
    stop_pct = 0.02 if confidence > 0.7 else 0.03

    # Actual risk = position_size * stop_pct
    actual_risk = position_size * stop_pct

    # If actual risk exceeds our risk budget, reduce position
    if actual_risk > risk_amount:
        position_size = risk_amount / stop_pct

    # Take profit at MIN_RR_RATIO * stop distance
    tp_pct = stop_pct * MIN_RR_RATIO

    return {
        "position_size": round(position_size, 2),
        "leverage": MAX_LEVERAGE,
        "stop_loss_pct": stop_pct * 100,
        "take_profit_pct": tp_pct * 100,
        "risk_amount": round(risk_amount, 4),
        "risk_reward": MIN_RR_RATIO,
    }

# ═══════════════════════════════════════════════════════════════
# MAIN SCAN LOOP
# ═══════════════════════════════════════════════════════════════

def scan_symbol(symbol, all_tickers):
    """Run all 5 strategies on a single symbol."""
    ticker = all_tickers.get(symbol)
    if not ticker:
        return None

    # Fetch klines (15m candles, last 100)
    df = fetch_klines(symbol, "15m", 100)

    # Fetch funding rate
    fr = fetch_funding_rate(symbol)

    # Run all strategies
    strategies = {
        "funding_rate": strategy_funding_rate(symbol, fr),
        "rsi_divergence": strategy_rsi_divergence(df),
        "vwap": strategy_vwap(df),
        "ema_crossover": strategy_ema_crossover(df),
        "momentum": strategy_momentum(df, ticker),
    }

    # Combine
    direction, score, details = combine_signals(strategies)

    price = float(ticker.get("lastPrice", 0))

    return {
        "symbol": symbol,
        "price": price,
        "direction": direction,
        "score": score,
        "details": details,
        "funding_rate": fr * 100,
        "strategies": {k: (v[0], v[1], v[2]) for k, v in strategies.items()},
    }

def run_full_scan():
    """Scan all watchlist symbols and return ranked signals with EV weighting."""
    log("═══ NEXYROTH Strategy Engine v2.0 (EV-Weighted) — Full Scan ═══")

    # Reload EV config fresh each run (config may change without restart)
    watchlist, ev_boost, avoid_set = load_ev_config()

    # Fetch all tickers once
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/tickers", timeout=12)
        all_tickers = {t["symbol"]: t for t in r.json().get("data", [])}
    except Exception as e:
        log(f"ERROR: Cannot fetch tickers: {e}")
        return []

    results = []
    for sym in watchlist:
        try:
            result = scan_symbol(sym, all_tickers)
            if result:
                # Apply EV boost to raw score
                boost = ev_boost.get(sym, 0.0)
                raw_score = result["score"]
                boosted_score = min(raw_score + boost, 0.99)  # Cap at 99%
                result["score_raw"] = raw_score
                result["score"] = boosted_score
                result["ev_boost"] = boost
                result["is_avoid"] = sym in avoid_set
                results.append(result)
            time.sleep(0.15)  # Rate limit
        except Exception as e:
            log(f"  Error scanning {sym}: {e}")

    # Sort by boosted score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Log results — flag avoid symbols clearly
    signals = [r for r in results if r["direction"] != "NEUTRAL"]
    log(f"Scanned {len(results)} symbols | {len(signals)} signals fired")

    for r in results[:12]:
        emoji = "🟢" if r["direction"] == "LONG" else "🔴" if r["direction"] == "SHORT" else "⚪"
        avoid_flag = " ⚠️AVOID" if r.get("is_avoid") else ""
        boost_str = f" +{r['ev_boost']:.2f}boost" if r.get("ev_boost", 0) > 0 else ""
        log(f"  {emoji} {r['symbol']:<14} ${r['price']:<12.6g} {r['direction']:>6} score={r['score']:.2f}{boost_str}{avoid_flag} FR={r['funding_rate']:+.3f}%")
        for d in r["details"]:
            log(f"    {d}")

    return results

def send_signal_alert(signals, account_balance=10.0):
    """Send email alert for high-confidence signals."""
    if not signals:
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = ""
    for s in signals[:5]:
        pos = calculate_position(account_balance, s["score"], s["price"])
        emoji = "🟢 LONG" if s["direction"] == "LONG" else "🔴 SHORT"
        stop_price = s["price"] * (1 - pos["stop_loss_pct"]/100) if s["direction"] == "LONG" else s["price"] * (1 + pos["stop_loss_pct"]/100)
        tp_price = s["price"] * (1 + pos["take_profit_pct"]/100) if s["direction"] == "LONG" else s["price"] * (1 - pos["take_profit_pct"]/100)

        strategy_breakdown = "<br>".join(s["details"])

        rows += f"""
        <tr style="border-bottom:1px solid #333;">
            <td style="padding:12px;font-weight:bold;font-size:16px;">{s['symbol']}</td>
            <td style="padding:12px;color:{'#00ff88' if s['direction']=='LONG' else '#ff4444'};font-weight:bold;">{emoji}</td>
            <td style="padding:12px;">${s['price']:.6g}</td>
            <td style="padding:12px;font-weight:bold;">{s['score']:.0%}</td>
            <td style="padding:12px;color:#ffaa00;">${stop_price:.6g}</td>
            <td style="padding:12px;color:#00ff88;">${tp_price:.6g}</td>
            <td style="padding:12px;">{pos['leverage']}x / ${pos['position_size']:.2f}</td>
        </tr>
        <tr style="border-bottom:2px solid #555;">
            <td colspan="7" style="padding:8px 12px;font-size:12px;color:#aaa;">{strategy_breakdown}</td>
        </tr>"""

    html = f"""
    <div style="font-family:monospace;background:#0a0a0a;color:#eee;padding:20px;border-radius:8px;">
        <h2 style="color:#00ff88;margin:0 0 5px 0;">⚡ NEXYROTH STRATEGY ENGINE</h2>
        <p style="color:#888;margin:0 0 15px 0;">{now} | Account: ${account_balance:.2f} | Signals: {len(signals)}</p>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <tr style="background:#1a1a1a;color:#888;">
                <th style="padding:8px;text-align:left;">Symbol</th>
                <th style="padding:8px;text-align:left;">Signal</th>
                <th style="padding:8px;text-align:left;">Price</th>
                <th style="padding:8px;text-align:left;">Score</th>
                <th style="padding:8px;text-align:left;">Stop</th>
                <th style="padding:8px;text-align:left;">Target</th>
                <th style="padding:8px;text-align:left;">Lev/Size</th>
            </tr>
            {rows}
        </table>
        <p style="color:#666;font-size:11px;margin-top:15px;">
            Strategies: Funding Rate (30%) | RSI Divergence (25%) | VWAP (20%) | EMA Cross (15%) | Momentum (10%)<br>
            Threshold: {SIGNAL_THRESHOLD:.0%} | Max Risk: {MAX_RISK_PCT:.0%}/trade | Max Leverage: {MAX_LEVERAGE}x | Min R:R: {MIN_RR_RATIO}:1
        </p>
    </div>"""

    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": "NEXYROTH <onboarding@resend.dev>",
                "to": [ALERT_EMAIL],
                "subject": f"⚡ {len(signals)} SIGNAL{'S' if len(signals)>1 else ''} | {signals[0]['symbol']} {signals[0]['direction']} {signals[0]['score']:.0%}",
                "html": html,
            },
            timeout=10,
        )
        if r.status_code == 200:
            log(f"✅ Alert sent | {len(signals)} signals")
        else:
            log(f"Email error {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log(f"Email error: {e}")

def save_signals(results):
    """Append signals to history file."""
    signals = [r for r in results if r["direction"] != "NEUTRAL"]
    if not signals:
        return

    history = []
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE) as f:
                history = json.load(f)
        except:
            pass

    now = datetime.now(timezone.utc).isoformat()
    for s in signals:
        history.append({
            "timestamp": now,
            "symbol": s["symbol"],
            "direction": s["direction"],
            "score": round(s["score"], 4),
            "price": s["price"],
            "funding_rate": round(s["funding_rate"], 4),
        })

    # Keep last 500 signals
    history = history[-500:]
    os.makedirs(os.path.dirname(SIGNALS_FILE), exist_ok=True)
    with open(SIGNALS_FILE, "w") as f:
        json.dump(history, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    results = run_full_scan()

    # Filter actionable signals
    signals = [r for r in results if r["direction"] != "NEUTRAL" and r["score"] >= SIGNAL_THRESHOLD]

    if signals:
        log(f"\n🎯 {len(signals)} ACTIONABLE SIGNAL(S):")
        for s in signals:
            log(f"   → {s['symbol']} {s['direction']} @ ${s['price']:.6g} (score={s['score']:.2f})")
        send_signal_alert(signals)
    else:
        log("No signals above threshold — market is quiet")

    save_signals(results)
    log("═══ Scan complete ═══\n")
