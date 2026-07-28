#!/usr/bin/env python3
import requests
import time
import sys
from datetime import datetime

BASE = "https://fapi.bitunix.com"
SYMBOL = "IDUSDT"
ENTRY_PRICE = 0.03975
LOG_FILE = "/home/ubuntu/trading_sniper/zero_tolerance.log"

def get_status():
    try:
        r_ob = requests.get(f"{BASE}/api/v1/futures/market/depth", params={"symbol": SYMBOL}, timeout=10)
        ob = r_ob.json().get("data", {})
        bids = sum([float(b[1]) for b in ob.get("bids", [])[:10]])
        asks = sum([float(a[1]) for a in ob.get("asks", [])[:10]])
        ratio = bids / asks if asks > 0 else 0
        
        r_t = requests.get(f"{BASE}/api/v1/futures/market/tickers", timeout=10)
        ticker = next((t for t in r_t.json().get("data", []) if t["symbol"] == SYMBOL), None)
        price = float(ticker["lastPrice"]) if ticker else 0
        
        return price, ratio
    except:
        return 0, 0

print(f"=== 🛡️ CAPITAL PROTECTION: {SYMBOL} ===")
print(f"Entry: {ENTRY_PRICE} | Zero-Tolerance Active")

try:
    while True:
        price, ratio = get_status()
        pnl = ((price - ENTRY_PRICE) / ENTRY_PRICE) * 100
        
        status = "✅ HOLD (Support Strong)"
        if ratio < 1.2:
            status = "🚨 EXIT NOW (Whale Support Faded)"
        elif pnl < -1.5:
            status = "🚨 EXIT NOW (Stop Loss Hit)"
        elif pnl > 5.0:
            status = "💰 TAKE PROFIT (Target Hit)"
            
        timestamp = datetime.now().strftime("%H:%M:%S")
        output = f"[{timestamp}] Price: {price:.5f} | PnL: {pnl:+.2f}% | Ratio: {ratio:.2f} | {status}"
        
        sys.stdout.write(f"\r{output}")
        sys.stdout.flush()
        
        if "EXIT" in status or "TAKE PROFIT" in status:
            print(f"\n{status} - TRIGGERED")
            break
            
        time.sleep(15)
except KeyboardInterrupt:
    print("\nMonitor stopped.")
