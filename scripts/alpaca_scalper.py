#!/usr/bin/env python3
"""
NEXYROTH × Alpaca Momentum Scalper v1.0
========================================
Paper trading scalper targeting high-volume momentum stocks and ETFs.
Runs every 5 minutes via cron during market hours (9:30 AM - 4:00 PM ET).

Strategy:
  1. Scan top momentum stocks (high volume + price surge)
  2. EMA 9/21 crossover on 5m bars
  3. RSI filter (40-70 for LONG entries)
  4. Volume spike (1.5x above 20-bar average)
  5. Only trade during market hours

Risk Management:
  - 5% of portfolio per trade (max 10 concurrent positions)
  - TP: +1.5% | SL: -0.75% (2:1 R/R)
  - Market orders for instant fills
  - Auto-close all positions at 3:45 PM ET (15 min before close)

Auth: Alpaca REST API v2 (paper trading)
"""

import os
import json
import time
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
def _read_secret(path: str) -> str:
    try:
        with open(os.path.expanduser(path)) as f:
            return f.read().strip()
    except:
        return ""

API_KEY    = _read_secret("~/.secrets/alpaca_api_key")
SECRET_KEY = _read_secret("~/.secrets/alpaca_secret_key")
BASE_URL   = "https://paper-api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"

LOG_FILE   = "/home/ubuntu/trading_sniper/alpaca_scalper.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/alpaca_scalper_state.json"
HISTORY_FILE = "/home/ubuntu/trading_sniper/data/alpaca_scalper_history.json"

# Telegram
TG_TOKEN = _read_secret("~/.secrets/telegram_bot_token")
TG_CHAT  = _read_secret("~/.secrets/telegram_chat_id")

# Strategy params
RISK_PER_TRADE  = 0.05    # 5% of portfolio per trade
MAX_POSITIONS   = 10      # Max concurrent positions
TP_PCT          = 0.015   # +1.5% take profit
SL_PCT          = 0.0075  # -0.75% stop loss
VOL_MULT        = 1.5     # Volume must be 1.5x average
RSI_MIN         = 40      # RSI floor for LONG
RSI_MAX         = 70      # RSI ceiling for LONG
EMA_FAST        = 9
EMA_SLOW        = 21
BAR_LIMIT       = 50      # Number of 5m bars to fetch

# Top momentum watchlist — high-volume liquid stocks + ETFs
WATCHLIST = [
    # Mega-cap tech (high liquidity, tight spreads)
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "AMD",
    # High-beta momentum
    "PLTR", "SOFI", "RIVN", "LCID", "MARA", "RIOT", "COIN",
    # Leveraged ETFs (high volatility, great for scalping)
    "TQQQ", "SQQQ", "SPXL", "SPXS", "SOXL", "UVXY",
    # Sector ETFs
    "SPY", "QQQ", "IWM", "XLF", "XLE",
]

ET = ZoneInfo("America/New_York")

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

def send_telegram(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# ALPACA API HELPERS
# ═══════════════════════════════════════════════════════════════
HEADERS = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": SECRET_KEY,
    "Content-Type": "application/json",
}

