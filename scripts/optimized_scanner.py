#!/usr/bin/env python3
"""
🏆 OPTIMIZED SCANNER - TLMUSDT WINNING PATTERN
Filters for high-momentum symbols with strong whale support
"""
import requests
import json
from datetime import datetime

def fetch_bitunix_tickers():
    """Fetch all symbols from Bitunix"""
    try:
        resp = requests.get('https://api.bitunix.com/spot/v1/public/tickers', timeout=10)
        data = resp.json()
        if data.get('code') == '0':
            return data.get('data', [])
    except Exception as e:
        print(f"Error fetching tickers: {e}")
    return []

def analyze_symbol(ticker):
    """Analyze a symbol against the TLMUSDT winning criteria"""
    try:
        symbol = ticker.get('symbol', '')
        price = float(ticker.get('last', 0))
        change_24h = float(ticker.get('change24h', 0)) * 100
        volume = float(ticker.get('quoteVolume', 0)) / 1_000_000  # Convert to millions
        
        # FILTER 1: Min 24h gain +15%
        if change_24h < 15:
            return None
        
        # FILTER 2: Min volume $1M
        if volume < 1:
            return None
        
        # FILTER 3: Fetch funding rate
        try:
            fr_resp = requests.get(
                'https://api.bitunix.com/perpetual/v1/public/fundingRate',
                params={'symbol': symbol},
                timeout=5
            )
            fr_data = fr_resp.json()
            if fr_data.get('code') == '0' and fr_data.get('data'):
                funding_rate = float(fr_data['data'][0].get('fundingRate', 0)) * 100
            else:
                funding_rate = 0
        except:
            funding_rate = 0
        
        # FILTER 4: Negative funding (shorts underwater)
        if funding_rate >= 0:
            return None
        
        # FILTER 5: Fetch order book for whale ratio
        try:
            ob_resp = requests.get(
                'https://api.bitunix.com/spot/v1/public/depth',
                params={'symbol': symbol, 'limit': 10},
                timeout=5
            )
            ob_data = ob_resp.json()
            if ob_data.get('code') == '0' and ob_data.get('data'):
                bids = ob_data['data'].get('bids', [])
                asks = ob_data['data'].get('asks', [])
                
                bid_vol = sum(float(b[1]) for b in bids[:10])
                ask_vol = sum(float(a[1]) for a in asks[:10])
                
                whale_ratio = bid_vol / ask_vol if ask_vol > 0 else 0
            else:
                whale_ratio = 0
        except:
            whale_ratio = 0
        
        # FILTER 6: Whale ratio > 1.2 (strong buy support)
        if whale_ratio < 1.2:
            return None
        
        return {
            'symbol': symbol,
            'price': price,
            'change_24h': change_24h,
            'volume_m': volume,
            'funding_rate': funding_rate,
            'whale_ratio': whale_ratio,
            'score': change_24h * whale_ratio  # Composite score
        }
    except Exception as e:
        return None

def main():
    print("=" * 80)
    print("🏆 OPTIMIZED SCANNER - TLMUSDT WINNING PATTERN")
    print("=" * 80)
    print(f"Scan Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    
    print("Fetching all Bitunix symbols...")
    tickers = fetch_bitunix_tickers()
    
    print(f"Analyzing {len(tickers)} symbols against TLMUSDT criteria...\n")
    
    candidates = []
    for ticker in tickers:
        result = analyze_symbol(ticker)
        if result:
            candidates.append(result)
    
    # Sort by composite score
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    if not candidates:
        print("❌ No symbols match the TLMUSDT winning pattern")
        return
    
    print(f"✅ Found {len(candidates)} HIGH-CONVICTION candidates:\n")
    print(f"{'Symbol':<12} {'24h%':<8} {'Vol(M)':<8} {'FR%':<8} {'Ratio':<8} {'Score':<8}")
    print("-" * 80)
    
    for i, cand in enumerate(candidates[:15], 1):
        print(f"{cand['symbol']:<12} {cand['change_24h']:>6.2f}% {cand['volume_m']:>6.1f}M {cand['funding_rate']:>6.2f}% {cand['whale_ratio']:>6.2f} {cand['score']:>6.2f}")
    
    print("\n" + "=" * 80)
    print("🎯 TOP 3 PRIORITY ENTRIES:")
    print("=" * 80)
    for i, cand in enumerate(candidates[:3], 1):
        print(f"\n{i}. {cand['symbol']}")
        print(f"   24h Gain: {cand['change_24h']:+.2f}%")
        print(f"   Volume: ${cand['volume_m']:.1f}M")
        print(f"   Funding: {cand['funding_rate']:.2f}% (shorts underwater)")
        print(f"   Whale Ratio: {cand['whale_ratio']:.2f} (strong buy support)")
        print(f"   Composite Score: {cand['score']:.2f}")

if __name__ == '__main__':
    main()
