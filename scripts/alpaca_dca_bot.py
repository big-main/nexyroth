#!/usr/bin/env python3
"""
NEXYROTH DCA Bot v1.0 (Alpaca)
═══════════════════════════════
Dollar-Cost Averages into positions on dips using Alpaca paper account.
Buys more when price drops, sells when recovery target hit.

Strategy:
  - Monitors a watchlist of high-quality stocks/ETFs
  - Buys a fixed $ amount when price drops X% from recent high
  - Adds to position (DCA) on each additional X% drop
  - Sells entire position when price recovers Y% from avg cost
  - Max 5 DCA levels per symbol

Schedule: Every 15 minutes via cron (market hours only)
"""

import os, json, time, requests
from datetime import datetime, timezone
from typing import Optional, Dict

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
API_KEY    = open(os.path.expanduser("~/.secrets/alpaca_api_key")).read().strip() if os.path.exists(os.path.expanduser("~/.secrets/alpaca_api_key")) else ""
SECRET_KEY = open(os.path.expanduser("~/.secrets/alpaca_secret_key")).read().strip() if os.path.exists(os.path.expanduser("~/.secrets/alpaca_secret_key")) else ""
BASE_URL   = "https://paper-api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"

# DCA parameters
DCA_AMOUNT       = 500.0    # $ per DCA buy
DIP_TRIGGER_PCT  = 0.03     # 3% drop from recent high triggers first buy
DCA_STEP_PCT     = 0.02     # Each additional 2% drop triggers another buy
RECOVERY_TARGET  = 0.04     # 4% above avg cost = sell all
MAX_DCA_LEVELS   = 5        # Max 5 buys per symbol
LOOKBACK_DAYS    = 20       # Recent high = highest close in last 20 days

# Watchlist — high-quality stocks that recover from dips
WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
    "SPY", "QQQ", "TQQQ",
    "AMD", "PLTR", "COIN", "MARA",
]

# Paths
DATA_DIR   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "dca_bot_state.json")
LOG_FILE   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alpaca_dca.log")

# Telegram
TG_TOKEN_FILE = os.path.expanduser("~/.secrets/telegram_bot_token")
TG_CHAT_FILE  = os.path.expanduser("~/.secrets/telegram_chat_id")

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

def alpaca_get(path: str, base=None) -> dict:
    url = f"{base or BASE_URL}{path}"
    r = requests.get(url, headers={
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": SECRET_KEY
    }, timeout=15)
    return r.json() if r.status_code == 200 else {}

def alpaca_post(path: str, body: dict) -> dict:
    r = requests.post(f"{BASE_URL}{path}", headers={
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": SECRET_KEY
    }, json=body, timeout=15)
    return r.json() if r.status_code in (200, 201) else {"error": r.text}

# ═══════════════════════════════════════════════════════════════
# MARKET DATA
# ═══════════════════════════════════════════════════════════════
def is_market_open() -> bool:
    clock = alpaca_get("/v2/clock")
    return clock.get("is_open", False)

def get_recent_high(symbol: str) -> Optional[float]:
    """Get highest close in last LOOKBACK_DAYS days."""
    try:
        bars = alpaca_get(f"/v2/stocks/{symbol}/bars?timeframe=1Day&limit={LOOKBACK_DAYS}", base=DATA_URL)
        if "bars" in bars and bars["bars"]:
            return max(float(b["c"]) for b in bars["bars"])
    except:
        pass
    return None

def get_current_price(symbol: str) -> Optional[float]:
    """Get latest trade price."""
    try:
        trade = alpaca_get(f"/v2/stocks/{symbol}/trades/latest", base=DATA_URL)
        if "trade" in trade:
            return float(trade["trade"]["p"])
    except:
        pass
    return None

def get_account_equity() -> float:
    acct = alpaca_get("/v2/account")
    return float(acct.get("equity", 0))

# ═══════════════════════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def load_state() -> dict:
    try:
        return json.load(open(STATE_FILE))
    except:
        return {"positions": {}, "total_buys": 0, "total_sells": 0, "total_profit": 0.0}

