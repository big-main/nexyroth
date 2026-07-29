#!/usr/bin/env python3
"""
NEXYROTH Multi-Timeframe Scanner v1.0
══════════════════════════════════════
Scans all zero-fee tokens across 5 timeframes simultaneously.
Generates a confluence score (0-5) for each token and direction.
Sends Telegram alert when score >= 4 (strong alignment).

Timeframes: 1m, 5m, 15m, 1h, 4h
Indicators per TF: EMA trend, RSI zone, MACD direction
Score: +1 per TF that agrees with direction

Schedule: Every 3 minutes via cron
"""

import os, sys, json, time, requests, numpy as np
from datetime import datetime
from typing import Optional, Dict, List, Tuple

# Import zero-fee config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from zero_fee_config import ZERO_FEE_TOKENS, QTY_PRECISION, PRICE_PRECISION
except:
    ZERO_FEE_TOKENS = ["SOLUSDT", "XRPUSDT", "HYPEUSDT", "DOGEUSDT", "ADAUSDT",
                       "SUIUSDT", "XLMUSDT", "BEATUSDT", "VELVETUSDT",
                       "OILUSDT", "GOLDXAUTUSDT", "SILVERXAGUSDT", "OILBZUSDT"]

BASE_URL = "https://fapi.bitunix.com"
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
CANDLE_LIMIT = 50
MIN_CONFLUENCE = 4  # Alert when >= 4/5 TFs agree

# Paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SCAN_FILE = os.path.join(DATA_DIR, "multi_tf_scan.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "multi_tf_scanner.log")

# Telegram
TG_TOKEN_FILE = os.path.expanduser("~/.secrets/telegram_bot_token")
TG_CHAT_FILE = os.path.expanduser("~/.secrets/telegram_chat_id")

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def send_telegram(msg: str):
    try:
        token = open(TG_TOKEN_FILE).read().strip()
        chat_id = open(TG_CHAT_FILE).read().strip()
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════
def calc_ema(data: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    ema = np.zeros_like(data)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
    return ema

def calc_rsi(data: np.ndarray, period: int = 14) -> float:
    if len(data) < period + 1:
        return 50.0
    deltas = np.diff(data[-(period+1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(data: np.ndarray) -> Tuple[float, float]:
    """Returns (macd_line, signal_line)"""
    if len(data) < 26:
        return 0.0, 0.0
    ema12 = calc_ema(data, 12)
    ema26 = calc_ema(data, 26)
    macd_line = ema12 - ema26
    signal = calc_ema(macd_line[-9:], 9) if len(macd_line) >= 9 else macd_line
    return float(macd_line[-1]), float(signal[-1])

def analyze_timeframe(closes: np.ndarray) -> Dict:
    """Analyze a single timeframe and return bias."""
    if len(closes) < 26:
        return {"bias": "neutral", "ema_trend": "flat", "rsi": 50, "macd": "flat"}

    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    rsi = calc_rsi(closes)
    macd_val, signal_val = calc_macd(closes)

    # EMA trend
    ema_trend = "bullish" if ema9[-1] > ema21[-1] else "bearish"

    # RSI zone
    if rsi > 60:
        rsi_zone = "bullish"
    elif rsi < 40:
        rsi_zone = "bearish"
    else:
        rsi_zone = "neutral"

    # MACD direction
    macd_dir = "bullish" if macd_val > signal_val else "bearish"

    # Overall bias (2 of 3 must agree)
    votes = [ema_trend, rsi_zone, macd_dir]
    bull_count = votes.count("bullish")
    bear_count = votes.count("bearish")

    if bull_count >= 2:
        bias = "LONG"
    elif bear_count >= 2:
        bias = "SHORT"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "ema_trend": ema_trend,
        "rsi": round(rsi, 1),
        "macd": macd_dir,
        "price": float(closes[-1])
    }

# ═══════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════
def get_klines(symbol: str, interval: str, limit: int = CANDLE_LIMIT) -> Optional[np.ndarray]:
    """Fetch kline closes for a symbol and interval."""
    try:
        r = requests.get(f"{BASE_URL}/api/v1/futures/market/kline",
            params={"symbol": symbol, "klineType": interval, "limit": str(limit)},
            timeout=10)
        data = r.json().get("data", [])
        if not data:
            return None
        closes = np.array([float(k["close"]) for k in data])
        return closes
    except:
        return None

# ═══════════════════════════════════════════════════════════════
# MAIN SCANNER
# ═══════════════════════════════════════════════════════════════
def scan_symbol(symbol: str) -> Dict:
    """Scan a symbol across all timeframes."""
    result = {"symbol": symbol, "timeframes": {}, "long_score": 0, "short_score": 0}

    for tf in TIMEFRAMES:
        closes = get_klines(symbol, tf)
        if closes is None or len(closes) < 26:
            result["timeframes"][tf] = {"bias": "NEUTRAL", "rsi": 50}
            continue

        analysis = analyze_timeframe(closes)
        result["timeframes"][tf] = analysis

        if analysis["bias"] == "LONG":
            result["long_score"] += 1
        elif analysis["bias"] == "SHORT":
            result["short_score"] += 1

    # Determine overall signal
    if result["long_score"] >= MIN_CONFLUENCE:
        result["signal"] = "STRONG_LONG"
    elif result["short_score"] >= MIN_CONFLUENCE:
        result["signal"] = "STRONG_SHORT"
    elif result["long_score"] >= 3:
        result["signal"] = "LEAN_LONG"
    elif result["short_score"] >= 3:
        result["signal"] = "LEAN_SHORT"
    else:
        result["signal"] = "MIXED"

    return result

def main():
    log(f"🔍 Multi-TF Scanner v1.0 | Scanning {len(ZERO_FEE_TOKENS)} tokens × {len(TIMEFRAMES)} timeframes")

    results = []
    alerts = []

    for symbol in ZERO_FEE_TOKENS:
        result = scan_symbol(symbol)
        results.append(result)

        # Log summary
        price = result["timeframes"].get("1m", {}).get("price", 0)
        log(f"  {symbol:16s} | L:{result['long_score']}/5 S:{result['short_score']}/5 | {result['signal']:12s} | ${price}")

        # Alert on strong signals
        if result["signal"] in ("STRONG_LONG", "STRONG_SHORT"):
            alerts.append(result)

    # Save scan results
    os.makedirs(DATA_DIR, exist_ok=True)
    scan_data = {
        "timestamp": time.time(),
        "scan_time": datetime.utcnow().isoformat(),
        "results": results,
        "alerts": len(alerts)
    }
    with open(SCAN_FILE, "w") as f:
        json.dump(scan_data, f, indent=2)

    # Send Telegram alerts for strong signals
    if alerts:
        msg = "🎯 <b>Multi-TF Alert</b>\n\n"
        for a in alerts:
            direction = "🟢 LONG" if "LONG" in a["signal"] else "🔴 SHORT"
            score = a["long_score"] if "LONG" in a["signal"] else a["short_score"]
            price = a["timeframes"].get("1m", {}).get("price", 0)
            rsi_1m = a["timeframes"].get("1m", {}).get("rsi", 50)
            msg += f"{direction} <b>{a['symbol']}</b> ({score}/5 TFs)\n"
            msg += f"  Price: ${price} | RSI(1m): {rsi_1m}\n\n"
        send_telegram(msg)
        log(f"  📨 Sent {len(alerts)} alert(s)")

    log(f"  ✅ Scan complete | {len(alerts)} strong signals")

if __name__ == "__main__":
    main()
