#!/usr/bin/env python3
"""
NEXYROTH Bitunix Zero-Fee Scalper v1.0
=======================================
EMA 9/21 crossover + RSI(14) filter on 1-minute candles.
Only trades the 10 zero-fee tokens on Bitunix.

Strategy:
  - EMA9 crosses above EMA21 + RSI > 50  → LONG
  - EMA9 crosses below EMA21 + RSI < 50  → SHORT
  - TP: +0.3%, SL: -0.2% (tight scalp)
  - Max 1 position at a time
  - Runs every 5 minutes via cron

Auth: Double-SHA256 (same as auto-executor)
"""

import os
import json
import time
import uuid
import hashlib
import requests
from datetime import datetime, timezone
from typing import Optional, List, Dict

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
BITUNIX_API = "https://fapi.bitunix.com"

def _read_secret(env_var: str, path: str) -> str:
    val = os.getenv(env_var, "")
    if not val and os.path.exists(path):
        try:
            with open(path) as f:
                val = f.read().strip()
        except:
            pass
    return val

API_KEY    = _read_secret("BITUNIX_API_KEY",    os.path.expanduser("~/.secrets/bitunix_api_key"))
SECRET_KEY = _read_secret("BITUNIX_SECRET_KEY", os.path.expanduser("~/.secrets/bitunix_secret_key"))
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL    = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")

LOG_FILE   = "/home/ubuntu/trading_sniper/bitunix_scalper.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/scalper_state.json"

# Strategy parameters — MAXIMUM AGGRESSION MODE (updated 2026-07-25)
TP_PCT          = 0.003   # +0.3% take profit
SL_PCT          = 0.002   # -0.2% stop loss
LEVERAGE        = 10      # 10x leverage for scalping
RISK_PCT        = 0.45    # 45% of balance per trade
MIN_BALANCE     = 3.0     # Don't trade below $3
EMA_FAST        = 9       # Fast EMA period
EMA_SLOW        = 21      # Slow EMA period
RSI_PERIOD      = 14      # RSI period
RSI_LONG_MIN    = 45      # RSI must be above this for LONG
RSI_SHORT_MAX   = 55      # RSI must be below this for SHORT
MIN_CANDLES     = 30      # Minimum candles needed for reliable signals
CANDLE_INTERVAL = "1m"    # 1-minute candles

# Zero-fee token allowlist
ZERO_FEE_SYMBOLS = [
    "SOLUSDT", "XRPUSDT", "SUIUSDT", "LABUSDT", "BUSDT",
    "TONUSDT", "SKYAIUSDT", "DOGSUSDT", "DOGEUSDT", "TSTUSDT",
]

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# AUTH — matches bitunix_auto_executor.py signing logic exactly
# ═══════════════════════════════════════════════════════════════
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_sign(nonce: str, timestamp: str, query_params: str = "", body: str = "") -> str:
    """
    sign = SHA256( SHA256(nonce + timestamp + api-key + queryParams + body) + secretKey )
    """
    digest = sha256_hex(nonce + timestamp + API_KEY + query_params + body)
    return sha256_hex(digest + SECRET_KEY)

def make_headers(query_params: str = "", body: str = "") -> dict:
    nonce     = uuid.uuid4().hex[:32]
    timestamp = str(int(time.time() * 1000))
    sign      = make_sign(nonce, timestamp, query_params, body)
    return {
        "api-key":      API_KEY,
        "nonce":        nonce,
        "timestamp":    timestamp,
        "sign":         sign,
        "Content-Type": "application/json",
        "language":     "en-US",
    }

def bitunix_get(path: str, params: dict = None) -> Optional[dict]:
    try:
        if params:
            sorted_params = sorted(params.items())
            query_str = "".join(f"{k}{v}" for k, v in sorted_params)
            query_url = "&".join(f"{k}={v}" for k, v in sorted_params)
        else:
            query_str = ""
            query_url = ""
        headers = make_headers(query_params=query_str)
        url = f"{BITUNIX_API}{path}"
        if query_url:
            url += f"?{query_url}"
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            log(f"  API error [{path}]: {data.get('msg', data)}")
            return None
        return data.get("data")
    except Exception as e:
        log(f"  GET error [{path}]: {e}")
        return None