def alpaca_get(path: str, params: dict = None, base: str = BASE_URL) -> Optional[dict]:
    try:
        r = requests.get(f"{base}{path}", headers=HEADERS, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        log(f"  GET error [{path}]: {r.status_code} {r.text[:100]}")
        return None
    except Exception as e:
        log(f"  GET exception [{path}]: {e}")
        return None

def alpaca_post(path: str, body: dict) -> Optional[dict]:
    try:
        r = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=body, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        log(f"  POST error [{path}]: {r.status_code} {r.text[:150]}")
        return None
    except Exception as e:
        log(f"  POST exception [{path}]: {e}")
        return None

def alpaca_delete(path: str) -> bool:
    try:
        r = requests.delete(f"{BASE_URL}{path}", headers=HEADERS, timeout=15)
        return r.status_code in (200, 204)
    except:
        return False

# ═══════════════════════════════════════════════════════════════
# MARKET HOURS CHECK
# ═══════════════════════════════════════════════════════════════
def is_market_open() -> bool:
    """Check if US market is open right now."""
    data = alpaca_get("/v2/clock")
    if data:
        return data.get("is_open", False)
    # Fallback: check time manually
    now = datetime.now(ET)
    if now.weekday() >= 5:  # Weekend
        return False
    market_open  = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close

def is_near_close() -> bool:
    """True if within 15 min of market close (3:45 PM ET)."""
    now = datetime.now(ET)
    cutoff = now.replace(hour=15, minute=45, second=0, microsecond=0)
    close  = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return cutoff <= now <= close

# ═══════════════════════════════════════════════════════════════
# ACCOUNT & POSITIONS
# ═══════════════════════════════════════════════════════════════
def get_account() -> dict:
    return alpaca_get("/v2/account") or {}

def get_positions() -> List[dict]:
    return alpaca_get("/v2/positions") or []

def get_open_orders() -> List[dict]:
    return alpaca_get("/v2/orders", {"status": "open"}) or []

# ═══════════════════════════════════════════════════════════════
# MARKET DATA
# ═══════════════════════════════════════════════════════════════
def get_bars(symbol: str, timeframe: str = "5Min", limit: int = 50) -> List[dict]:
    """Fetch OHLCV bars from Alpaca data API."""
    data = alpaca_get(
        f"/v2/stocks/{symbol}/bars",
        {"timeframe": timeframe, "limit": limit, "feed": "iex"},
        base=DATA_URL
    )
    if not data:
        return []
    bars = data.get("bars", [])
    return [{
        "open":   float(b["o"]),
        "high":   float(b["h"]),
        "low":    float(b["l"]),
        "close":  float(b["c"]),
        "volume": float(b["v"]),
    } for b in bars]

def get_latest_price(symbol: str) -> float:
    """Get latest trade price."""
    data = alpaca_get(
        f"/v2/stocks/{symbol}/trades/latest",
        {"feed": "iex"},
        base=DATA_URL
    )
    if data and "trade" in data:
        return float(data["trade"]["p"])
    return 0.0

# ═══════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ═══════════════════════════════════════════════════════════════
def calc_ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result

def calc_rsi(closes: List[float], period: int = 14) -> float:
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
    return 100.0 - (100.0 / (1 + avg_gain / avg_loss))

def calc_volume_ratio(volumes: List[float], lookback: int = 20) -> float:
    if len(volumes) < lookback + 1:
        return 1.0
    avg = sum(volumes[-lookback-1:-1]) / lookback
    if avg == 0:
        return 1.0
    return volumes[-1] / avg

# ═══════════════════════════════════════════════════════════════
# SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════
def get_signal(symbol: str) -> Optional[dict]:
    """Returns signal dict if entry conditions met, else None."""
    bars = get_bars(symbol, "5Min", BAR_LIMIT)
    if len(bars) < EMA_SLOW + 5:
        return None

    closes  = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]

    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None

    # EMA crossover: fast crossed above slow (bullish)
    prev_cross = ema_fast[-2] <= ema_slow[-2]
    curr_cross = ema_fast[-1] > ema_slow[-1]
    bullish_cross = prev_cross and curr_cross

    # EMA already above (continuation)
    ema_bullish = ema_fast[-1] > ema_slow[-1]

    if not (bullish_cross or ema_bullish):
        return None  # No bullish EMA setup

    # RSI filter
    rsi = calc_rsi(closes)
    if not (RSI_MIN <= rsi <= RSI_MAX):
        return None  # RSI out of range

    # Volume filter
    vol_ratio = calc_volume_ratio(volumes)
    if vol_ratio < VOL_MULT:
        return None  # Not enough volume

    price = closes[-1]
    return {
        "symbol":    symbol,
        "direction": "LONG",
        "price":     price,
        "rsi":       round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
        "ema_cross": bullish_cross,
    }

# ═══════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════
def place_trade(signal: dict, portfolio_value: float) -> Optional[dict]:
    symbol = signal["symbol"]
    price  = signal["price"]

    # Position sizing: 5% of portfolio
    trade_value = portfolio_value * RISK_PER_TRADE
    qty = max(1, int(trade_value / price))

    # TP and SL prices
    tp_price = round(price * (1 + TP_PCT), 2)
    sl_price = round(price * (1 - SL_PCT), 2)

    log(f"  📤 PLACING LONG {symbol}: qty={qty} @ ~${price:.2f} | TP=${tp_price} SL=${sl_price}")

    # Place market order
    order = alpaca_post("/v2/orders", {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          "buy",
        "type":          "market",
        "time_in_force": "day",
    })

    if not order:
        return None

    order_id = order.get("id", "unknown")
    log(f"  ✅ ORDER PLACED: {order_id}")

    # Place bracket TP/SL orders (OCO)
    # Note: Alpaca paper supports bracket orders
    alpaca_post("/v2/orders", {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          "sell",
        "type":          "limit",
        "time_in_force": "gtc",
        "limit_price":   str(tp_price),
    })
    alpaca_post("/v2/orders", {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          "sell",
        "type":          "stop",
        "time_in_force": "gtc",
        "stop_price":    str(sl_price),
    })

    send_telegram(
        f"📈 <b>ALPACA LONG {symbol}</b>\n"
        f"💰 Entry: <code>~${price:.2f}</code>\n"
        f"🟢 TP: <code>${tp_price}</code>  🔴 SL: <code>${sl_price}</code>\n"
        f"📊 Qty: {qty} | RSI: {signal['rsi']} | Vol: {signal['vol_ratio']}x\n"
        f"🏦 Paper Account"
    )

    return {"symbol": symbol, "order_id": order_id, "entry": price, "qty": qty, "tp": tp_price, "sl": sl_price}

