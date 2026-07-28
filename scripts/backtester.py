#!/usr/bin/env python3
import requests
import pandas as pd
import numpy as np

BASE = "https://fapi.bitunix.com"

def backtest(symbol, days=7):
    print(f"=== 📊 BACKTESTING ENGINE: {symbol} ({days} Days) ===")
    try:
        limit = 24 * days
        r = requests.get(f"{BASE}/api/v1/futures/market/kline", params={"symbol": symbol, "interval": "1h", "limit": limit}, timeout=10)
        data = r.json().get("data", [])
        
        if not data:
            print("No historical data found.")
            return

        df = pd.DataFrame(data)
        df['close'] = df['close'].astype(float)
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['quoteVol'].astype(float)
        
        df = df.iloc[::-1].reset_index(drop=True)
        
        # Strategy: Buy when price > SMA20 AND Volume > 1.5x Avg Volume
        df['sma20'] = df['close'].rolling(window=20).mean()
        df['vol_avg'] = df['volume'].rolling(window=20).mean()
        
        df['signal'] = np.where((df['close'] > df['sma20']) & (df['volume'] > df['vol_avg'] * 1.5), 1, 0)
        
        df['returns'] = df['close'].pct_change()
        df['strategy_returns'] = df['signal'].shift(1) * df['returns']
        
        total_return = (df['strategy_returns'] + 1).prod() - 1
        trades = df[df['signal'] == 1]
        win_rate = len(df[df['strategy_returns'] > 0]) / len(trades) if len(trades) > 0 else 0
        
        # Drawdown calculation
        cumulative = (df['strategy_returns'] + 1).cumprod()
        peak = cumulative.expanding(min_periods=1).max()
        drawdown = (cumulative/peak) - 1
        max_dd = drawdown.min()
        
        print(f"Total Return: {total_return*100:.2f}%")
        print(f"Win Rate: {win_rate*100:.2f}%")
        print(f"Max Drawdown: {max_dd*100:.2f}%")
        print(f"Total Trades Triggered: {len(trades)}")
        print("-" * 35)
        
        return total_return
        
    except Exception as e:
        print(f"Backtest Error: {e}")

if __name__ == "__main__":
    backtest("IDUSDT", days=7)
    backtest("TLMUSDT", days=7)
    backtest("LIGHTERUSDT", days=7)
