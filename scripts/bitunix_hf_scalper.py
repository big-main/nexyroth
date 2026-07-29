#!/usr/bin/env python3
"""
NEXYROTH HF Scalper v1.0
=========================
High-frequency momentum scalper for the 10 zero-fee tokens on Bitunix.
Designed to trade CONTINUOUSLY for small consistent profits.

Strategy (2-condition entry — fires frequently):
  1. EMA 9 direction (slope determines LONG/SHORT bias)
  2. RSI momentum (not extreme in the wrong direction)
  Entry fires on ANY 3-candle momentum burst in the EMA direction.

Risk Management:
  - Tight TP: +0.4% (10x leverage = +4% account per win)
  - Tight SL: -0.2% (10x leverage = -2% account per loss)
  - 2:1 reward/risk ratio
  - Fixed 20% balance per trade (aggressive compounding)
  - Max 5 concurrent positions (one per top-volume token)
  - 3-minute cooldown per symbol after close (avoid chop)
  - Runs every 30 seconds via cron (2x per minute)

Complements the 7-filter confluence scalper (bitunix_scalper.py).
Auth: Double-SHA256 (same as all other NEXYROTH scripts)
"""

import os
import json
import time
import uuid
import hashlib
import requests
import math
from datetime import datetime, timezone
from typing import Optional, List, Dict

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
BITUNIX_API  = "https://fapi.bitunix.com"
WS_DATA_FILE = "/tmp/nexyroth_ws_data.json"
LOG_FILE     = "/home/ubuntu/trading_sniper/bitunix_hf_scalper.log"
STATE_FILE   = "/home/ubuntu/trading_sniper/data/hf_scalper_state.json"
HISTORY_FILE = "/home/ubuntu/trading_sniper/data/hf_scalper_history.json"

# ─── Secrets ───────────────────────────────────────────────────
def _read_secret(env_var: str, path: str) -> str:
    val = os.getenv(env_var, "")
    if val:
        return val
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""

API_KEY    = _read_secret("BITUNIX_API_KEY",    "/home/ubuntu/.secrets/bitunix_api_key")
SECRET_KEY = _read_secret("BITUNIX_SECRET_KEY", "/home/ubuntu/.secrets/bitunix_secret_key")
ALERT_EMAIL = _read_secret("ALERT_EMAIL", "/home/ubuntu/.secrets/alert_email")
RESEND_API_KEY = _read_secret("RESEND_API_KEY", "/home/ubuntu/.secrets/resend_api_key")
TELEGRAM_BOT_TOKEN = _read_secret("TELEGRAM_BOT_TOKEN", "/home/ubuntu/.secrets/telegram_bot_token")
TELEGRAM_CHAT_ID   = _read_secret("TELEGRAM_CHAT_ID",   "/home/ubuntu/.secrets/telegram_chat_id")

# ─── HF Strategy Parameters ────────────────────────────────────
ZERO_FEE_TOKENS = [
    "SOLUSDT", "XRPUSDT", "SUIUSDT", "DOGEUSDT", "TSTUSDT",
    "LABUSDT", "BUSDT",   "TONUSDT", "SKYAIUSDT","DOGSUSDT",
]

LEVERAGE         = 10
RISK_PCT         = 0.20    # 20% of balance per trade
MAX_POSITIONS    = 5       # Max concurrent HF positions
CANDLE_INTERVAL  = "1m"
CANDLE_LIMIT     = 30      # Only need 30 candles for HF logic

# Entry thresholds
EMA_FAST_PERIOD  = 9
MOMENTUM_BARS    = 3       # Consecutive candles in direction required
RSI_PERIOD       = 14
RSI_LONG_MAX     = 75      # Don't LONG if RSI already overbought
RSI_SHORT_MIN    = 25      # Don't SHORT if RSI already oversold

# Exit thresholds (tight for HF)
TP_PCT           = 0.006   # +0.6% price move = TP (10x = +6% account) — 3:1 ratio
SL_PCT           = 0.002   # -0.2% price move = SL (10x = -2% account)
MIN_CANDLE_BODY  = 0.0005  # Min avg candle body pct (0.05%) — filters weak chop

# Cooldown: don't re-enter same symbol for N seconds after close
COOLDOWN_SECS    = 180     # 3 minutes

# Min balance to trade
MIN_BALANCE      = 2.0