def bitunix_post(path: str, body: dict) -> Optional[dict]:
    try:
        body_str = json.dumps(body, separators=(",", ":"))
        headers  = make_headers(body=body_str)
        r = requests.post(f"{BITUNIX_API}{path}", headers=headers, data=body_str, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            log(f"  API error [{path}]: {data.get('msg', data)}")
            return None
        return data.get("data")
    except Exception as e:
        log(f"  POST error [{path}]: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# MARKET DATA
# ═══════════════════════════════════════════════════════════════
def get_balance() -> float:
    data = bitunix_get("/api/v1/futures/account", {"marginCoin": "USDT"})
    if not data:
        return 0.0
    return float(data.get("available", 0) or 0)

def get_klines(symbol: str, interval: str = "1m", limit: int = 50) -> List[dict]:
    """Fetch OHLCV candles. Returns list of {open, high, low, close, volume}."""
    try:
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/market/kline",
            params={"symbol": symbol, "interval": interval, "limit": str(limit)},
            timeout=10
        )
        resp = r.json()
        if resp.get("code") != 0:
            return []
        data = resp.get("data", [])
        candles = []
        for c in data:
            try:
                # API returns dicts: {open, high, low, close, quoteVol, baseVol, time}
                if isinstance(c, dict):
                    candles.append({
                        "open":   float(c.get("open", 0)),
                        "high":   float(c.get("high", 0)),
                        "low":    float(c.get("low", 0)),
                        "close":  float(c.get("close", 0)),
                        "volume": float(c.get("quoteVol", 0)),
                    })
                elif isinstance(c, list):
                    candles.append({
                        "open":   float(c[1]),
                        "high":   float(c[2]),
                        "low":    float(c[3]),
                        "close":  float(c[4]),
                        "volume": float(c[5]),
                    })
            except (IndexError, TypeError, ValueError):
                pass
        return candles
    except Exception as e:
        log(f"  Kline error [{symbol}]: {e}")
        return []

def get_ticker_price(symbol: str) -> float:
    """Get current last price for a symbol using the tickers endpoint."""
    try:
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/market/tickers",
            params={"symbol": symbol},
            timeout=8
        )
        resp = r.json()
        if resp.get("code") != 0:
            return 0.0
        data = resp.get("data", [])
        # Returns a list; find the matching symbol
        if isinstance(data, list):
            for item in data:
                if item.get("symbol") == symbol:
                    return float(item.get("last", item.get("lastPrice", 0)) or 0)
            # If symbol filter didn't work, return first item
            if data:
                return float(data[0].get("last", data[0].get("lastPrice", 0)) or 0)
        elif isinstance(data, dict):
            return float(data.get("last", data.get("lastPrice", 0)) or 0)
        return 0.0
    except:
        return 0.0

def get_open_positions() -> List[dict]:
    """Get all open positions."""
    data = bitunix_get("/api/v1/futures/position/get_pending_positions", {"marginCoin": "USDT"})
    if not data:
        return []
    positions = data if isinstance(data, list) else data.get("positionList", [])
    return [p for p in positions if float(p.get("qty", 0) or 0) > 0]

def get_min_qty(symbol: str) -> float:
    """Get minimum order quantity for a symbol."""
    try:
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/market/detail",
            params={"symbol": symbol},
            timeout=8
        )
        resp = r.json()
        if resp.get("code") != 0:
            return 1.0
        data = resp.get("data", {})
        return float(data.get("minQty", 1) or 1)
    except:
        return 1.0

# ═══════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ═══════════════════════════════════════════════════════════════
def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result

