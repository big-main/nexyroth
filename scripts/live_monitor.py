#!/usr/bin/env python3
import requests
import time
import sys
from datetime import datetime

BASE = "https://fapi.bitunix.com"
TARGETS = ["IDUSDT", "VANRYUSDT", "SYNUSDT", "LIGHTERUSDT", "TLMUSDT", "AMBUSDT"]
LOG_FILE = "/home/ubuntu/trading_sniper/live_signals.log"

def check_signal(symbol):
    try:
        r_ob = requests.get(f"{BASE}/api/v1/futures/market/depth", params={"symbol": symbol}, timeout=10)
        ob = r_ob.json().get("data", {})
        bids = sum([float(b[1]) for b in ob.get("bids", [])[:10]])
        asks = sum([float(a[1]) for a in ob.get("asks", [])[:10]])
        ratio = bids / asks if asks > 0 else 0
        
        r_t = requests.get(f"{BASE}/api/v1/futures/market/tickers", timeout=10)
        ticker = next((t for t in r_t.json().get("data", []) if t["symbol"] == symbol), None)
        price = float(ticker["lastPrice"]) if ticker else 0
        
        return price, ratio
    except:
        return 0, 0

try:
    with open(LOG_FILE, "a") as log:
        log.write(f"\n--- EXPANDED MONITOR START: {datetime.now()} ---\n")
        
    while True:
        for sym in TARGETS:
            price, ratio = check_signal(sym)
            if ratio > 1.5:
                timestamp = datetime.now().strftime("%H:%M:%S")
                alert = f"[{timestamp}] {sym} | Price: {price} | Ratio: {ratio:.2f} | 🚀 SIGNAL: LONG"
                with open(LOG_FILE, "a") as log:
                    log.write(alert + "\n")
        time.sleep(30)
except KeyboardInterrupt:
    pass
