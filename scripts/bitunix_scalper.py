#!/usr/bin/env python3
"""
NEXYROTH × AlgoPro Hybrid Scalper v2.0
=======================================
Full confluence strategy running natively on cloud computer.
No TradingView needed — all indicators computed locally.

Strategy Filters (ALL must agree for entry):
  1. EMA 9/21 crossover (primary signal)
  2. 200 EMA trend filter (only LONG above, SHORT below)
  3. MACD histogram confirmation (positive for LONG, negative for SHORT)
  4. Volume filter (1.2x above 20-bar average)
  5. RSI filter (>45 for LONG, <55 for SHORT)

Risk Management:
  - Rolling Kelly Criterion position sizing (adapts to win rate)
  - Chandelier trailing stop (ATR-based, locks profits)
  - ATR emergency stop (hard stop if trail fails)
  - TP at 3:1 risk-reward ratio

Execution:
  - Runs every 1 minute via cron
  - Only trades 10 zero-fee tokens on Bitunix
  - Max 2 concurrent positions
  - Auto-manages trailing stops on existing positions

Auth: Double-SHA256 (same as auto-executor)
"""

import os
import json
import time
import uuid
import hashlib
import requests
import math
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

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
RESEND_API_KEY = _read_secret("RESEND_API_KEY", os.path.expanduser("~/.secrets/resend_api_key"))
ALERT_EMAIL    = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")

LOG_FILE   = "/home/ubuntu/trading_sniper/bitunix_scalper.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/scalper_state.json"
HISTORY_FILE = "/home/ubuntu/trading_sniper/data/scalper_history.json"

# ─── Strategy Parameters ───────────────────────────────────────
# EMA Crossover
EMA_FAST        = 9
EMA_SLOW        = 21
EMA_TREND       = 200    # Trend filter

# MACD
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9

# RSI
RSI_PERIOD      = 14
RSI_LONG_MIN    = 45
RSI_SHORT_MAX   = 55

# Volume
VOL_MULT        = 1.2    # Volume must be 1.2x above 20-bar avg
VOL_LOOKBACK    = 20

# ATR / Chandelier
ATR_PERIOD      = 14
CHANDELIER_MULT = 2.5    # Chandelier trailing stop multiplier
ATR_EMERGENCY   = 1.5    # Emergency hard stop multiplier

# Risk Management
LEVERAGE        = 10
MIN_BALANCE     = 2.0
MAX_POSITIONS   = 2
TP_RR_RATIO     = 3.0    # Take profit at 3:1 risk-reward
FALLBACK_RISK   = 0.02   # 2% risk before Kelly activates
MAX_RISK_CAP    = 0.05   # 5% max risk per trade (Kelly cap)
MIN_KELLY_TRADES = 10    # Min trades before Kelly activates

# Candle settings
CANDLE_INTERVAL = "1m"
CANDLE_LIMIT    = 250    # Need 200+ for EMA200

# Zero-fee token allowlist
ZERO_FEE_SYMBOLS = [
    "SOLUSDT", "XRPUSDT", "SUIUSDT", "LABUSDT", "BUSDT",
    "TONUSDT", "SKYAIUSDT", "DOGSUSDT", "DOGEUSDT", "TSTUSDT",
]

# Per-symbol minimum qty (from Bitunix error messages)
MIN_QTY_MAP = {
    "SOLUSDT": 0.1, "XRPUSDT": 5, "SUIUSDT": 10, "LABUSDT": 10,
    "BUSDT": 20, "TONUSDT": 1, "SKYAIUSDT": 10, "DOGSUSDT": 100000,
    "DOGEUSDT": 10, "TSTUSDT": 10,
}

# Per-symbol price precision
PRICE_PRECISION = {
    "SOLUSDT": 2, "XRPUSDT": 4, "SUIUSDT": 4, "LABUSDT": 4,
    "BUSDT": 4, "TONUSDT": 4, "SKYAIUSDT": 5, "DOGSUSDT": 8,
    "DOGEUSDT": 5, "TSTUSDT": 5,
}

