#!/usr/bin/env python3
import requests
import time
import sys

BASE = "https://fapi.bitunix.com"
SYMBOL = "SKHYNIXUSDT"

def check_flip():
    try:
        # Kline for 1m trend
        r_c = requests.get(f"{BASE}/api/v1/futures/market/kline", params={"symbol": SYMBOL, "interval": "1m", "limit": 1}, timeout=10)
        candle = r_c.json().get("data", [])[0]
        is_red = float(candle['close']) < float(candle['open'])
        
        # Depth for whale pressure
        r_ob = requests.get(f"{BASE}/api/v1/futures/market/depth", params={"symbol": SYMBOL}, timeout=10)
        ob = r_ob.json().get("data", {})
        bids = sum([float(b[1]) for b in ob.get("bids", [])[:10]])
        asks = sum([float(a[1]) for a in ob.get("asks", [])[:10]])
        ratio = bids / asks if asks > 0 else 0
        
        return is_red, ratio, float(candle['close'])
    except:
        return False, 0, 0

print(f"=== 📉 RED FLIP MONITOR: {SYMBOL} ===")
print("Watching for 1m RED candle + Whale Ratio < 0.8...")

try:
    found = False
    while not found:
        red, ratio, price = check_flip()
        if red and ratio < 0.8:
            print(f"\n📉 [SHORT NOW] {SYMBOL} flipped RED! Price: {price} | Whale Ratio: {ratio:.2f}")
            found = True
        else:
            sys.stdout.write(f"\r{SYMBOL}: {'🟢' if not red else '🔴'} (R: {ratio:.2f}) | ")
            sys.stdout.flush()
            time.sleep(5)
except KeyboardInterrupt:
    print("\nMonitor stopped.")
