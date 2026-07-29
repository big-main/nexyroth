#!/usr/bin/env python3
"""
NEXYROTH Grid Bot v1.0
═══════════════════════
Places a grid of buy/sell limit orders within a price range on Bitunix zero-fee tokens.
Profits from sideways/ranging markets where price oscillates between levels.

Strategy:
  - Divides a price range into N grid levels
  - Places BUY orders below current price, SELL orders above
  - When a BUY fills, immediately places a SELL at the next grid level up
  - When a SELL fills, immediately places a BUY at the next grid level down
  - Each completed buy→sell cycle captures the grid spacing as profit

Config:
  - GRID_LEVELS: Number of grid lines (default 10)
  - GRID_RANGE_PCT: Total range as % of current price (default 2%)
  - AMOUNT_PER_GRID: USDT per grid order
  - Auto-detects best token based on lowest volatility (ranging = best for grid)

Schedule: Every 2 minutes via cron
"""

import os, sys, json, time, hashlib, uuid, hmac, requests
from typing import Optional, Dict, List
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
API_KEY    = os.getenv("BITUNIX_API_KEY", "")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "")
BASE_URL   = "https://fapi.bitunix.com"

# Grid parameters
GRID_LEVELS      = 8          # Number of grid lines
GRID_RANGE_PCT   = 0.015      # 1.5% total range (tight for scalping)
AMOUNT_PER_GRID  = 0.50       # $0.50 USDT per grid order (small account)
LEVERAGE         = 10
MAX_OPEN_ORDERS  = 16         # Max open orders at any time

# Zero-fee tokens to grid
GRID_TOKENS = ["SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]

# Precision maps
QTY_PRECISION = {
    "SOLUSDT": 2, "XRPUSDT": 1, "SUIUSDT": 1,
    "DOGEUSDT": 0, "LABUSDT": 1, "BUSDT": 1,
    "TONUSDT": 2, "SKYAIUSDT": 0, "DOGSUSDT": 0, "TSTUSDT": 0,
}
PRICE_PRECISION = {
    "SOLUSDT": 2, "XRPUSDT": 4, "SUIUSDT": 4,
    "DOGEUSDT": 5, "LABUSDT": 4, "BUSDT": 4,
    "TONUSDT": 4, "SKYAIUSDT": 5, "DOGSUSDT": 7, "TSTUSDT": 6,
}

# Paths
DATA_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "grid_bot_state.json")
LOG_FILE   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "grid_bot.log")

# Telegram
TG_TOKEN_FILE = os.path.expanduser("~/.secrets/telegram_bot_token")
TG_CHAT_FILE  = os.path.expanduser("~/.secrets/telegram_chat_id")

# ═══════════════════════════════════════════════════════════════
# LOGGING
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
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# BITUNIX AUTH
# ═══════════════════════════════════════════════════════════════
def load_keys():
    global API_KEY, SECRET_KEY
    if not API_KEY:
        try:
            API_KEY = open(os.path.expanduser("~/.secrets/bitunix_api_key")).read().strip()
            SECRET_KEY = open(os.path.expanduser("~/.secrets/bitunix_secret_key")).read().strip()
        except:
            pass

def sign_request(timestamp: str, nonce: str, query_str: str = "", body_str: str = "") -> str:
    digest_input = nonce + timestamp + API_KEY + query_str + body_str
    digest = hashlib.sha256(digest_input.encode()).hexdigest()
    sign_input = digest + SECRET_KEY
    return hashlib.sha256(sign_input.encode()).hexdigest()

def bitunix_get(path: str, params: dict = None) -> dict:
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    query_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    signature = sign_request(timestamp, nonce, query_str, "")
    headers = {
        "api-key": API_KEY,
        "sign": signature,
        "timestamp": timestamp,
        "nonce": nonce,
        "Content-Type": "application/json"
    }
    url = f"{BASE_URL}{path}"
    if query_str:
        url += f"?{query_str}"
    r = requests.get(url, headers=headers, timeout=10)
    return r.json()

def bitunix_post(path: str, body: dict) -> dict:
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    body_str = json.dumps(body, separators=(",", ":"))
    signature = sign_request(timestamp, nonce, "", body_str)
    headers = {
        "api-key": API_KEY,
        "sign": signature,
        "timestamp": timestamp,
        "nonce": nonce,
        "Content-Type": "application/json"
    }
    r = requests.post(f"{BASE_URL}{path}", headers=headers, data=body_str, timeout=10)
    return r.json()

# ═══════════════════════════════════════════════════════════════
# MARKET DATA
# ═══════════════════════════════════════════════════════════════
def get_ticker_price(symbol: str) -> Optional[float]:
    """Get current price from WS cache or REST."""
    # Try WS cache first
    try:
        ws_data = json.load(open("/tmp/nexyroth_ws_data.json"))
        if symbol in ws_data:
            age = time.time() - ws_data[symbol].get("ts", 0)
            if age < 60:
                return ws_data[symbol]["price"]
    except:
        pass
    # REST fallback
    try:
        r = requests.get(f"{BASE_URL}/api/v1/futures/market/tickers", timeout=10)
        data = r.json()
        for t in data.get("data", []):
            if t.get("symbol") == symbol:
                return float(t["lastPrice"])
    except:
        pass
    return None

