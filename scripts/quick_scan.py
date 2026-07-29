#!/usr/bin/env python3
"""Quick signal scanner — shows what's blocking entries on all zero-fee tokens."""
import requests

API = "https://fapi.bitunix.com"
TOKENS = ["SOLUSDT","XRPUSDT","SUIUSDT","DOGEUSDT","TSTUSDT","LABUSDT","BUSDT","TONUSDT","SKYAIUSDT","DOGSUSDT"]

def get_klines(symbol, limit=250):
    try:
        r = requests.get(f"{API}/api/v1/futures/market/kline",
            params={"symbol": symbol, "interval": "1m", "limit": str(limit)}, timeout=10)
        data = r.json().get("data", [])
        candles = []
        for c in data:
            if isinstance(c, dict):
                candles.append({
                    "o": float(c.get("open",0)), "h": float(c.get("high",0)),
                    "l": float(c.get("low",0)),  "c": float(c.get("close",0)),
                    "v": float(c.get("quoteVol", c.get("baseVol", 0)))
                })
        return candles
    except:
        return []

def ema(prices, p):
    if len(prices) < p: return None
    k = 2/(p+1); e = sum(prices[:p])/p
    for x in prices[p:]: e = x*k + e*(1-k)
    return e

def rsi(closes, p=14):
    if len(closes) < p+1: return 50
    g, l = [], []
    for i in range(1, len(closes)):
        d = closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag = sum(g[-p:])/p; al = sum(l[-p:])/p
    return 100 if al == 0 else 100-100/(1+ag/al)

def macd_hist(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow+sig+5: return None
    macd_line = []
    for i in range(slow, len(closes)+1):
        ef = ema(closes[:i], fast)
        es = ema(closes[:i], slow)
        if ef and es: macd_line.append(ef - es)
    if len(macd_line) < sig: return None
    sl = ema(macd_line, sig)
    return macd_line[-1] - sl if sl else None

print(f"\n{'SYM':<12} {'PRICE':>9} {'RSI':>5} {'EMA':>5} {'CROSS':>6} {'200T':>5} {'MACD_H':>9} {'VOL':>5}  BLOCKERS")
print("-"*90)

for sym in TOKENS:
    candles = get_klines(sym, 250)
    if len(candles) < 30: continue
    closes = [c["c"] for c in candles]
    vols   = [c["v"] for c in candles]
    price  = closes[-1]

    e9   = ema(closes, 9)
    e21  = ema(closes, 21)
    e200 = ema(closes, 200) if len(closes) >= 200 else None
    pe9  = ema(closes[:-1], 9)
    pe21 = ema(closes[:-1], 21)

    rsi_v = rsi(closes[-20:])
    hist  = macd_hist(closes[-60:])

    avg_vol   = sum(vols[-20:])/20 if vols else 1
    vol_ratio = vols[-1]/avg_vol if avg_vol > 0 else 0

    cross_long  = pe9 and pe21 and pe9 < pe21 and e9 > e21
    cross_short = pe9 and pe21 and pe9 > pe21 and e9 < e21
    above_200   = e200 and price > e200
    below_200   = e200 and price < e200
    ema_bull    = e9 and e21 and e9 > e21

    blockers = []
    if not cross_long and not cross_short:
        blockers.append("no_cross")
    if e200 is None:
        blockers.append("no_200ema")
    if hist is None:
        blockers.append("no_macd")
    elif ema_bull and hist < 0:
        blockers.append("macd_neg")
    elif not ema_bull and hist > 0:
        blockers.append("macd_pos")
    if vol_ratio < 0.8:
        blockers.append(f"vol({vol_ratio:.2f}x)")
    if rsi_v < 45 and ema_bull:
        blockers.append(f"rsi_low({rsi_v:.0f})")
    if rsi_v > 55 and not ema_bull:
        blockers.append(f"rsi_high({rsi_v:.0f})")

    cross_str  = "LONG" if cross_long else ("SHORT" if cross_short else "none")
    trend_200  = "↑" if above_200 else ("↓" if below_200 else "?")
    hist_str   = f"{hist:.5f}" if hist is not None else "N/A    "
    status     = "✅ SIGNAL!" if not blockers else ", ".join(blockers)

    print(f"{sym:<12} ${price:>8.4f} {rsi_v:>4.0f}  {'↑' if ema_bull else '↓':>4} {cross_str:>7} {trend_200:>5} {hist_str:>9} {vol_ratio:>4.2f}x  {status}")

print()