QTY_PRECISION = {
    "SOLUSDT": 2, "XRPUSDT": 1, "SUIUSDT": 1, "LABUSDT": 1,
    "BUSDT": 1, "TONUSDT": 2, "SKYAIUSDT": 1, "DOGSUSDT": 0,
    "DOGEUSDT": 1, "TSTUSDT": 1,
}

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
# AUTH — Double-SHA256
# ═══════════════════════════════════════════════════════════════
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_sign(nonce: str, timestamp: str, query_params: str = "", body: str = "") -> str:
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

def get_klines(symbol: str, interval: str = "1m", limit: int = 250) -> List[dict]:
    """Fetch OHLCV candles."""
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
    """Get current last price."""
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
        if isinstance(data, list):
            for item in data:
                if item.get("symbol") == symbol:
                    return float(item.get("last", item.get("lastPrice", 0)) or 0)
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

# ═══════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ═══════════════════════════════════════════════════════════════
def calc_ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average — returns full-length list."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result

def calc_rsi(closes: List[float], period: int = 14) -> float:
    """RSI (last value)."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))

def calc_macd(closes: List[float]) -> Tuple[float, float, float]:
    """MACD line, signal line, histogram (last values)."""
    ema12 = calc_ema(closes, MACD_FAST)
    ema26 = calc_ema(closes, MACD_SLOW)
    if not ema12 or not ema26:
        return 0, 0, 0
    # Align
    min_len = min(len(ema12), len(ema26))
    macd_line = [ema12[-(min_len - i)] - ema26[-(min_len - i)] for i in range(min_len)]
    if len(macd_line) < MACD_SIGNAL:
        return macd_line[-1] if macd_line else 0, 0, 0
    signal = calc_ema(macd_line, MACD_SIGNAL)
    if not signal:
        return macd_line[-1], 0, macd_line[-1]
    hist = macd_line[-1] - signal[-1]
    return macd_line[-1], signal[-1], hist

def calc_atr(candles: List[dict], period: int = 14) -> float:
    """Average True Range (last value)."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    # Wilder's smoothing
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr

def calc_volume_ratio(candles: List[dict], lookback: int = 20) -> float:
    """Current volume / average volume over lookback."""
    if len(candles) < lookback + 1:
        return 0.0
    volumes = [c["volume"] for c in candles]
    avg_vol = sum(volumes[-(lookback+1):-1]) / lookback
    if avg_vol == 0:
        return 0.0
    return volumes[-1] / avg_vol

