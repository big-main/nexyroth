#!/usr/bin/env python3
import requests
import json
import sys

BASE = "https://fapi.bitunix.com"

def snipe(symbol):
    print(f"=== 🎯 SNIPER SCOPE: {symbol} ===")
    try:
        # Depth
        r_ob = requests.get(f"{BASE}/api/v1/futures/market/depth", params={"symbol": symbol}, timeout=10)
        data_ob = r_ob.json()
        if data_ob.get("code") != 0:
            print(f"API Error (Depth): {data_ob.get('msg')}")
            return
        
        ob = data_ob.get("data", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        
        bid_vol = sum([float(b[1]) for b in bids])
        ask_vol = sum([float(a[1]) for a in asks])
        ratio = bid_vol / ask_vol if ask_vol else 0
        
        # Kline
        r_c = requests.get(f"{BASE}/api/v1/futures/market/kline", params={"symbol": symbol, "interval": "1m", "limit": 1}, timeout=10)
        data_c = r_c.json()
        if data_c.get("code") != 0:
            print(f"API Error (Klines): {data_c.get('msg')}")
            return
            
        candles = data_c.get("data", [])
        if not candles:
            print("No candle data available.")
            return
            
        # Bitunix kline is a list of dicts: [{'open': '...', 'close': '...', ...}]
        last_candle = candles[0]
        last_close = float(last_candle.get('close', 0))
        last_open = float(last_candle.get('open', 0))
        trend = "🟢 GREEN" if last_close > last_open else "🔴 RED"
        
        print(f"Price: ${last_close}")
        print(f"1m Candle: {trend}")
        print(f"Bid/Ask Ratio: {ratio:.2f}")
        
        if ratio > 1.2 and trend == "🟢 GREEN":
            print(">>> 🟢 SIGNAL: GO (Strong Buy Support + Upward Momentum)")
        elif ratio < 0.8 and trend == "🔴 RED":
            print(">>> 🔴 SIGNAL: ABORT (Selling Pressure + Downward Momentum)")
        else:
            print(">>> 🟡 SIGNAL: WAIT (Neutral or Mixed Signals)")
            
    except Exception as e:
        print(f"Sniper Error: {type(e).__name__} - {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 orderbook_sniper.py <SYMBOL>")
    else:
        snipe(sys.argv[1])
