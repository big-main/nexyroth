#!/usr/bin/env python3
import requests
import time
import sys
import pandas as pd
from datetime import datetime

BASE = "https://fapi.bitunix.com"
TARGETS = {
    "VANRYUSDT": {"entry": 0.0055},
    "LABUSDT": {"entry": 16.525}
}
LOG_FILE = "/home/ubuntu/trading_sniper/swing_logs.log"

def get_4h_trend(symbol):
    try:
        r_c = requests.get(f"{BASE}/api/v1/futures/market/kline", params={"symbol": symbol, "interval": "4h", "limit": 20}, timeout=10)
        candles = r_c.json().get("data", [])
        df = pd.DataFrame(candles)
        df['close'] = df['close'].astype(float)
        sma = df['close'].mean()
        curr = df['close'].iloc[0]
        return curr, sma
    except:
        return 0, 0

print(f"=== 🌊 MULTI-SWING MONITOR ACTIVE ===")
print(f"Tracking: {', '.join(TARGETS.keys())}")

try:
    with open(LOG_FILE, "a") as log:
        log.write(f"\n--- MULTI-SWING START: {datetime.now()} ---\n")
        
    while True:
        for sym, data in TARGETS.items():
            curr, sma = get_4h_trend(sym)
            pnl = ((curr - data['entry']) / data['entry']) * 100
            
            status = "✅ BULLISH"
            if curr < sma:
                status = "🚨 REVERSED"
            elif pnl < -10.0:
                status = "🚨 STOP HIT"
                
            timestamp = datetime.now().strftime("%H:%M:%S")
            output = f"[{timestamp}] {sym} | Price: {curr:.4f} | PnL: {pnl:+.2f}% | {status}"
            print(output)
            
            if "REVERSED" in status or "STOP" in status:
                with open(LOG_FILE, "a") as log:
                    log.write(f"ALERT: {output}\n")
        
        time.sleep(300) # 5-minute intervals
except KeyboardInterrupt:
    pass