# ═══════════════════════════════════════════════════════════════
# SIGNAL GENERATION — Full Confluence
# ═══════════════════════════════════════════════════════════════
def get_signal(symbol: str) -> Optional[Dict]:
    """
    Returns signal dict with direction, ATR, entry price, or None.
    ALL 5 filters must agree for a signal.
    """
    candles = get_klines(symbol, CANDLE_INTERVAL, CANDLE_LIMIT)
    if len(candles) < EMA_TREND + 5:
        return None

    closes = [c["close"] for c in candles]
    current_price = closes[-1]

    # ─── Filter 1: EMA 9/21 Crossover ───────────────────────────
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None

    min_len = min(len(ema_fast), len(ema_slow))
    ef = ema_fast[-min_len:]
    es = ema_slow[-min_len:]

    prev_above = ef[-2] > es[-2]
    curr_above = ef[-1] > es[-1]

    # Must be an actual crossover (state change)
    if prev_above == curr_above:
        return None  # No crossover happening

    direction = "LONG" if (not prev_above and curr_above) else "SHORT"

    # ─── Filter 2: 200 EMA Trend ────────────────────────────────
    ema200 = calc_ema(closes, EMA_TREND)
    if not ema200:
        return None
    trend_ema = ema200[-1]

    if direction == "LONG" and current_price < trend_ema:
        return None  # Don't LONG below 200 EMA
    if direction == "SHORT" and current_price > trend_ema:
        return None  # Don't SHORT above 200 EMA

    # ─── Filter 3: MACD Histogram Confirmation ──────────────────
    macd_line, signal_line, histogram = calc_macd(closes)
    if direction == "LONG" and histogram <= 0:
        return None  # MACD must be positive for LONG
    if direction == "SHORT" and histogram >= 0:
        return None  # MACD must be negative for SHORT

    # ─── Filter 4: Volume Confirmation ──────────────────────────
    vol_ratio = calc_volume_ratio(candles, VOL_LOOKBACK)
    if vol_ratio < VOL_MULT:
        return None  # Volume too low

    # ─── Filter 5: RSI Confirmation ─────────────────────────────
    current_rsi = calc_rsi(closes, RSI_PERIOD)
    if direction == "LONG" and current_rsi < RSI_LONG_MIN:
        return None
    if direction == "SHORT" and current_rsi > RSI_SHORT_MAX:
        return None

    # ─── All 5 filters passed! ──────────────────────────────────
    atr = calc_atr(candles, ATR_PERIOD)

    log(f"  ✅ {symbol}: {direction} SIGNAL CONFIRMED")
    log(f"     EMA9={ef[-1]:.6f} {'>' if direction=='LONG' else '<'} EMA21={es[-1]:.6f}")
    log(f"     Price {'>' if direction=='LONG' else '<'} EMA200={trend_ema:.6f}")
    log(f"     MACD hist={histogram:.8f} | RSI={current_rsi:.1f} | Vol={vol_ratio:.2f}x")
    log(f"     ATR={atr:.8f}")

    return {
        "direction": direction,
        "price": current_price,
        "atr": atr,
        "rsi": current_rsi,
        "macd_hist": histogram,
        "vol_ratio": vol_ratio,
    }

# ═══════════════════════════════════════════════════════════════
# ROLLING KELLY CRITERION
# ═══════════════════════════════════════════════════════════════
def load_trade_history() -> List[dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except:
            pass
    return []

def save_trade_history(history: List[dict]):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history[-100:], f, indent=2)  # Keep last 100 trades

def calc_kelly_fraction(history: List[dict]) -> float:
    """Calculate Kelly fraction from trade history."""
    if len(history) < MIN_KELLY_TRADES:
        return FALLBACK_RISK

    # Use last 50 trades for rolling window
    recent = history[-50:]
    wins = [t for t in recent if t.get("pnl", 0) > 0]
    losses = [t for t in recent if t.get("pnl", 0) < 0]

    if not wins or not losses:
        return FALLBACK_RISK

    win_rate = len(wins) / len(recent)
    avg_win = sum(t["pnl"] for t in wins) / len(wins)
    avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses))

    if avg_loss == 0:
        return MAX_RISK_CAP

    # Kelly = W - (1-W)/R where R = avg_win/avg_loss
    rr = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / rr

    # Half-Kelly for safety, capped
    half_kelly = kelly / 2.0
    return max(FALLBACK_RISK, min(half_kelly, MAX_RISK_CAP))

# ═══════════════════════════════════════════════════════════════
# CHANDELIER TRAILING STOP
# ═══════════════════════════════════════════════════════════════
def calc_chandelier_stop(candles: List[dict], direction: str, atr: float) -> float:
    """Calculate Chandelier trailing stop level."""
    if direction == "LONG":
        # Highest high in recent candles minus ATR * mult
        recent_highs = [c["high"] for c in candles[-ATR_PERIOD:]]
        highest = max(recent_highs) if recent_highs else candles[-1]["close"]
        return highest - (atr * CHANDELIER_MULT)
    else:
        # Lowest low in recent candles plus ATR * mult
        recent_lows = [c["low"] for c in candles[-ATR_PERIOD:]]
        lowest = min(recent_lows) if recent_lows else candles[-1]["close"]
        return lowest + (atr * CHANDELIER_MULT)

