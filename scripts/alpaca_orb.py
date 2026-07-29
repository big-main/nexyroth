#!/usr/bin/env python3
"""
NEXYROTH × Alpaca Opening Range Breakout (ORB) v1.0
=====================================================
Trades breakouts above/below the first 30-minute range.
The ORB is one of the most statistically robust intraday patterns.
Price often trends strongly in the direction of the first breakout.

Logic:
  - Calculate high/low of first 30 minutes (9:30-10:00 AM ET)
  - Wait for price to break above ORB high (LONG) or below ORB low (SHORT)
  - Volume must confirm breakout (>2x average)
  - Entry: Market order on breakout
  - TP: 2× the ORB range above/below breakout
  - SL: Opposite side of ORB range

Schedule: Every 5 min from 10:00 AM to 12:00 PM ET (prime breakout window)
"""

import os, json, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo

def _s(p): return open(os.path.expanduser(p)).read().strip() if os.path.exists(os.path.expanduser(p)) else ""
API_KEY    = _s("~/.secrets/alpaca_api_key")
SECRET_KEY = _s("~/.secrets/alpaca_secret_key")
BASE_URL   = "https://paper-api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"
LOG_FILE   = "/home/ubuntu/trading_sniper/alpaca_orb.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/alpaca_orb_state.json"
TG_TOKEN   = _s("~/.secrets/telegram_bot_token")
TG_CHAT    = _s("~/.secrets/telegram_chat_id")

RISK_PCT   = 0.05
MAX_POS    = 6
TP_MULT    = 2.0   # TP = 2× ORB range
VOL_MULT   = 2.0   # Breakout volume must be 2x average
ET = ZoneInfo("America/New_York")

WATCHLIST = [
    "NVDA","AMD","TSLA","AMZN","META","GOOGL","MSFT","AAPL",
    "PLTR","SOFI","MARA","RIOT","COIN","HOOD","RBLX","SNAP",
    "TQQQ","SQQQ","SPXL","SPXS","SOXL","UVXY",
    "SPY","QQQ","IWM","DIA",
]

HEADERS = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f: f.write(line + "\n")
    except: pass

def tg(msg):
    if not TG_TOKEN or not TG_CHAT: return
    try: requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=8)
    except: pass

def get(path, params=None, base=BASE_URL):
    try:
        r = requests.get(f"{base}{path}", headers=HEADERS, params=params, timeout=15)
        return r.json() if r.status_code == 200 else None
    except: return None

def post(path, body):
    try:
        r = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=body, timeout=15)
        return r.json() if r.status_code in (200,201) else None
    except: return None

def is_market_open():
    d = get("/v2/clock")
    return d.get("is_open", False) if d else False

def is_orb_window():
    """Trade ORB breakouts from 10:00 AM to 12:00 PM ET."""
    now = datetime.now(ET)
    start = now.replace(hour=10, minute=0, second=0)
    end   = now.replace(hour=12, minute=0, second=0)
    return start <= now <= end

def get_bars(symbol, limit=30):
    d = get(f"/v2/stocks/{symbol}/bars", {"timeframe": "5Min", "limit": limit, "feed": "iex"}, base=DATA_URL)
    if not d: return []
    return [{"o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
             "c": float(b["c"]), "v": float(b["v"])} for b in d.get("bars", [])]

def calc_vol_ratio(vols, lookback=10):
    if len(vols) < lookback+1: return 1.0
    avg = sum(vols[-lookback-1:-1]) / lookback
    return vols[-1] / avg if avg > 0 else 1.0

