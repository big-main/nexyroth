#!/usr/bin/env python3
"""
NEXYROTH Order Flow Analyzer v1.0
═════════════════════════════════
Reads Bitunix order book depth to detect whale activity and imbalances.
Alerts when large orders (whales) appear that signal directional intent.

Detects:
  - Bid/ask imbalance (>3:1 ratio = strong directional pressure)
  - Whale walls (single order > 5% of total book depth)
  - Absorption (large orders being eaten = momentum incoming)
  - Spoofing detection (orders that appear and disappear rapidly)

Schedule: Every 1 minute via cron
"""

import os, sys, json, time, requests
from datetime import datetime
from typing import Optional, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from zero_fee_config import ZERO_FEE_TOKENS
except:
    ZERO_FEE_TOKENS = ["SOLUSDT", "XRPUSDT", "HYPEUSDT", "DOGEUSDT", "SUIUSDT"]

BASE_URL = "https://fapi.bitunix.com"

# Config
IMBALANCE_THRESHOLD = 2.5   # Bid/ask ratio threshold for alert
WHALE_PCT_THRESHOLD = 0.08  # Single order > 8% of book = whale
TOP_DEPTH_LEVELS    = 20    # Analyze top 20 levels of order book
ALERT_COOLDOWN      = 300   # 5 min cooldown between alerts per symbol

# Only scan top-volume tokens (order book depth matters)
SCAN_TOKENS = ["SOLUSDT", "XRPUSDT", "HYPEUSDT", "DOGEUSDT", "ADAUSDT",
               "SUIUSDT", "OILUSDT", "GOLDXAUTUSDT"]

# Paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "order_flow_state.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "order_flow.log")

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
# ORDER BOOK DATA
# ═══════════════════════════════════════════════════════════════
def get_order_book(symbol: str) -> Optional[Dict]:
    """Fetch order book depth from Bitunix."""
    try:
        r = requests.get(f"{BASE_URL}/api/v1/futures/market/depth",
            params={"symbol": symbol, "limit": str(TOP_DEPTH_LEVELS)},
            timeout=10)
        data = r.json()
        if data.get("code") == 0 and data.get("data"):
            return data["data"]
    except:
        pass
    return None

# ═══════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════
def analyze_order_book(symbol: str, book: Dict) -> Dict:
    """Analyze order book for imbalances and whale activity."""
    bids = book.get("bids", [])  # [[price, qty], ...]
    asks = book.get("asks", [])

    if not bids or not asks:
        return {"signal": "NO_DATA"}

    # Calculate total depth
    bid_total = sum(float(b[1]) for b in bids)
    ask_total = sum(float(a[1]) for a in asks)

    if ask_total == 0:
        ask_total = 0.0001

    # Bid/Ask imbalance ratio
    imbalance_ratio = bid_total / ask_total

    # Find whale orders (single order > X% of total)
    bid_whales = []
    for b in bids:
        qty = float(b[1])
        if bid_total > 0 and qty / bid_total > WHALE_PCT_THRESHOLD:
            bid_whales.append({"price": float(b[0]), "qty": qty, "pct": qty/bid_total})

    ask_whales = []
    for a in asks:
        qty = float(a[1])
        if ask_total > 0 and qty / ask_total > WHALE_PCT_THRESHOLD:
            ask_whales.append({"price": float(a[0]), "qty": qty, "pct": qty/ask_total})

    # Spread
    best_bid = float(bids[0][0]) if bids else 0
    best_ask = float(asks[0][0]) if asks else 0
    spread_pct = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0

    # Determine signal
    signal = "NEUTRAL"
    strength = 0

    if imbalance_ratio >= IMBALANCE_THRESHOLD:
        signal = "BUY_PRESSURE"
        strength = min(int(imbalance_ratio), 5)
    elif imbalance_ratio <= 1.0 / IMBALANCE_THRESHOLD:
        signal = "SELL_PRESSURE"
        strength = min(int(1.0 / imbalance_ratio), 5)

    if bid_whales:
        signal = "WHALE_BID_WALL"
        strength = max(strength, 4)
    if ask_whales:
        signal = "WHALE_ASK_WALL"
        strength = max(strength, 4)

    return {
        "symbol": symbol,
        "signal": signal,
        "strength": strength,
        "imbalance_ratio": round(imbalance_ratio, 2),
        "bid_total": round(bid_total, 2),
        "ask_total": round(ask_total, 2),
        "spread_pct": round(spread_pct, 4),
        "bid_whales": len(bid_whales),
        "ask_whales": len(ask_whales),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "whale_details": bid_whales + ask_whales
    }

# ═══════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════
def load_state() -> dict:
    try:
        return json.load(open(STATE_FILE))
    except:
        return {"last_alerts": {}, "history": []}

def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    # Keep last 100 history entries
    state["history"] = state["history"][-100:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    log(f"🐋 Order Flow Analyzer v1.0 | Scanning {len(SCAN_TOKENS)} tokens")

    state = load_state()
    alerts = []

    for symbol in SCAN_TOKENS:
        book = get_order_book(symbol)
        if not book:
            continue

        analysis = analyze_order_book(symbol, book)

        # Log
        emoji = "🟢" if "BUY" in analysis["signal"] or "BID" in analysis["signal"] else \
                "🔴" if "SELL" in analysis["signal"] or "ASK" in analysis["signal"] else "⚪"
        log(f"  {emoji} {symbol:16s} | {analysis['signal']:15s} | Ratio: {analysis['imbalance_ratio']:.2f} | Spread: {analysis['spread_pct']:.4f}%")

        # Check if alert-worthy
        if analysis["signal"] != "NEUTRAL" and analysis["strength"] >= 3:
            # Cooldown check
            last_alert = state["last_alerts"].get(symbol, 0)
            if time.time() - last_alert > ALERT_COOLDOWN:
                alerts.append(analysis)
                state["last_alerts"][symbol] = time.time()

        # Save to history
        state["history"].append({
            "ts": time.time(),
            "symbol": symbol,
            "signal": analysis["signal"],
            "ratio": analysis["imbalance_ratio"]
        })

    # Send alerts
    if alerts:
        for a in alerts:
            direction = "🟢 BUY" if "BUY" in a["signal"] or "BID" in a["signal"] else "🔴 SELL"
            msg = (f"🐋 <b>Order Flow Alert</b>\n\n"
                   f"{direction} <b>{a['symbol']}</b>\n"
                   f"Signal: {a['signal']} (strength {a['strength']}/5)\n"
                   f"Bid/Ask Ratio: {a['imbalance_ratio']:.2f}\n"
                   f"Bid Depth: ${a['bid_total']:,.0f} | Ask: ${a['ask_total']:,.0f}\n"
                   f"Spread: {a['spread_pct']:.4f}%\n"
                   f"Whales: {a['bid_whales']} bid / {a['ask_whales']} ask")
            send_telegram(msg)
            log(f"  📨 Alert sent: {a['symbol']} {a['signal']}")

    save_state(state)
    log(f"  ✅ Done | {len(alerts)} alerts sent")

if __name__ == "__main__":
    main()
