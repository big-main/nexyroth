import requests
import pandas as pd

BASE = "https://fapi.bitunix.com"

def analyze_trend():
    print("=== 📈 SWING TRADE TREND ANALYZER ===")
    try:
        tickers = requests.get(f'{BASE}/api/v1/futures/market/tickers').json().get('data', [])
        tickers.sort(key=lambda x: float(x.get('quoteVol', 0)), reverse=True)
        
        results = []
        for t in tickers[:20]:
            sym = t['symbol']
            try:
                # 4h Data for Trend
                r_c = requests.get(f"{BASE}/api/v1/futures/market/kline", params={"symbol": sym, "interval": "4h", "limit": 20}, timeout=10)
                candles = r_c.json().get("data", [])
                if not candles: continue
                
                df = pd.DataFrame(candles)
                df['close'] = df['close'].astype(float)
                
                # Trend Strength: Current vs 20-period SMA
                sma = df['close'].mean()
                curr = df['close'].iloc[0]
                strength = ((curr - sma) / sma) * 100
                
                # Funding
                fr = float(requests.get(f'{BASE}/api/v1/futures/market/funding_rate', params={'symbol': sym}).json().get('data', {}).get('fundingRate', 0)) * 100
                
                results.append({
                    "symbol": sym,
                    "price": curr,
                    "strength": strength,
                    "fr": fr
                })
            except: pass
            
        results.sort(key=lambda x: abs(x['strength']), reverse=True)
        print(f"{'Symbol':<12} | {'Price':>10} | {'4h Trend%':>10} | {'FR%':>10}")
        print("-" * 50)
        for r in results[:10]:
            print(f"{r['symbol']:<12} | {r['price']:>10.4f} | {r['strength']:>+10.2f}% | {r['fr']:>+10.4f}%")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_trend()
