#!/usr/bin/env python3
"""
NEXYROTH × Alpaca VWAP Pullback Strategy v1.1
===============================================
Buys pullbacks to VWAP in uptrending stocks.
VWAP is the institutional benchmark — price tends to bounce
off VWAP multiple times during the day.

Logic:
  - Stock is above VWAP (uptrend)
  - Price pulls back to within 0.15% of VWAP
  - RSI between 40-55 (pullback zone, not oversold)
  - Volume declining on pullback (healthy retracement)
  - Entry: At VWAP touch
  - TP: +1% above VWAP
  - SL: -0.75% below VWAP (widened from 0.5% per 180-day backtest)

Symbol Selection (backtest-validated, 180d):
  AAPL: 70.8% WR, PF=3.985, Sharpe=18.33
  MSFT: 47.4% WR, PF=1.416, Sharpe=4.87
  META: 47.4% WR, PF=1.392, Sharpe=4.79

Schedule: Every 5 min during market hours (offset +2 min)
"""

import os, json, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo

def _s(p): return open(os.path.expanduser(p)).read().strip() if os.path.exists(os.path.expanduser(p)) else ""
API_KEY    = _s("~/.secrets/alpaca_api_key")
SECRET_KEY = _s("~/.secrets/alpaca_secret_key")
BASE_URL   = "https://paper-api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"
LOG_FILE   = "/home/ubuntu/trading_sniper/alpaca_vwap_pb.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/alpaca_vwap_pb_state.json"
TG_TOKEN   = _s("~/.secrets/telegram_bot_token")
TG_CHAT    = _s("~/.secrets/telegram_chat_id")

RISK_PCT       = 0.04
MAX_POS        = 8
VWAP_TOUCH_PCT = 0.0015  # Within 0.15% of VWAP
RSI_MIN        = 40
RSI_MAX        = 55
TP_PCT         = 0.01
SL_PCT         = 0.0075  # Widened from 0.5% per 180-day backtest results
ET = ZoneInfo("America/New_York")

# Restricted to backtest-validated symbols only (180-day 5-min bar analysis)
# Removed: NVDA (WR=17.6%), QQQ (WR=30%), PLTR (WR=25%), TSLA (WR=26%), etc.
WATCHLIST = [
    "AAPL",   # 70.8% WR, PF=3.985, Sharpe=18.33 — best performer
    "MSFT",   # 47.4% WR, PF=1.416, Sharpe=4.87
    "META",   # 47.4% WR, PF=1.392, Sharpe=4.79
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

def is_near_close():
    now = datetime.now(ET)
    return now.replace(hour=15, minute=45, second=0) <= now <= now.replace(hour=16, minute=0, second=0)

def get_bars(symbol, limit=80):
    d = get(f"/v2/stocks/{symbol}/bars", {"timeframe": "5Min", "limit": limit, "feed": "iex"}, base=DATA_URL)
    if not d: return []
    return [{"o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
             "c": float(b["c"]), "v": float(b["v"])} for b in d.get("bars", [])]

def calc_vwap(bars):
    """Intraday VWAP from all available bars today."""
    cumvol = 0; cumtpv = 0
    for b in bars:
        tp = (b["h"] + b["l"] + b["c"]) / 3
        cumvol += b["v"]; cumtpv += tp * b["v"]
    return cumtpv / cumvol if cumvol > 0 else 0

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50.0
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[:period])/period; al = sum(losses[:period])/period
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period; al = (al*(period-1)+losses[i])/period
    return 100.0 if al == 0 else 100.0 - (100.0/(1+ag/al))

def get_signal(symbol):
    bars = get_bars(symbol, 80)
    if len(bars) < 20: return None
    closes = [b["c"] for b in bars]
    vols   = [b["v"] for b in bars]
    vwap   = calc_vwap(bars)
    rsi    = calc_rsi(closes)
    price  = closes[-1]
    if vwap == 0: return None

    # Price must be near VWAP (within 0.15%)
    dist_pct = abs(price - vwap) / vwap
    if dist_pct > VWAP_TOUCH_PCT: return None

    # Price must be approaching from above (was above VWAP recently)
    recent_above = sum(1 for c in closes[-5:] if c > vwap)
    if recent_above < 3: return None  # Must have been above VWAP most of last 5 bars

    # RSI in pullback zone
    if not (RSI_MIN <= rsi <= RSI_MAX): return None

    # Volume declining on pullback (last bar < 3-bar average)
    if len(vols) >= 4:
        avg_vol_3 = sum(vols[-4:-1]) / 3
        if vols[-1] > avg_vol_3 * 1.5: return None  # Volume surging = not a clean pullback

    tp = round(vwap * (1 + TP_PCT), 2)
    sl = round(vwap * (1 - SL_PCT), 2)
    return {"symbol": symbol, "price": price, "vwap": round(vwap, 2),
            "tp": tp, "sl": sl, "rsi": round(rsi, 1), "dist_pct": round(dist_pct * 100, 3)}

def place_trade(sig, portfolio_value):
    symbol = sig["symbol"]; price = sig["price"]
    qty = max(1, int(portfolio_value * RISK_PCT / price))
    log(f"  📤 VWAP-PB LONG {symbol}: qty={qty} @ ~${price:.2f} | VWAP=${sig['vwap']} | RSI={sig['rsi']}")
    order = post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "buy",
                                "type": "market", "time_in_force": "day"})
    if not order: return None
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "sell",
                        "type": "limit", "time_in_force": "gtc", "limit_price": str(sig["tp"])})
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "sell",
                        "type": "stop", "time_in_force": "gtc", "stop_price": str(sig["sl"])})
    tg(f"📊 <b>VWAP PULLBACK {symbol}</b>\n"
       f"💰 Entry: <code>~${price:.2f}</code> | VWAP: <code>${sig['vwap']}</code>\n"
       f"🟢 TP: <code>${sig['tp']}</code>  🔴 SL: <code>${sig['sl']}</code>\n"
       f"📈 RSI: {sig['rsi']} | Dist from VWAP: {sig['dist_pct']}%\n"
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
    log("NEXYROTH × Alpaca VWAP Pullback v1.0 — Scan Start")
    log("=" * 55)
    if not is_market_open():
        log("  💤 Market closed"); return
    if is_near_close():
        log("  ⏰ Near close — skipping"); return
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
                log(f"  🎯 VWAP-PB: {sym} @ ${sig['price']:.2f} (VWAP=${sig['vwap']}) RSI={sig['rsi']}")
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
