#!/usr/bin/env python3
"""
NEXYROTH × Alpaca Gap-and-Go Strategy v1.0
============================================
Trades pre-market gap-ups that continue higher at market open.
One of the most reliable intraday patterns — gaps with catalyst
(earnings, news) tend to run 2-5% in the first 30 minutes.

Logic:
  - Scan for stocks gapping up >2% at open vs prior close
  - First 5-min candle must be bullish (close > open)
  - Volume in first candle must be >3x average daily volume
  - Entry: Buy on breakout above first 5-min candle high
  - TP: +3% from entry
  - SL: Below first 5-min candle low

Schedule: Runs once at 9:35 AM ET (after first candle closes)
"""

import os, json, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List

def _s(p): return open(os.path.expanduser(p)).read().strip() if os.path.exists(os.path.expanduser(p)) else ""
API_KEY    = _s("~/.secrets/alpaca_api_key")
SECRET_KEY = _s("~/.secrets/alpaca_secret_key")
BASE_URL   = "https://paper-api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"
LOG_FILE   = "/home/ubuntu/trading_sniper/alpaca_gap_go.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/alpaca_gap_go_state.json"
TG_TOKEN   = _s("~/.secrets/telegram_bot_token")
TG_CHAT    = _s("~/.secrets/telegram_chat_id")

RISK_PCT       = 0.05   # 5% portfolio per trade
MAX_POS        = 5      # Limit gap trades — they're high risk
GAP_MIN_PCT    = 0.02   # Minimum 2% gap up
TP_PCT         = 0.03   # +3% TP
VOL_MULT_MIN   = 3.0    # First candle must be 3x average volume
ET = ZoneInfo("America/New_York")

# Gap-and-go watchlist — high-beta stocks that gap frequently
WATCHLIST = [
    "NVDA","AMD","TSLA","AMZN","META","GOOGL","MSFT","AAPL",
    "PLTR","SOFI","RIVN","MARA","RIOT","COIN","HOOD","RBLX",
    "SNAP","UBER","LYFT","ABNB","DASH","SHOP","SQ","PYPL",
    "TQQQ","SQQQ","SPXL","SOXL","UVXY","LABU",
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

def is_gap_window():
    """Only trade gaps in first 30 minutes (9:30-10:00 AM ET)."""
    now = datetime.now(ET)
    open_time  = now.replace(hour=9, minute=35, second=0)
    cutoff     = now.replace(hour=10, minute=0, second=0)
    return open_time <= now <= cutoff

def get_prev_close(symbol):
    """Get previous day's closing price."""
    d = get(f"/v2/stocks/{symbol}/bars",
            {"timeframe": "1Day", "limit": 2, "feed": "iex"}, base=DATA_URL)
    if not d: return None
    bars = d.get("bars", [])
    if len(bars) >= 2:
        return float(bars[-2]["c"])
    return None

def get_first_5min_bar(symbol):
    """Get today's first 5-minute bar."""
    d = get(f"/v2/stocks/{symbol}/bars",
            {"timeframe": "5Min", "limit": 3, "feed": "iex"}, base=DATA_URL)
    if not d: return None
    bars = d.get("bars", [])
    if not bars: return None
    b = bars[0]
    return {"open": float(b["o"]), "high": float(b["h"]),
            "low": float(b["l"]), "close": float(b["c"]), "volume": float(b["v"])}

def get_avg_daily_volume(symbol):
    """Get 20-day average daily volume."""
    d = get(f"/v2/stocks/{symbol}/bars",
            {"timeframe": "1Day", "limit": 21, "feed": "iex"}, base=DATA_URL)
    if not d: return 0
    bars = d.get("bars", [])
    if len(bars) < 2: return 0
    vols = [float(b["v"]) for b in bars[:-1]]
    return sum(vols) / len(vols) if vols else 0

def get_signal(symbol):
    prev_close = get_prev_close(symbol)
    if not prev_close: return None
    first_bar = get_first_5min_bar(symbol)
    if not first_bar: return None
    avg_vol = get_avg_daily_volume(symbol)
    if avg_vol == 0: return None

    gap_pct = (first_bar["open"] - prev_close) / prev_close
    vol_ratio = first_bar["volume"] / (avg_vol / 78)  # 78 5-min bars per day

    # Conditions: gap up, bullish first candle, massive volume
    if (gap_pct >= GAP_MIN_PCT and
        first_bar["close"] > first_bar["open"] and
        vol_ratio >= VOL_MULT_MIN):
        entry = first_bar["high"]  # Buy breakout above first candle high
        tp    = round(entry * (1 + TP_PCT), 2)
        sl    = round(first_bar["low"] * 0.999, 2)  # Just below first candle low
        return {"symbol": symbol, "entry": entry, "tp": tp, "sl": sl,
                "gap_pct": round(gap_pct * 100, 2), "vol_ratio": round(vol_ratio, 1),
                "prev_close": prev_close, "first_bar": first_bar}
    return None

def place_trade(sig, portfolio_value):
    symbol = sig["symbol"]; entry = sig["entry"]
    qty = max(1, int(portfolio_value * RISK_PCT / entry))
    log(f"  📤 GAP-GO LONG {symbol}: qty={qty} | Entry=${entry:.2f} | Gap={sig['gap_pct']}% | Vol={sig['vol_ratio']}x")
    # Buy stop order — only fills if price breaks above first candle high
    order = post("/v2/orders", {
        "symbol": symbol, "qty": str(qty), "side": "buy",
        "type": "stop", "time_in_force": "day", "stop_price": str(entry)
    })
    if not order: return None
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "sell",
                        "type": "limit", "time_in_force": "gtc", "limit_price": str(sig["tp"])})
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "sell",
                        "type": "stop", "time_in_force": "gtc", "stop_price": str(sig["sl"])})
    tg(f"🚀 <b>GAP-AND-GO {symbol}</b>\n"
       f"📈 Gap: <code>+{sig['gap_pct']}%</code> | Vol: <code>{sig['vol_ratio']}x</code>\n"
       f"💰 Entry (stop): <code>${entry:.2f}</code>\n"
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
    log("NEXYROTH × Alpaca Gap-and-Go v1.0 — Scan Start")
    log("=" * 55)
    if not is_market_open():
        log("  💤 Market closed"); return
    if not is_gap_window():
        log("  ⏰ Outside gap window (9:35-10:00 AM ET only)"); return
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
                log(f"  🎯 Gap: {sym} +{sig['gap_pct']}% | Vol {sig['vol_ratio']}x | Entry=${sig['entry']:.2f}")
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