# Precision maps (same as confluence scalper)
QTY_PRECISION = {
    "SOLUSDT": 2, "XRPUSDT": 1, "SUIUSDT": 1, "DOGEUSDT": 0,
    "TSTUSDT": 0, "LABUSDT": 0, "BUSDT": 0,   "TONUSDT": 2,
    "SKYAIUSDT": 0, "DOGSUSDT": 0,
}
PRICE_PRECISION = {
    "SOLUSDT": 2, "XRPUSDT": 4, "SUIUSDT": 4, "DOGEUSDT": 5,
    "TSTUSDT": 6, "LABUSDT": 4, "BUSDT": 4,   "TONUSDT": 4,
    "SKYAIUSDT": 6, "DOGSUSDT": 8,
}
MIN_QTY_MAP = {
    "SOLUSDT": 0.01, "XRPUSDT": 1.0, "SUIUSDT": 1.0, "DOGEUSDT": 1.0,
    "TSTUSDT": 1.0,  "LABUSDT": 1.0, "BUSDT": 1.0,   "TONUSDT": 0.01,
    "SKYAIUSDT": 1.0, "DOGSUSDT": 1.0,
}

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════
# ALERTS
# ═══════════════════════════════════════════════════════════════
def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception:
        pass

def send_alert(msg: str):
    send_telegram(msg)
    if not RESEND_API_KEY:
        return
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": "NEXYROTH HF <alerts@nexyroth.com>",
                "to": [ALERT_EMAIL],
                "subject": f"⚡ HF: {msg[:50]}",
                "text": msg,
            },
            timeout=10,
        )
    except Exception:
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
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("code") == 0:
            return data.get("data")
        return None
    except Exception:
        return None