def rsi(closes: List[float], period: int = 14) -> float:
    """Relative Strength Index (last value)."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    # Initial averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))

def get_signal(symbol: str) -> Optional[str]:
    """
    Returns 'LONG', 'SHORT', or None based on EMA crossover + RSI.
    """
    candles = get_klines(symbol, CANDLE_INTERVAL, limit=60)
    if len(candles) < MIN_CANDLES:
        log(f"  {symbol}: insufficient candles ({len(candles)})")
        return None

    closes = [c["close"] for c in candles]
    ema_fast = ema(closes, EMA_FAST)
    ema_slow = ema(closes, EMA_SLOW)

    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None

    # Align lengths
    min_len = min(len(ema_fast), len(ema_slow))
    ef = ema_fast[-min_len:]
    es = ema_slow[-min_len:]

    # Previous and current crossover state
    prev_above = ef[-2] > es[-2]
    curr_above = ef[-1] > es[-1]

    current_rsi = rsi(closes, RSI_PERIOD)

    # Bullish crossover: EMA9 crosses above EMA21
    if not prev_above and curr_above and current_rsi > RSI_LONG_MIN:
        log(f"  {symbol}: LONG signal | EMA9={ef[-1]:.6f} > EMA21={es[-1]:.6f} | RSI={current_rsi:.1f}")
        return "LONG"

    # Bearish crossover: EMA9 crosses below EMA21
    if prev_above and not curr_above and current_rsi < RSI_SHORT_MAX:
        log(f"  {symbol}: SHORT signal | EMA9={ef[-1]:.6f} < EMA21={es[-1]:.6f} | RSI={current_rsi:.1f}")
        return "SHORT"

    return None

# ═══════════════════════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def load_state() -> dict:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"active_position": None, "total_trades": 0, "total_pnl": 0.0}

def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════
def place_scalp_trade(symbol: str, direction: str, price: float, balance: float) -> Optional[dict]:
    """Place a scalp trade with tight TP/SL."""
    risk_usdt = balance * RISK_PCT
    position_val = risk_usdt * LEVERAGE
    qty = position_val / price

    min_qty = get_min_qty(symbol)
    if qty < min_qty:
        log(f"  ⚠️ {symbol}: qty {qty:.6f} < min {min_qty} — skipping")
        return None

    qty = round(qty, 3)

    if direction == "LONG":
        side     = "BUY"
        tp_price = round(price * (1 + TP_PCT), 6)
        sl_price = round(price * (1 - SL_PCT), 6)
    else:
        side     = "SELL"
        tp_price = round(price * (1 - TP_PCT), 6)
        sl_price = round(price * (1 + SL_PCT), 6)

    order_body = {
        "symbol":      symbol,
        "side":        side,
        "tradeSide":   "OPEN",
        "orderType":   "MARKET",
        "qty":         str(qty),
        "tpPrice":     str(tp_price),
        "tpStopType":  "MARK_PRICE",
        "tpOrderType": "MARKET",
        "slPrice":     str(sl_price),
        "slStopType":  "MARK_PRICE",
        "slOrderType": "MARKET",
        "clientId":    f"nexyroth_scalp_{uuid.uuid4().hex[:12]}",
    }

    log(f"  📤 Scalp {direction} {symbol} | qty={qty} | price=${price:.6f} | TP=${tp_price:.6f} | SL=${sl_price:.6f}")
    result = bitunix_post("/api/v1/futures/trade/place_order", order_body)

    if result:
        order_id = result.get("orderId", "?")
        log(f"  ✅ Scalp order placed: {order_id}")
        return {
            "orderId":    order_id,
            "symbol":     symbol,
            "direction":  direction,
            "qty":        qty,
            "entryPrice": price,
            "tpPrice":    tp_price,
            "slPrice":    sl_price,
            "openTime":   datetime.now(timezone.utc).isoformat(),
        }
    return None

def check_position_closed(state: dict) -> bool:
    """Check if the active position has been closed (hit TP or SL)."""
    pos = state.get("active_position")
    if not pos:
        return True

    symbol = pos["symbol"]
    open_positions = get_open_positions()
    open_symbols = {p.get("symbol") for p in open_positions}

    if symbol not in open_symbols:
        log(f"  ✅ Position {symbol} closed (TP/SL hit or manual close)")
        return True
    return False

def send_scalp_alert(trade: dict, balance: float):
    """Send email alert for scalp trade."""
    direction = trade["direction"]
    symbol    = trade["symbol"]
    emoji     = "🟢" if direction == "LONG" else "🔴"
    subject   = f"{emoji} NEXYROTH Scalp {direction}: {symbol}"
    html = f"""
    <div style="font-family:monospace;background:#0a0a0a;color:#e0e0e0;padding:20px;border-radius:12px;max-width:480px">
        <h2 style="color:#00d4ff;margin:0 0 16px">{emoji} SCALP {direction}: {symbol}</h2>
        <p style="color:#aaa;margin:4px 0">Entry: <b style="color:#fff">${trade['entryPrice']:.6f}</b></p>
        <p style="color:#aaa;margin:4px 0">TP: <b style="color:#00ff88">${trade['tpPrice']:.6f}</b> (+{TP_PCT*100:.1f}%)</p>
        <p style="color:#aaa;margin:4px 0">SL: <b style="color:#ff4444">${trade['slPrice']:.6f}</b> (-{SL_PCT*100:.1f}%)</p>
        <p style="color:#aaa;margin:4px 0">Qty: <b style="color:#fff">{trade['qty']}</b></p>
        <p style="color:#aaa;margin:4px 0">Balance: <b style="color:#fff">${balance:.2f} USDT</b></p>
        <p style="color:#555;font-size:10px;margin-top:12px">NEXYROTH Scalper v1.0 | EMA9/21 + RSI14</p>
    </div>
    """
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=10
        )
        log("  📧 Scalp alert sent.")
    except Exception as e:
        log(f"  ⚠️ Email error: {e}")

# ═══════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════
def main():
    log("=" * 60)
    log("NEXYROTH Bitunix Zero-Fee Scalper v1.0")
    log("=" * 60)

    if not API_KEY or not SECRET_KEY:
        log("  ❌ No API keys — exiting")
        return

    # Load state
    state = load_state()

    # Check balance
    balance = get_balance()
    log(f"  Balance: ${balance:.2f} USDT")

    if balance < MIN_BALANCE:
        log(f"  ⚠️ Balance ${balance:.2f} below minimum ${MIN_BALANCE} — pausing")
        return

    # Check if active position is still open
    if state.get("active_position"):
        if check_position_closed(state):
            state["active_position"] = None
            state["total_trades"] = state.get("total_trades", 0) + 1
            save_state(state)
        else:
            log(f"  📊 Active position: {state['active_position']['symbol']} {state['active_position']['direction']} — waiting for TP/SL")
            return

    # Scan zero-fee tokens for signals
    log("  🔍 Scanning zero-fee tokens for EMA/RSI signals...")
    signal_found = False

    for symbol in ZERO_FEE_SYMBOLS:
        signal = get_signal(symbol)
        if not signal:
            continue

        # Get current price
        price = get_ticker_price(symbol)
        if price <= 0:
            log(f"  ⚠️ {symbol}: could not get price")
            continue

        log(f"  🎯 Signal: {signal} {symbol} @ ${price:.6f}")

        # Place trade
        trade = place_scalp_trade(symbol, signal, price, balance)
        if trade:
            state["active_position"] = trade
            save_state(state)
            send_scalp_alert(trade, balance)
            signal_found = True
            break  # Only 1 position at a time

        time.sleep(0.2)

    if not signal_found:
        log("  ⏳ No EMA/RSI signals this scan.")

    log(f"\n  📊 Total scalp trades: {state.get('total_trades', 0)}")
    log("=" * 60)

if __name__ == "__main__":
    main()
