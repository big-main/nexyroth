#!/usr/bin/env python3
"""
NEXYROTH Bitunix DCA Bot v1.0
═════════════════════════════
Dollar-Cost Averages into zero-fee crypto futures on dips.
Opens LONG positions when price drops from recent high, adds on further drops.
Closes all when recovery target hit.

Strategy:
  - Monitors zero-fee tokens for 2%+ dip from 4h high
  - Opens LONG with 10x leverage on first dip trigger
  - Adds to position on each additional 1.5% drop (max 3 DCA levels)
  - Closes all when price recovers 3% above average entry
  - Uses tight SL at -4% from avg entry as safety net

Schedule: Every 5 minutes via cron
"""

import os, sys, json, time, hashlib, uuid, requests
from datetime import datetime
from typing import Optional, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from zero_fee_config import ZERO_FEE_TOKENS, QTY_PRECISION, PRICE_PRECISION, MIN_QTY, CRYPTO_TOKENS
except:
    CRYPTO_TOKENS = ["SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "ADAUSDT", "HYPEUSDT"]
    QTY_PRECISION = {"SOLUSDT": 2, "XRPUSDT": 1, "DOGEUSDT": 0, "SUIUSDT": 1, "ADAUSDT": 0, "HYPEUSDT": 2}
    PRICE_PRECISION = {"SOLUSDT": 2, "XRPUSDT": 4, "DOGEUSDT": 5, "SUIUSDT": 4, "ADAUSDT": 4, "HYPEUSDT": 3}
    MIN_QTY = {"SOLUSDT": 0.01, "XRPUSDT": 1, "DOGEUSDT": 1, "SUIUSDT": 1, "ADAUSDT": 1, "HYPEUSDT": 0.01}

BASE_URL = "https://fapi.bitunix.com"

# DCA Config
DIP_TRIGGER_PCT   = 0.02    # 2% drop from 4h high = first entry
DCA_STEP_PCT      = 0.015   # 1.5% additional drop = add to position
RECOVERY_TARGET   = 0.03    # 3% above avg = close all
SAFETY_SL_PCT     = 0.04    # 4% below avg = emergency close
MAX_DCA_LEVELS    = 3
AMOUNT_PER_DCA    = 0.50    # $0.50 per DCA entry (small account)
LEVERAGE          = 10

# Paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "bitunix_dca_state.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bitunix_dca.log")

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
# BITUNIX AUTH
# ═══════════════════════════════════════════════════════════════
API_KEY = ""
SECRET_KEY = ""

def load_keys():
    global API_KEY, SECRET_KEY
    try:
        API_KEY = open(os.path.expanduser("~/.secrets/bitunix_api_key")).read().strip()
        SECRET_KEY = open(os.path.expanduser("~/.secrets/bitunix_secret_key")).read().strip()
    except:
        pass

def sign_request(timestamp, nonce, query_str="", body_str=""):
    digest_input = nonce + timestamp + API_KEY + query_str + body_str
    digest = hashlib.sha256(digest_input.encode()).hexdigest()
    return hashlib.sha256((digest + SECRET_KEY).encode()).hexdigest()

def bitunix_get(path, params=None):
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    query_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    sig = sign_request(timestamp, nonce, query_str, "")
    headers = {"api-key": API_KEY, "sign": sig, "timestamp": timestamp, "nonce": nonce, "Content-Type": "application/json"}
    url = f"{BASE_URL}{path}" + (f"?{query_str}" if query_str else "")
    return requests.get(url, headers=headers, timeout=10).json()

def bitunix_post(path, body):
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    body_str = json.dumps(body, separators=(",", ":"))
    sig = sign_request(timestamp, nonce, "", body_str)
    headers = {"api-key": API_KEY, "sign": sig, "timestamp": timestamp, "nonce": nonce, "Content-Type": "application/json"}
    return requests.post(f"{BASE_URL}{path}", headers=headers, data=body_str, timeout=10).json()

# ═══════════════════════════════════════════════════════════════
# MARKET DATA
# ═══════════════════════════════════════════════════════════════
def get_price(symbol):
    try:
        ws_data = json.load(open("/tmp/nexyroth_ws_data.json"))
        if symbol in ws_data and time.time() - ws_data[symbol].get("ts", 0) < 60:
            return ws_data[symbol]["price"]
    except:
        pass
    try:
        r = requests.get(f"{BASE_URL}/api/v1/futures/market/tickers", timeout=10)
        for t in r.json().get("data", []):
            if t.get("symbol") == symbol:
                return float(t["lastPrice"])
    except:
        pass
    return None

def get_4h_high(symbol):
    """Get highest price in last 4 hours (48 x 5m candles)."""
    try:
        r = requests.get(f"{BASE_URL}/api/v1/futures/market/kline",
            params={"symbol": symbol, "klineType": "5m", "limit": "48"}, timeout=10)
        data = r.json().get("data", [])
        if data:
            return max(float(k["high"]) for k in data)
    except:
        pass
    return None

def get_balance():
    resp = bitunix_get("/api/v1/futures/account", {"marginCoin": "USDT"})
    try:
        return float(resp["data"]["available"])
    except:
        return 0.0

# ═══════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════
def load_state():
    try:
        return json.load(open(STATE_FILE))
    except:
        return {"positions": {}, "total_cycles": 0, "total_profit": 0.0}

def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# TRADING
# ═══════════════════════════════════════════════════════════════
def open_long(symbol, price):
    qty_prec = QTY_PRECISION.get(symbol, 2)
    qty = round((AMOUNT_PER_DCA * LEVERAGE) / price, qty_prec)
    min_q = MIN_QTY.get(symbol, 0.01)
    if qty < min_q:
        qty = min_q

    body = {
        "symbol": symbol, "side": "BUY_OPEN", "type": "MARKET",
        "qty": str(qty), "leverage": str(LEVERAGE), "positionType": "CROSSED"
    }
    resp = bitunix_post("/api/v1/futures/order/create", body)
    if resp.get("code") == 0:
        return qty
    else:
        log(f"  ⚠️ Order failed: {resp.get('msg')}")
        return 0

def close_long(symbol, qty):
    qty_prec = QTY_PRECISION.get(symbol, 2)
    body = {
        "symbol": symbol, "side": "SELL_CLOSE", "type": "MARKET",
        "qty": str(round(qty, qty_prec)), "leverage": str(LEVERAGE), "positionType": "CROSSED"
    }
    resp = bitunix_post("/api/v1/futures/order/create", body)
    return resp.get("code") == 0

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    load_keys()
    if not API_KEY:
        log("❌ No API key")
        return

    state = load_state()
    balance = get_balance()
    log(f"📉 DCA Bot v1.0 | Balance: ${balance:.2f} | Active: {len(state['positions'])} | Cycles: {state['total_cycles']}")

    if balance < 0.50:
        log("  ⚠️ Balance too low")
        return

    # Check existing positions for recovery or SL
    for symbol in list(state["positions"].keys()):
        pos = state["positions"][symbol]
        price = get_price(symbol)
        if not price:
            continue

        avg = pos["avg_entry"]
        recovery = (price - avg) / avg
        
        if recovery >= RECOVERY_TARGET:
            # Take profit
            if close_long(symbol, pos["total_qty"]):
                profit = recovery * pos["total_qty"] * avg
                state["total_profit"] += profit
                state["total_cycles"] += 1
                log(f"  🟢 DCA TP {symbol} | +{recovery*100:.1f}% | Profit: ${profit:.3f}")
                send_telegram(f"🟢 <b>DCA TP</b>\n{symbol} +{recovery*100:.1f}%\nProfit: ${profit:.3f}")
                del state["positions"][symbol]
        elif recovery <= -SAFETY_SL_PCT:
            # Emergency stop
            if close_long(symbol, pos["total_qty"]):
                loss = recovery * pos["total_qty"] * avg
                state["total_profit"] += loss
                log(f"  🔴 DCA SL {symbol} | {recovery*100:.1f}% | Loss: ${loss:.3f}")
                send_telegram(f"🔴 <b>DCA SL</b>\n{symbol} {recovery*100:.1f}%\nLoss: ${loss:.3f}")
                del state["positions"][symbol]

    # Scan for new DCA entries
    for symbol in CRYPTO_TOKENS:
        if len(state["positions"]) >= 3:  # Max 3 active DCA positions
            break

        price = get_price(symbol)
        high = get_4h_high(symbol)
        if not price or not high:
            continue

        dip = (high - price) / high

        pos = state["positions"].get(symbol)

        # New entry
        if not pos and dip >= DIP_TRIGGER_PCT:
            qty = open_long(symbol, price)
            if qty > 0:
                state["positions"][symbol] = {
                    "levels": 1, "avg_entry": price, "total_qty": qty,
                    "first_entry": price, "last_entry_time": time.time()
                }
                log(f"  📗 DCA Entry #{1} {symbol} @ ${price} (dip {dip*100:.1f}%)")
                send_telegram(f"📗 <b>DCA Entry #1</b>\n{symbol} @ ${price}\nDip: {dip*100:.1f}% from 4h high")

        # Add to existing position
        elif pos and pos["levels"] < MAX_DCA_LEVELS:
            drop_from_avg = (pos["avg_entry"] - price) / pos["avg_entry"]
            if drop_from_avg >= DCA_STEP_PCT:
                qty = open_long(symbol, price)
                if qty > 0:
                    new_qty = pos["total_qty"] + qty
                    new_avg = (pos["avg_entry"] * pos["total_qty"] + price * qty) / new_qty
                    pos["levels"] += 1
                    pos["avg_entry"] = new_avg
                    pos["total_qty"] = new_qty
                    pos["last_entry_time"] = time.time()
                    log(f"  📗 DCA Add #{pos['levels']} {symbol} @ ${price} | Avg: ${new_avg:.4f}")
                    send_telegram(f"📗 <b>DCA Add #{pos['levels']}</b>\n{symbol} @ ${price}\nAvg: ${new_avg:.4f}")

    save_state(state)
    log(f"  ✅ Done | Active: {len(state['positions'])} | Profit: ${state['total_profit']:.3f}")

if __name__ == "__main__":
    main()
