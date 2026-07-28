#!/usr/bin/env python3
import requests
import time
import sys

BASE = "https://fapi.bitunix.com"
TARGETS = ["IDUSDT", "TLMUSDT", "SYNUSDT"]

def check_flip(symbol):
    try:
        # Kline for 1m trend
        r_c = requests.get(f"{BASE}/api/v1/futures/market/kline", params={"symbol": symbol, "interval": "1m", "limit": 1}, timeout=10)
        candle = r_c.json().get("data", [])[0]
        is_green = float(candle['close']) > float(candle['open'])
        
        # Depth for whale support
        r_ob = requests.get(f"{BASE}/api/v1/futures/market/depth", params={"symbol": symbol}, timeout=10)
        ob = r_ob.json().get("data", {})
        bids = sum([float(b[1]) for b in ob.get("bids", [])[:10]])
        asks = sum([float(a[1]) for a in ob.get("asks", [])[:10]])
        ratio = bids / asks if asks > 0 else 0
        
        return is_green, ratio, float(candle['close'])
    except:
        return False, 0, 0

print("=== 📡 GREEN FLIP MONITOR ACTIVE ===")
print(f"Watching: {', '.join(TARGETS)}")

try:
    found = False
    while not found:
        for sym in TARGETS:
            green, ratio, price = check_flip(sym)
            if green and ratio > 1.5:
                print(f"\n🚀 [BUY NOW] {sym} flipped GREEN! Price: {price} | Whale Ratio: {ratio:.2f}")
                found = True
                break
            else:
                sys.stdout.write(f"\r{sym}: {'🔴' if not green else '🟢'} (R: {ratio:.2f}) | ")
                sys.stdout.flush()
        if not found:
            time.sleep(10)
except KeyboardInterrupt:
    print("\nMonitor stopped.")