def get_balance() -> float:
    resp = bitunix_get("/api/v1/futures/account", {"marginCoin": "USDT"})
    try:
        return float(resp["data"]["available"])
    except:
        return 0.0

# ═══════════════════════════════════════════════════════════════
# GRID LOGIC
# ═══════════════════════════════════════════════════════════════
def calculate_grid_levels(price: float, symbol: str) -> List[float]:
    """Calculate grid price levels centered around current price."""
    half_range = price * GRID_RANGE_PCT / 2
    low = price - half_range
    high = price + half_range
    step = (high - low) / (GRID_LEVELS - 1)
    prec = PRICE_PRECISION.get(symbol, 4)
    levels = [round(low + i * step, prec) for i in range(GRID_LEVELS)]
    return levels

def load_state() -> dict:
    try:
        return json.load(open(STATE_FILE))
    except:
        return {"grids": {}, "total_cycles": 0, "total_profit": 0.0}

def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def place_limit_order(symbol: str, side: str, price: float, qty: float) -> Optional[str]:
    """Place a limit order. Returns order ID or None."""
    prec = PRICE_PRECISION.get(symbol, 4)
    qty_prec = QTY_PRECISION.get(symbol, 2)
    body = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "LIMIT",
        "price": str(round(price, prec)),
        "qty": str(round(qty, qty_prec)),
        "leverage": str(LEVERAGE),
        "positionType": "CROSSED",
        "timeInForce": "GTC"
    }
    resp = bitunix_post("/api/v1/futures/order/create", body)
    if resp.get("code") == 0 and resp.get("data"):
        return resp["data"].get("orderId")
    else:
        log(f"  ⚠️ Order failed: {resp.get('msg', 'unknown')}")
        return None

def select_best_grid_token() -> Optional[str]:
    """Select the token with lowest recent volatility (best for grid)."""
    best = None
    lowest_vol = float("inf")
    for symbol in GRID_TOKENS:
        try:
            r = requests.get(f"{BASE_URL}/api/v1/futures/market/kline",
                params={"symbol": symbol, "klineType": "5m", "limit": "20"}, timeout=10)
            data = r.json().get("data", [])
            if len(data) < 10:
                continue
            # Calculate ATR as volatility proxy
            ranges = [float(k["high"]) - float(k["low"]) for k in data[-10:]]
            avg_range = sum(ranges) / len(ranges)
            price = float(data[-1]["close"])
            vol_pct = avg_range / price if price > 0 else 1.0
            if vol_pct < lowest_vol:
                lowest_vol = vol_pct
                best = symbol
        except:
            continue
    if best:
        log(f"  📊 Best grid token: {best} (vol={lowest_vol*100:.3f}%)")
    return best

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    load_keys()
    if not API_KEY:
        log("❌ No API key found")
        return

    state = load_state()
    balance = get_balance()
    log(f"🔲 Grid Bot v1.0 | Balance: ${balance:.2f} | Cycles: {state['total_cycles']}")

    if balance < 1.0:
        log("  ⚠️ Balance too low for grid ($1 minimum)")
        return

    # Select best token for grid
    symbol = select_best_grid_token()
    if not symbol:
        log("  ⚠️ No suitable token found")
        return

    price = get_ticker_price(symbol)
    if not price:
        log(f"  ⚠️ Can't get price for {symbol}")
        return

    # Calculate grid
    levels = calculate_grid_levels(price, symbol)
    qty_prec = QTY_PRECISION.get(symbol, 2)
    qty_per_level = round((AMOUNT_PER_GRID * LEVERAGE) / price, qty_prec)

    # Determine buy/sell levels
    buy_levels = [l for l in levels if l < price]
    sell_levels = [l for l in levels if l > price]

    log(f"  📐 Grid: {symbol} @ ${price} | {len(buy_levels)} buys, {len(sell_levels)} sells | Qty={qty_per_level}")

    # Check existing grid state
    grid_key = symbol
    if grid_key not in state["grids"]:
        state["grids"][grid_key] = {"orders": [], "last_price": price, "created": time.time()}

    # Place grid orders (limit to avoid spam)
    orders_placed = 0
    max_new = 4  # Place max 4 new orders per run

    for level in buy_levels[:max_new//2]:
        oid = place_limit_order(symbol, "BUY_OPEN", level, qty_per_level)
        if oid:
            state["grids"][grid_key]["orders"].append({
                "id": oid, "side": "BUY", "price": level, "qty": qty_per_level
            })
            orders_placed += 1
            log(f"    📗 BUY @ ${level}")

    for level in sell_levels[:max_new//2]:
        oid = place_limit_order(symbol, "SELL_OPEN", level, qty_per_level)
        if oid:
            state["grids"][grid_key]["orders"].append({
                "id": oid, "side": "SELL", "price": level, "qty": qty_per_level
            })
            orders_placed += 1
            log(f"    📕 SELL @ ${level}")

    if orders_placed > 0:
        send_telegram(f"🔲 <b>Grid Bot</b>\n{symbol} @ ${price}\n{orders_placed} orders placed\nRange: ${levels[0]:.4f} - ${levels[-1]:.4f}")

    save_state(state)
    log(f"  ✅ {orders_placed} orders placed | Total grid cycles: {state['total_cycles']}")

if __name__ == "__main__":
    main()
