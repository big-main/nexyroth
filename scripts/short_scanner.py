import requests
BASE = "https://fapi.bitunix.com"

def scan_shorts():
    print("=== 📉 EFFICIENT SHORT SCANNER ===")
    try:
        tickers = requests.get(f'{BASE}/api/v1/futures/market/tickers').json().get('data', [])
        tickers.sort(key=lambda x: float(x.get('quoteVol', 0)), reverse=True)
        
        print(f"{'Symbol':<12} | {'Price':>10} | {'24h%':>8} | {'FR%':>10} | {'Vol(M)':>7}")
        print("-" * 60)
        
        count = 0
        for t in tickers:
            if count >= 20: break
            sym = t['symbol']
            try:
                fr = float(requests.get(f'{BASE}/api/v1/futures/market/funding_rate', params={'symbol': sym}).json().get('data', {}).get('fundingRate', 0)) * 100
                if fr > 0.1: # Only high positive funding
                    l, o = float(t.get('lastPrice', 0)), float(t.get('open', 0))
                    pct = ((l-o)/o)*100 if o else 0
                    vol = float(t.get('quoteVol', 0)) / 1e6
                    print(f"{sym:<12} | {l:>10.4f} | {pct:>+7.2f}% | {fr:>+10.4f}% | {vol:>7.1f}M")
                    count += 1
            except: pass
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    scan_shorts()
