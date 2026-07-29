#!/usr/bin/env python3
"""
NEXYROTH × Alpaca Mean Reversion Strategy v1.0
================================================
Fades extreme moves: buys oversold stocks that have pulled back
to Bollinger Band lower band, sells when price reverts to mean (SMA).

Logic:
  - Price touches or breaks below BB lower band (2σ)
  - RSI < 35 (oversold)
  - Volume spike confirms the flush (1.2x average)
  - Entry: LONG at lower band touch
  - TP: Middle band (20-period SMA)
  - SL: 1.5× ATR below entry

Schedule: Every 5 min during market hours (offset +1 min from momentum scalper)
"""

import os, json, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List

# ── Config ──────────────────────────────────────────────────────
def _s(p): return open(os.path.expanduser(p)).read().strip() if os.path.exists(os.path.expanduser(p)) else ""
API_KEY    = _s("~/.secrets/alpaca_api_key")
SECRET_KEY = _s("~/.secrets/alpaca_secret_key")
BASE_URL   = "https://paper-api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"
LOG_FILE   = "/home/ubuntu/trading_sniper/alpaca_mean_rev.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/alpaca_mean_rev_state.json"
TG_TOKEN   = _s("~/.secrets/telegram_bot_token")
TG_CHAT    = _s("~/.secrets/telegram_chat_id")

RISK_PCT    = 0.04   # 4% portfolio per trade
MAX_POS     = 8
BB_PERIOD   = 20
BB_STD      = 2.0
RSI_THRESH  = 35     # Must be below this to enter
VOL_MULT    = 1.2
ATR_SL_MULT = 1.5
ET = ZoneInfo("America/New_York")

# Mean reversion watchlist — liquid large-caps that revert well
WATCHLIST = [
    "AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","JPM","BAC","GS",
    "XOM","CVX","JNJ","PFE","UNH","WMT","KO","PEP","DIS","NFLX",
    "SPY","QQQ","IWM","GLD","SLV","TLT","HYG","XLF","XLE","XLK",
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

def get_bars(symbol, limit=60):
    d = get(f"/v2/stocks/{symbol}/bars", {"timeframe": "5Min", "limit": limit, "feed": "iex"}, base=DATA_URL)
    if not d: return []
    return [{"o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
             "c": float(b["c"]), "v": float(b["v"])} for b in d.get("bars", [])]

def calc_bb(closes, period=20, std_mult=2.0):
    if len(closes) < period: return None, None, None
    sma = sum(closes[-period:]) / period
    variance = sum((c - sma)**2 for c in closes[-period:]) / period
    std = variance ** 0.5
    return sma, sma + std_mult * std, sma - std_mult * std  # mid, upper, lower

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50.0
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[:period])/period; al = sum(losses[:period])/period
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period; al = (al*(period-1)+losses[i])/period
    return 100.0 if al == 0 else 100.0 - (100.0/(1+ag/al))

def calc_atr(bars, period=14):
    if len(bars) < period+1: return 0.0
    trs = [max(b["h"]-b["l"], abs(b["h"]-bars[i-1]["c"]), abs(b["l"]-bars[i-1]["c"]))
           for i, b in enumerate(bars[1:], 1)]
    return sum(trs[-period:]) / period

def calc_vol_ratio(vols, lookback=20):
    if len(vols) < lookback+1: return 1.0
    avg = sum(vols[-lookback-1:-1]) / lookback
    return vols[-1] / avg if avg > 0 else 1.0

def get_signal(symbol):
    bars = get_bars(symbol, 60)
    if len(bars) < BB_PERIOD + 5: return None
    closes = [b["c"] for b in bars]
    vols   = [b["v"] for b in bars]
    mid, upper, lower = calc_bb(closes, BB_PERIOD, BB_STD)
    if lower is None: return None
    rsi = calc_rsi(closes)
    vol_ratio = calc_vol_ratio(vols)
    atr = calc_atr(bars)
    price = closes[-1]
    # Entry: price at or below lower band, oversold RSI, volume spike
    if price <= lower and rsi < RSI_THRESH and vol_ratio >= VOL_MULT:
        return {"symbol": symbol, "price": price, "tp": round(mid, 2),
                "sl": round(price - ATR_SL_MULT * atr, 2),
                "rsi": round(rsi, 1), "vol": round(vol_ratio, 2),
                "bb_lower": round(lower, 2), "bb_mid": round(mid, 2)}
    return None

def place_trade(sig, portfolio_value):
    symbol = sig["symbol"]; price = sig["price"]
    qty = max(1, int(portfolio_value * RISK_PCT / price))
    log(f"  📤 MEAN-REV LONG {symbol}: qty={qty} @ ~${price:.2f} | TP=${sig['tp']} SL=${sig['sl']}")
    order = post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "buy",
                                "type": "market", "time_in_force": "day"})
    if not order: return None
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "sell",
                        "type": "limit", "time_in_force": "gtc", "limit_price": str(sig["tp"])})
    post("/v2/orders", {"symbol": symbol, "qty": str(qty), "side": "sell",
                        "type": "stop", "time_in_force": "gtc", "stop_price": str(sig["sl"])})
    tg(f"📉 <b>MEAN-REV LONG {symbol}</b>\n"
       f"💰 Entry: <code>~${price:.2f}</code>\n"
       f"🟢 TP: <code>${sig['tp']}</code> (BB mid)  🔴 SL: <code>${sig['sl']}</code>\n"
       f"📊 RSI: {sig['rsi']} | Vol: {sig['vol']}x | BB lower: ${sig['bb_lower']}\n"
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
    log("NEXYROTH × Alpaca Mean Reversion v1.0 — Scan Start")
    log("=" * 55)
    if not is_market_open():
        log("  💤 Market closed"); return
    if is_near_close():
        log("  ⏰ Near close — skipping mean rev entries"); return
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
                log(f"  🎯 Mean-Rev: {sym} @ ${sig['price']:.2f} RSI={sig['rsi']} Vol={sig['vol']}x")
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