# ═══════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════
def place_trade(symbol: str, direction: str, price: float, atr: float, balance: float) -> Optional[dict]:
    """Place a trade with Kelly sizing and ATR-based TP/SL."""
    # Kelly position sizing
    history = load_trade_history()
    risk_frac = calc_kelly_fraction(history)
    risk_usdt = balance * risk_frac
    position_val = risk_usdt * LEVERAGE

    qty = position_val / price
    min_qty = MIN_QTY_MAP.get(symbol, 1.0)
    qty_prec = QTY_PRECISION.get(symbol, 2)
    price_prec = PRICE_PRECISION.get(symbol, 4)

    # Bump up to minimum if close
    if qty < min_qty:
        needed_balance = (min_qty * price) / LEVERAGE / risk_frac
        if needed_balance < balance * 2:  # Within 2x intended risk
            qty = min_qty
        else:
            log(f"  ⚠️ {symbol}: qty {qty:.4f} < min {min_qty} — skipping")
            return None

    qty = round(qty, qty_prec)
    if qty_prec == 0:
        qty = int(qty)

    # ATR-based stops
    sl_distance = atr * ATR_EMERGENCY
    tp_distance = sl_distance * TP_RR_RATIO

    if direction == "LONG":
        side     = "BUY"
        tp_price = round(price + tp_distance, price_prec)
        sl_price = round(price - sl_distance, price_prec)
    else:
        side     = "SELL"
        tp_price = round(price - tp_distance, price_prec)
        sl_price = round(price + sl_distance, price_prec)

    order_body = {
        "symbol":      symbol,
        "side":        side,
        "tradeSide":   "OPEN",
        "orderType":   "MARKET",
        "qty":         str(qty),
        "leverage":    str(LEVERAGE),
        "positionType": 1,
        "tpPrice":     str(tp_price),
        "slPrice":     str(sl_price),
    }

    log(f"  📤 PLACING {direction} {symbol}: qty={qty} @ ~{price} | TP={tp_price} SL={sl_price} | Kelly={risk_frac:.3f}")
    result = bitunix_post("/api/v1/futures/trade/place_order", order_body)

    if result:
        order_id = result.get("orderId", "unknown")
        log(f"  ✅ ORDER FILLED: {order_id}")
        send_alert(f"🎯 SCALPER {direction} {symbol}\nQty: {qty}\nEntry: ~{price}\nTP: {tp_price}\nSL: {sl_price}\nKelly: {risk_frac:.3f}\nOrder: {order_id}")
        return {
            "symbol": symbol,
            "direction": direction,
            "entry_price": price,
            "qty": qty,
            "tp": tp_price,
            "sl": sl_price,
            "atr": atr,
            "order_id": order_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    return None

# ═══════════════════════════════════════════════════════════════
# TRAILING STOP MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def manage_trailing_stops(state: dict):
    """Check and update trailing stops on active positions."""
    active = state.get("active_positions", [])
    if not active:
        return

    for pos in active[:]:
        symbol = pos["symbol"]
        direction = pos["direction"]
        entry = pos["entry_price"]

        candles = get_klines(symbol, CANDLE_INTERVAL, 50)
        if len(candles) < ATR_PERIOD + 1:
            continue

        current_price = candles[-1]["close"]
        atr = calc_atr(candles, ATR_PERIOD)
        chandelier = calc_chandelier_stop(candles, direction, atr)

        # Check if Chandelier stop is hit
        if direction == "LONG" and current_price < chandelier:
            log(f"  🔔 {symbol} LONG: Chandelier stop hit @ {current_price:.6f} (stop={chandelier:.6f})")
            close_position(symbol, direction, current_price, pos, state)
        elif direction == "SHORT" and current_price > chandelier:
            log(f"  🔔 {symbol} SHORT: Chandelier stop hit @ {current_price:.6f} (stop={chandelier:.6f})")
            close_position(symbol, direction, current_price, pos, state)
        else:
            # Update trailing stop in state
            pos["chandelier_stop"] = chandelier
            log(f"  📊 {symbol} {direction}: price={current_price:.6f} | trail={chandelier:.6f} | ATR={atr:.8f}")

def close_position(symbol: str, direction: str, exit_price: float, pos: dict, state: dict):
    """Close a position via market order."""
    qty = pos["qty"]
    close_side = "SELL" if direction == "LONG" else "BUY"

    order_body = {
        "symbol": symbol,
        "side": close_side,
        "tradeSide": "CLOSE",
        "orderType": "MARKET",
        "qty": str(qty),
        "positionType": 1,
    }

    result = bitunix_post("/api/v1/futures/trade/place_order", order_body)
    entry = pos["entry_price"]

    if direction == "LONG":
        pnl_pct = (exit_price - entry) / entry
    else:
        pnl_pct = (entry - exit_price) / entry

    pnl_usdt = pnl_pct * float(qty) * entry * LEVERAGE / LEVERAGE  # Simplified

    log(f"  💰 CLOSED {symbol} {direction}: entry={entry} exit={exit_price} PnL={pnl_pct*100:.2f}%")

    # Record in history
    history = load_trade_history()
    history.append({
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "exit": exit_price,
        "pnl": pnl_pct,
        "pnl_usdt": pnl_usdt,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    save_trade_history(history)

    # Remove from active
    if pos in state.get("active_positions", []):
        state["active_positions"].remove(pos)
    state["total_trades"] = state.get("total_trades", 0) + 1
    state["total_pnl"] = state.get("total_pnl", 0) + pnl_pct

    send_alert(f"💰 SCALPER CLOSED {symbol} {direction}\nEntry: {entry}\nExit: {exit_price}\nPnL: {pnl_pct*100:.2f}%")

# ═══════════════════════════════════════════════════════════════
# EMAIL ALERTS
# ═══════════════════════════════════════════════════════════════
def send_alert(msg: str):
    if not RESEND_API_KEY:
        return
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": "NEXYROTH Scalper <alerts@nexyroth.com>",
                "to": [ALERT_EMAIL],
                "subject": f"⚡ Scalper: {msg[:50]}",
                "text": msg,
            },
            timeout=10,
        )
    except:
        pass

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
    return {"active_positions": [], "total_trades": 0, "total_pnl": 0.0}

def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════
def main():
    log("=" * 60)
    log("NEXYROTH × AlgoPro Hybrid Scalper v2.0 — Scan Start")
    log("=" * 60)

    if not API_KEY or not SECRET_KEY:
        log("❌ Missing Bitunix API credentials")
        return

    # Load state
    state = load_state()
    active = state.get("active_positions", [])

    # Check balance
    balance = get_balance()
    log(f"  Balance: ${balance:.2f} | Active positions: {len(active)}/{MAX_POSITIONS}")

    if balance < MIN_BALANCE:
        log(f"  ⚠️ Balance ${balance:.2f} < ${MIN_BALANCE} minimum — skipping")
        save_state(state)
        return

    # Step 1: Manage trailing stops on existing positions
    if active:
        log("─── Managing Trailing Stops ───")
        manage_trailing_stops(state)

    # Step 2: Look for new signals if we have open slots
    active = state.get("active_positions", [])
    active_symbols = [p["symbol"] for p in active]

    if len(active) < MAX_POSITIONS:
        log("─── Scanning for New Signals ───")
        for symbol in ZERO_FEE_SYMBOLS:
            if symbol in active_symbols:
                continue
            if len(active) >= MAX_POSITIONS:
                break

            signal = get_signal(symbol)
            if signal:
                result = place_trade(
                    symbol=symbol,
                    direction=signal["direction"],
                    price=signal["price"],
                    atr=signal["atr"],
                    balance=balance,
                )
                if result:
                    active.append(result)
                    state["active_positions"] = active
                    save_state(state)
                    # Reduce available balance for next trade
                    balance = get_balance()
    else:
        log("  All slots filled — monitoring only")

    # Save final state
    save_state(state)

    # Summary
    history = load_trade_history()
    kelly = calc_kelly_fraction(history)
    log(f"─── Summary: {len(active)} active | {state.get('total_trades', 0)} total trades | Kelly={kelly:.3f} ───")
    log("")

if __name__ == "__main__":
    main()