def get_signal(symbol):
    bars = get_bars(symbol, 30)
    if len(bars) < 8: return None  # Need at least 6 bars (30 min) + 2 breakout bars

    # First 6 bars = first 30 minutes (ORB)
    orb_bars = bars[:6]
    orb_high = max(b["h"] for b in orb_bars)
    orb_low  = min(b["l"] for b in orb_bars)
    orb_range = orb_high - orb_low
    if orb_range <= 0: return None

    # Current bar (latest)
    current = bars[-1]
    price   = current["c"]
    vols    = [b["v"] for b in bars]
    vol_ratio = calc_vol_ratio(vols)

    if vol_ratio < VOL_MULT: return None  # No volume confirmation

    # LONG breakout: price closes above ORB high
    if price > orb_high:
        tp = round(orb_high + TP_MULT * orb_range, 2)
        sl = round(orb_low, 2)
        return {"symbol": symbol, "direction": "LONG", "price": price,
                "tp": tp, "sl": sl, "orb_high": round(orb_high, 2),
                "orb_low": round(orb_low, 2), "orb_range": round(orb_range, 2),
                "vol_ratio": round(vol_ratio, 1)}

    # SHORT breakout: price closes below ORB low
    if price < orb_low:
        tp = round(orb_low - TP_MULT * orb_range, 2)
        sl = round(orb_high, 2)
        return {"symbol": symbol, "direction": "SHORT", "price": price,
                "tp": tp, "sl": sl, "orb_high": round(orb_high, 2),
                "orb_low": round(orb_low, 2), "orb_range": round(orb_range, 2),
                "vol_ratio": round(vol_ratio, 1)}
    return None

def place_trade(sig, portfolio_value):
    symbol = sig["symbol"]; price = sig["price"]; direction = sig["direction"]
    qty  = max(1, int(portfolio_value * RISK_PCT / price))
    side = "buy" if direction == "LONG" else "sell"
    log(f"  📤 ORB {direction} {symbol}: qty={qty} @ ~${price:.2f} | TP=${sig['tp']} SL=${sig['sl']}")
    order = post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": side,
                                "type": "market", "time_in_force": "day"})
    if not order: return None
    close_side = "sell" if direction == "LONG" else "buy"
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": close_side,
                        "type": "limit", "time_in_force": "gtc", "limit_price": str(sig["tp"])})
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": close_side,
                        "type": "stop", "time_in_force": "gtc", "stop_price": str(sig["sl"])})
    emoji = "⬆️" if direction == "LONG" else "⬇️"
    tg(f"{emoji} <b>ORB {direction} {symbol}</b>\n"
       f"📐 ORB: <code>${sig['orb_low']:.2f} – ${sig['orb_high']:.2f}</code> (range: ${sig['orb_range']:.2f})\n"
       f"💰 Entry: <code>~${price:.2f}</code> | Vol: <code>{sig['vol_ratio']}x</code>\n"
       f"🟢 TP: <code>${sig['tp']}</code>  🔴 SL: <code>${sig['sl']}</code>\n"
       f"🏦 Paper Account")
    return order

def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except: return {"total_trades": 0, "traded_today": [], "last_date": ""}

def save_state(s):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f: json.dump(s, f, indent=2)

def main():
    log("=" * 55)
    log("NEXYROTH × Alpaca ORB v1.0 — Scan Start")
    log("=" * 55)
    if not is_market_open():
        log("  💤 Market closed"); return
    if not is_orb_window():
        log("  ⏰ Outside ORB window (10:00 AM–12:00 PM ET only)"); return
    account = get("/v2/account") or {}
    portfolio_value = float(account.get("portfolio_value", 100000))
    positions = get("/v2/positions") or []
    current_syms = {p["symbol"] for p in positions}
    log(f"  Portfolio: ${portfolio_value:,.2f} | Open: {len(positions)}/{MAX_POS}")
    if len(positions) >= MAX_POS:
        log("  ⚠️ Max positions reached"); return
    state = load_state()
    today = datetime.now(ET).strftime("%Y-%m-%d")
    if state.get("last_date") != today:
        state["traded_today"] = []; state["last_date"] = today
    signals = 0; trades = 0
    for sym in WATCHLIST:
        if sym in current_syms or sym in state.get("traded_today", []): continue
        try:
            sig = get_signal(sym)
            if sig:
                signals += 1
                log(f"  🎯 ORB {sig['direction']}: {sym} @ ${sig['price']:.2f} | Range=${sig['orb_range']:.2f} | Vol={sig['vol_ratio']}x")
                if len(positions) + trades >= MAX_POS: break
                if place_trade(sig, portfolio_value):
                    trades += 1
                    state["total_trades"] = state.get("total_trades", 0) + 1
                    state.setdefault("traded_today", []).append(sym)
                    save_state(state)
                    time.sleep(0.5)
        except Exception as e:
            log(f"  ⚠️ {sym}: {e}"); continue
    log(f"  Signals: {signals} | Trades: {trades} | Total: {state.get('total_trades',0)}")

if __name__ == "__main__":
    main()
