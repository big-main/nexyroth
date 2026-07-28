#!/usr/bin/env python3
import requests
import pandas as pd
import sys

BASE = "https://fapi.bitunix.com"
SYMBOL = "IDUSDT"

def get_advice(symbol):
    print(f"=== 🛡️ ENTRY ADVISOR: {symbol} ===")
    try:
        # Get 1h OHLCV
        r_c = requests.get(f"{BASE}/api/v1/futures/market/kline", params={"symbol": symbol, "interval": "1h", "limit": 24}, timeout=10)
        candles = r_c.json().get("data", [])
        if not candles:
            print("No candle data available.")
            return
            
        df = pd.DataFrame(candles)
        df['close'] = df['close'].astype(float)
        current_price = df['close'].iloc[0] # Bitunix returns most recent first
        avg_price = df['close'].mean()
        trend = "UP" if current_price > avg_price else "DOWN"
        
        # Get Order Book
        r_ob = requests.get(f"{BASE}/api/v1/futures/market/depth", params={"symbol": symbol}, timeout=10)
        ob = r_ob.json().get("data", {})
        bid_vol = sum([float(b[1]) for b in ob.get("bids", [])[:10]])
        ask_vol = sum([float(a[1]) for a in ob.get("asks", [])[:10]])
        ratio = bid_vol / ask_vol if ask_vol else 0
        
        # Get Funding Rate
        r_fr = requests.get(f"{BASE}/api/v1/futures/market/funding_rate", params={"symbol": symbol}, timeout=10)
        fr = float(r_fr.json().get("data", {}).get("fundingRate", 0)) * 100
        
        print(f"Current Price: ${current_price:.4f}")
        print(f"1h Trend: {trend}")
        print(f"Funding Rate: {fr:.4f}%")
        print(f"Whale Ratio (Top 10): {ratio:.2f}")
        print("-" * 30)
        
        if fr < -1.0 and ratio > 1.3 and trend == "UP":
            print(">>> 🚀 RECOMMENDATION: LONG (Short Squeeze Candidate)")
            print("Reason: Negative funding + Whale Support + Upward Trend.")
        elif fr > 0.05 and ratio < 0.7 and trend == "DOWN":
            print(">>> 📉 RECOMMENDATION: SHORT (Sell-off Continuation)")
            print("Reason: Positive funding + Heavy Asks + Downward Trend.")
        else:
            print(">>> 🟡 RECOMMENDATION: WAIT")
            print("Reason: Indicators not aligned for a high-conviction trade.")
            
    except Exception as e:
        print(f"Advisor Error: {e}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else SYMBOL
    get_advice(target)