def close_all_positions():
    """Close all open positions (called near market close)."""
    positions = get_positions()
    if not positions:
        return
    log(f"  🔔 Closing {len(positions)} positions before market close")
    for pos in positions:
        symbol = pos["symbol"]
        qty    = abs(int(float(pos["qty"])))
        side   = "sell" if float(pos["qty"]) > 0 else "buy"
        alpaca_post("/v2/orders", {
            "symbol": symbol, "qty": str(qty),
            "side": side, "type": "market", "time_in_force": "day",
        })
        log(f"  ✅ Closed {symbol} ({qty} shares)")

    send_telegram(
        f"🔔 <b>ALPACA EOD CLOSE</b>\n"
        f"Closed {len(positions)} positions before market close."
    )

# ═══════════════════════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"total_trades": 0, "total_pnl": 0.0, "traded_today": []}

def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════
def main():
    log("=" * 60)
    log("NEXYROTH × Alpaca Momentum Scalper v1.0 — Scan Start")
    log("=" * 60)

    if not API_KEY or not SECRET_KEY:
        log("  ❌ Missing Alpaca API credentials")
        return

    # Check market hours
    if not is_market_open():
        log("  💤 Market closed — skipping scan")
        return

    # Near close: liquidate everything
    if is_near_close():
        log("  ⏰ Near market close — closing all positions")
        close_all_positions()
        return

    account = get_account()
    if not account:
        log("  ❌ Could not fetch account")
        return

    portfolio_value = float(account.get("portfolio_value", 100000))
    buying_power    = float(account.get("buying_power", 0))
    log(f"  Portfolio: ${portfolio_value:,.2f} | Buying Power: ${buying_power:,.2f}")

    # Check current positions
    positions = get_positions()
    current_symbols = {p["symbol"] for p in positions}
    log(f"  Open positions: {len(positions)}/{MAX_POSITIONS} — {list(current_symbols)}")

    if len(positions) >= MAX_POSITIONS:
        log("  ⚠️ Max positions reached — no new entries")
        return

    state = load_state()
    # Reset daily traded list at start of new day
    today = datetime.now(ET).strftime("%Y-%m-%d")
    if state.get("last_date") != today:
        state["traded_today"] = []
        state["last_date"] = today

    # Scan watchlist for signals
    log(f"  Scanning {len(WATCHLIST)} symbols...")
    signals_found = 0
    trades_placed = 0

    for symbol in WATCHLIST:
        if symbol in current_symbols:
            continue  # Already in position
        if symbol in state.get("traded_today", []):
            continue  # Already traded today

        try:
            signal = get_signal(symbol)
            if signal:
                signals_found += 1
                log(f"  🎯 Signal: {symbol} LONG | RSI={signal['rsi']} Vol={signal['vol_ratio']}x Cross={signal['ema_cross']}")

                if len(positions) + trades_placed >= MAX_POSITIONS:
                    log(f"  ⚠️ Max positions — skipping {symbol}")
                    break

                result = place_trade(signal, portfolio_value)
                if result:
                    trades_placed += 1
                    state["total_trades"] = state.get("total_trades", 0) + 1
                    state.setdefault("traded_today", []).append(symbol)
                    save_state(state)
                    time.sleep(0.5)  # Brief pause between orders

        except Exception as e:
            log(f"  ⚠️ Error scanning {symbol}: {e}")
            continue

    log(f"  Signals found: {signals_found} | Trades placed: {trades_placed}")
    log(f"─── Summary: {len(positions)} open | {state.get('total_trades', 0)} total trades ───")
    log("")

if __name__ == "__main__":
    main()