def bitunix_post(path: str, body: dict) -> Optional[dict]:
    try:
        body_str = json.dumps(body, separators=(",", ":"))
        headers  = make_headers(body=body_str)
        r = requests.post(f"{BITUNIX_API}{path}", headers=headers, data=body_str, timeout=10)
        data = r.json()
        if data.get("code") == 0:
            return data.get("data")
        log(f"  ❌ API error: {data.get('msg', 'unknown')} (code={data.get('code')})")
        return None
    except Exception as e:
        log(f"  ❌ POST exception: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# MARKET DATA
# ═══════════════════════════════════════════════════════════════
def get_klines(symbol: str, interval: str = "1m", limit: int = 30) -> List[dict]:
    data = bitunix_get("/api/v1/futures/market/kline", {
        "symbol": symbol, "interval": interval, "limit": limit
    })
    if not data or not isinstance(data, list):
        return []
    candles = []
    for k in data:
        try:
            if isinstance(k, dict):
                candles.append({
                    "open":   float(k.get("open", 0)),
                    "high":   float(k.get("high", 0)),
                    "low":    float(k.get("low", 0)),
                    "close":  float(k.get("close", 0)),
                    "volume": float(k.get("quoteVol", k.get("baseVol", 0))),
                    "time":   int(k.get("time", 0)),
                })
            else:
                candles.append({
                    "open":   float(k[1]),
                    "high":   float(k[2]),
                    "low":    float(k[3]),
                    "close":  float(k[4]),
                    "volume": float(k[5]),
                    "time":   int(k[0]) if len(k) > 0 else 0,
                })
        except Exception:
            continue
    # Sort oldest → newest
    candles.sort(key=lambda c: c.get("time", 0))
    return candles

def get_balance() -> float:
    data = bitunix_get("/api/v1/futures/account", {"marginCoin": "USDT"})
    if not data:
        return 0.0
    return float(data.get("available", 0) or 0)

def get_open_positions() -> List[dict]:
    data = bitunix_get("/api/v1/futures/position/get_pending_positions")
    if not data:
        return []
    return data if isinstance(data, list) else data.get("positionList", [])

# ═══════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════
def calc_ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_momentum_direction(candles: List[dict], bars: int = 3) -> Optional[str]:
    """
    Returns 'LONG' if last N candles are all bullish (close > open).
    Returns 'SHORT' if last N candles are all bearish (close < open).
    Returns None if mixed.
    """
    if len(candles) < bars:
        return None
    recent = candles[-bars:]
    if all(c["close"] > c["open"] for c in recent):
        return "LONG"
    if all(c["close"] < c["open"] for c in recent):
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
        except Exception:
            pass
    return {
        "active_positions": [],
        "cooldowns": {},
        "total_trades": 0,
        "total_pnl": 0.0,
    }

def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_history() -> List[dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_history(history: List[dict]):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history[-200:], f, indent=2)

def is_in_cooldown(symbol: str, state: dict) -> bool:
    cooldowns = state.get("cooldowns", {})
    last_close = cooldowns.get(symbol, 0)
    return (time.time() - last_close) < COOLDOWN_SECS

def set_cooldown(symbol: str, state: dict):
    if "cooldowns" not in state:
        state["cooldowns"] = {}
    state["cooldowns"][symbol] = time.time()

# ═══════════════════════════════════════════════════════════════
# HF SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════
def get_hf_signal(symbol: str) -> Optional[dict]:
    """
    HF entry: 2 conditions only.
    1. EMA 9 slope agrees with momentum direction
    2. RSI not at extreme in the wrong direction
    3. 3 consecutive momentum candles in the direction
    """
    candles = get_klines(symbol, CANDLE_INTERVAL, CANDLE_LIMIT)
    if len(candles) < EMA_FAST_PERIOD + MOMENTUM_BARS + 2:
        return None

    closes = [c["close"] for c in candles]
    current_price = closes[-1]

    # Condition 1: 3-candle momentum burst
    direction = get_momentum_direction(candles, MOMENTUM_BARS)
    if direction is None:
        return None

    # Condition 2: EMA 9 slope agrees
    ema9 = calc_ema(closes, EMA_FAST_PERIOD)
    if len(ema9) < 2:
        return None
    ema_rising = ema9[-1] > ema9[-2]
    if direction == "LONG" and not ema_rising:
        return None   # EMA falling — skip LONG
    if direction == "SHORT" and ema_rising:
        return None   # EMA rising — skip SHORT

    # Condition 3: RSI not at extreme
    rsi = calc_rsi(closes, RSI_PERIOD)
    if direction == "LONG" and rsi > RSI_LONG_MAX:
        return None   # Already overbought
    if direction == "SHORT" and rsi < RSI_SHORT_MIN:
        return None   # Already oversold

    # Condition 4: Momentum strength — avg candle body must be meaningful (not chop)
    recent_candles = candles[-(MOMENTUM_BARS + 1):-1]
    avg_body = 0.0
    if recent_candles:
        avg_body = sum(
            abs(c["close"] - c["open"]) / c["open"]
            for c in recent_candles if c["open"] > 0
        ) / len(recent_candles)
    if avg_body < MIN_CANDLE_BODY:
        return None   # Candles too small — chop, skip

    # Signal confirmed
    log(f"  ⚡ HF {symbol}: {direction} | EMA9={'↑' if ema_rising else '↓'} | RSI={rsi:.1f} | Body={avg_body*100:.3f}% | Price={current_price}")
    return {
        "direction": direction,
        "price": current_price,
        "rsi": rsi,
        "avg_body": avg_body,
    }

# ═══════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════
def place_hf_trade(symbol: str, direction: str, price: float, balance: float) -> Optional[dict]:
    """Place a tight TP/SL HF scalp trade."""
    risk_usdt    = balance * RISK_PCT
    position_val = risk_usdt * LEVERAGE
    qty          = position_val / price

    qty_prec   = QTY_PRECISION.get(symbol, 2)
    price_prec = PRICE_PRECISION.get(symbol, 4)
    min_qty    = MIN_QTY_MAP.get(symbol, 1.0)

    if qty < min_qty:
        needed = (min_qty * price) / LEVERAGE / RISK_PCT
        if needed < balance * 3:
            qty = min_qty
        else:
            log(f"  ⚠️ {symbol}: qty {qty:.4f} < min {min_qty}, balance too low")
            return None

    qty = round(qty, qty_prec)
    if qty_prec == 0:
        qty = int(qty)

    if direction == "LONG":
        side     = "BUY"
        tp_price = round(price * (1 + TP_PCT), price_prec)
        sl_price = round(price * (1 - SL_PCT), price_prec)
    else:
        side     = "SELL"
        tp_price = round(price * (1 - TP_PCT), price_prec)
        sl_price = round(price * (1 + SL_PCT), price_prec)

    order_body = {
        "symbol":       symbol,
        "side":         side,
        "tradeSide":    "OPEN",
        "orderType":    "MARKET",
        "qty":          str(qty),
        "leverage":     str(LEVERAGE),
        "positionType": 1,
        "tpPrice":      str(tp_price),
        "slPrice":      str(sl_price),
    }

    log(f"  📤 HF {direction} {symbol}: qty={qty} @ ~{price} | TP={tp_price} SL={sl_price}")
    result = bitunix_post("/api/v1/futures/trade/place_order", order_body)
    if result:
        order_id = result.get("orderId", "unknown")
        log(f"  ✅ HF ORDER: {order_id}")
        send_alert(
            f"⚡ <b>HF {direction} {symbol}</b>\n"
            f"💰 Entry: <code>~{price}</code>\n"
            f"🟢 TP: <code>{tp_price}</code>  🔴 SL: <code>{sl_price}</code>\n"
            f"📊 Qty: {qty} | Risk: {RISK_PCT*100:.0f}% | Lev: {LEVERAGE}x"
        )
        return {
            "symbol":      symbol,
            "direction":   direction,
            "entry_price": price,
            "qty":         qty,
            "tp":          tp_price,
            "sl":          sl_price,
            "order_id":    order_id,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }
    return None

# ═══════════════════════════════════════════════════════════════
# POSITION MONITORING
# ═══════════════════════════════════════════════════════════════
def monitor_positions(state: dict):
    """Check active HF positions against live prices; close if TP/SL hit."""
    active = state.get("active_positions", [])
    if not active:
        return

    for pos in active[:]:
        symbol    = pos["symbol"]
        direction = pos["direction"]
        entry     = pos["entry_price"]
        tp        = pos["tp"]
        sl        = pos["sl"]

        # Get current price
        candles = get_klines(symbol, "1m", 3)
        if not candles:
            continue
        current = candles[-1]["close"]

        hit_tp = (direction == "LONG" and current >= tp) or (direction == "SHORT" and current <= tp)
        hit_sl = (direction == "LONG" and current <= sl) or (direction == "SHORT" and current >= sl)

        if hit_tp or hit_sl:
            reason = "TP" if hit_tp else "SL"
            pnl_pct = (current - entry) / entry if direction == "LONG" else (entry - current) / entry
            pnl_usdt = pnl_pct * pos["qty"] * entry

            log(f"  {'✅' if hit_tp else '❌'} HF {reason} {symbol} {direction} | Entry={entry} Exit={current} | PnL={pnl_pct*100:+.2f}%")

            # Close position via market order
            close_body = {
                "symbol":       symbol,
                "side":         "SELL" if direction == "LONG" else "BUY",
                "tradeSide":    "CLOSE",
                "orderType":    "MARKET",
                "qty":          str(pos["qty"]),
                "positionType": 1,
            }
            bitunix_post("/api/v1/futures/trade/place_order", close_body)

            # Record trade
            history = load_history()
            history.append({
                "symbol":      symbol,
                "direction":   direction,
                "entry":       entry,
                "exit":        current,
                "pnl":         pnl_pct,
                "pnl_usdt":    pnl_usdt,
                "reason":      reason,
                "timestamp":   datetime.now(timezone.utc).isoformat(),
            })
            save_history(history)

            # Update state
            active.remove(pos)
            state["total_trades"] = state.get("total_trades", 0) + 1
            state["total_pnl"]    = state.get("total_pnl", 0) + pnl_pct
            set_cooldown(symbol, state)

            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            send_alert(
                f"{pnl_emoji} <b>HF CLOSED {symbol}</b>\n"
                f"📍 {direction} | Entry: <code>{entry}</code> → Exit: <code>{current}</code>\n"
                f"💰 PnL: <b>{pnl_pct*100:+.2f}%</b> ({pnl_usdt:+.4f} USDT) [{reason}]\n"
                f"📈 HF Trades: {state['total_trades']}"
            )

    state["active_positions"] = active

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    log("=" * 60)
    log("NEXYROTH HF Scalper v1.0 — Scan Start")
    log("=" * 60)

    if not API_KEY or not SECRET_KEY:
        log("  ❌ No API credentials — exiting")
        return

    state   = load_state()
    balance = get_balance()

    if balance < MIN_BALANCE:
        log(f"  ⚠️ Balance ${balance:.2f} below minimum ${MIN_BALANCE} — skipping")
        save_state(state)
        return

    active_count = len(state.get("active_positions", []))
    log(f"  Balance: ${balance:.2f} | HF Active: {active_count}/{MAX_POSITIONS}")

    # Step 1: Monitor existing positions for TP/SL
    monitor_positions(state)

    # Step 2: Scan for new entries
    active_symbols = {p["symbol"] for p in state.get("active_positions", [])}
    active_count   = len(state.get("active_positions", []))

    if active_count < MAX_POSITIONS:
        log("─── HF Scanning for Entries ───")
        for symbol in ZERO_FEE_TOKENS:
            if active_count >= MAX_POSITIONS:
                break
            if symbol in active_symbols:
                continue
            if is_in_cooldown(symbol, state):
                log(f"  ⏳ {symbol}: cooldown active")
                continue

            signal = get_hf_signal(symbol)
            if signal:
                trade = place_hf_trade(symbol, signal["direction"], signal["price"], balance)
                if trade:
                    state["active_positions"].append(trade)
                    active_symbols.add(symbol)
                    active_count += 1
                    # Refresh balance after trade
                    balance = get_balance()
    else:
        log(f"  ⏸ Max HF positions ({MAX_POSITIONS}) reached — monitoring only")

    active_count = len(state.get("active_positions", []))
    log(f"─── HF Summary: {active_count} active | {state.get('total_trades', 0)} total | PnL={state.get('total_pnl', 0)*100:.2f}% ───")
    save_state(state)

if __name__ == "__main__":
    main()