def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# DCA LOGIC
# ═══════════════════════════════════════════════════════════════
def check_dca_buy(symbol: str, state: dict) -> bool:
    """Check if we should DCA buy this symbol."""
    price = get_current_price(symbol)
    high = get_recent_high(symbol)
    if not price or not high:
        return False

    drop_pct = (high - price) / high
    pos = state["positions"].get(symbol, {"levels": 0, "avg_cost": 0, "total_qty": 0, "total_invested": 0})

    # First buy: price must be DIP_TRIGGER_PCT below recent high
    if pos["levels"] == 0 and drop_pct >= DIP_TRIGGER_PCT:
        return do_buy(symbol, price, pos, state)

    # Additional DCA: price must be DCA_STEP_PCT below avg cost
    if 0 < pos["levels"] < MAX_DCA_LEVELS:
        drop_from_avg = (pos["avg_cost"] - price) / pos["avg_cost"]
        if drop_from_avg >= DCA_STEP_PCT:
            return do_buy(symbol, price, pos, state)

    return False

def do_buy(symbol: str, price: float, pos: dict, state: dict) -> bool:
    """Execute a DCA buy."""
    qty = round(DCA_AMOUNT / price, 2)
    if qty < 0.01:
        return False

    resp = alpaca_post("/v2/orders", {
        "symbol": symbol,
        "qty": str(qty),
        "side": "buy",
        "type": "market",
        "time_in_force": "day"
    })

    if "error" in resp:
        log(f"  ⚠️ {symbol} buy failed: {resp['error'][:100]}")
        return False

    # Update position state
    new_invested = pos.get("total_invested", 0) + DCA_AMOUNT
    new_qty = pos.get("total_qty", 0) + qty
    new_avg = new_invested / new_qty if new_qty > 0 else price
    new_levels = pos.get("levels", 0) + 1

    state["positions"][symbol] = {
        "levels": new_levels,
        "avg_cost": round(new_avg, 4),
        "total_qty": round(new_qty, 4),
        "total_invested": round(new_invested, 2),
        "last_buy_price": price,
        "last_buy_time": time.time()
    }
    state["total_buys"] += 1

    log(f"  📗 DCA BUY #{new_levels} {symbol} | {qty} shares @ ${price:.2f} | Avg: ${new_avg:.2f}")
    send_telegram(f"📗 <b>DCA BUY #{new_levels}</b>\n{symbol} | {qty} shares @ ${price:.2f}\nAvg cost: ${new_avg:.2f}\nInvested: ${new_invested:.0f}")
    return True

def check_recovery_sell(symbol: str, state: dict) -> bool:
    """Check if position has recovered enough to sell."""
    pos = state["positions"].get(symbol)
    if not pos or pos["levels"] == 0:
        return False

    price = get_current_price(symbol)
    if not price:
        return False

    recovery = (price - pos["avg_cost"]) / pos["avg_cost"]
    if recovery >= RECOVERY_TARGET:
        # Sell all
        resp = alpaca_post("/v2/orders", {
            "symbol": symbol,
            "qty": str(pos["total_qty"]),
            "side": "sell",
            "type": "market",
            "time_in_force": "day"
        })

        if "error" in resp:
            log(f"  ⚠️ {symbol} sell failed: {resp['error'][:100]}")
            return False

        profit = (price - pos["avg_cost"]) * pos["total_qty"]
        state["total_profit"] += profit
        state["total_sells"] += 1

        log(f"  📕 DCA SELL {symbol} | {pos['total_qty']} shares @ ${price:.2f} | Profit: ${profit:.2f} ({recovery*100:.1f}%)")
        send_telegram(f"📕 <b>DCA SELL</b> 🟢\n{symbol} | {pos['total_qty']} shares @ ${price:.2f}\nProfit: <b>${profit:.2f}</b> ({recovery*100:.1f}%)\nTotal DCA profit: ${state['total_profit']:.2f}")

        # Clear position
        del state["positions"][symbol]
        return True

    return False

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    if not API_KEY:
        log("❌ No Alpaca API key")
        return

    if not is_market_open():
        log("⏸️ Market closed — DCA bot sleeping")
        return

    state = load_state()
    equity = get_account_equity()
    active = len(state["positions"])

    log(f"📊 DCA Bot v1.0 | Equity: ${equity:.0f} | Active: {active} | Buys: {state['total_buys']} | Profit: ${state['total_profit']:.2f}")

    # Check recovery sells first
    for symbol in list(state["positions"].keys()):
        check_recovery_sell(symbol, state)

    # Check for new DCA buys
    for symbol in WATCHLIST:
        if symbol not in state["positions"] or state["positions"][symbol]["levels"] < MAX_DCA_LEVELS:
            check_dca_buy(symbol, state)

    save_state(state)
    log(f"  ✅ Scan complete | Active positions: {len(state['positions'])}")

if __name__ == "__main__":
    main()
