#!/usr/bin/env python3
"""Kalshi 15-min trade advisor - analyzes live prices and momentum"""
import requests
from datetime import datetime, timedelta
import time

def get_price_series(coin_id='bitcoin', minutes=30):
    """Get recent price data from CoinGecko"""
    try:
        resp = requests.get(
            f'https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart',
            params={'vs_currency': 'usd', 'days': '1'},
            timeout=10
        )
        prices = resp.json().get('prices', [])
        # Last N minutes of data (5-min granularity)
        recent = prices[-8:]
        return recent
    except Exception as e:
        return []

def analyze():
    current_utc = datetime.utcnow()
    current_edt = current_utc - timedelta(hours=4)
    
    print("=" * 80)
    print("🎲 KALSHI 15-MIN TRADE ADVISOR")
    print("=" * 80)
    print(f"Time: {current_edt.strftime('%H:%M:%S EDT')}\n")
    
    # Get current prices
    try:
        resp = requests.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids': 'bitcoin,ethereum', 'vs_currencies': 'usd', 'include_24hr_change': 'true'},
            timeout=10
        )
        data = resp.json()
        btc = data['bitcoin']['usd']
        btc_24h = data['bitcoin']['usd_24h_change']
        eth = data['ethereum']['usd']
        eth_24h = data['ethereum']['usd_24h_change']
    except:
        print("API error - retry")
        return
    
    print(f"BTC: ${btc:,.2f} ({btc_24h:+.2f}% 24h)")
    print(f"ETH: ${eth:,.2f} ({eth_24h:+.2f}% 24h)\n")
    
    # Get BTC momentum (last 30-40 min)
    series = get_price_series('bitcoin')
    if series and len(series) >= 2:
        oldest = series[0][1]
        newest = series[-1][1]
        momentum_pct = ((newest - oldest) / oldest) * 100
        print(f"BTC 30-40min momentum: {momentum_pct:+.3f}%")
        
        if momentum_pct > 0.15:
            momentum = "STRONG UP"
        elif momentum_pct > 0.05:
            momentum = "MILD UP"
        elif momentum_pct > -0.05:
            momentum = "FLAT"
        elif momentum_pct > -0.15:
            momentum = "MILD DOWN"
        else:
            momentum = "STRONG DOWN"
        print(f"Momentum: {momentum}\n")
    else:
        momentum = "UNKNOWN"
        momentum_pct = 0
    
    # Kalshi 15-min strike analysis
    print("=" * 80)
    print("STRIKE ANALYSIS (15-min market)")
    print("=" * 80)
    
    # Round to common Kalshi strikes ($50/$100 increments)
    strikes = []
    base = int(btc / 100) * 100
    for offset in [-200, -100, 0, 100, 200]:
        strikes.append(base + offset)
    
    print(f"\nCurrent BTC: ${btc:,.2f}\n")
    print(f"{'Strike':>10} | {'Distance':>10} | {'Dist %':>8} | {'15min Call':>12}")
    print("-" * 55)
    
    best_yes = None
    best_no = None
    
    for strike in strikes:
        dist = strike - btc
        dist_pct = (dist / btc) * 100
        
        # 15-min BTC typically moves 0.05-0.20%
        if dist_pct <= -0.15:
            call = "✅ YES (safe)"
            if best_yes is None or strike > best_yes:
                best_yes = strike
        elif dist_pct <= 0.03 and momentum_pct > 0.05:
            call = "🟢 YES (mom.)"
            if best_yes is None:
                best_yes = strike
        elif dist_pct >= 0.25:
            call = "🔴 NO (far)"
            if best_no is None or strike < best_no:
                best_no = strike
        else:
            call = "⚠️ COIN FLIP"
        
        print(f"${strike:>9,} | {dist:>+10.2f} | {dist_pct:>+7.3f}% | {call:>12}")
    
    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    
    if best_yes:
        print(f"""
🟢 BEST YES BET: "BTC above ${best_yes:,} in 15 min"
   BTC is ${btc - best_yes:+,.0f} relative to strike
   YES should cost 0.85-0.95 → small but consistent profit
   Safer play: sell into strikes BTC is already above
""")
    if best_no:
        print(f"""
🔴 BEST NO BET: "BTC above ${best_no:,} in 15 min"
   BTC needs +{((best_no-btc)/btc)*100:.2f}% in 15 min (unlikely)
   NO should cost 0.80-0.90 → consistent edge
""")
    
    print(f"""
STRATEGY NOTE:
The consistent Kalshi 15-min edge is selling volatility:
• Bet YES on strikes BELOW current price (BTC stays above)
• Bet NO on strikes 0.25%+ ABOVE current price (BTC won't reach)
• Avoid strikes within ±0.10% of current price (coin flips)
• Momentum: {momentum} ({momentum_pct:+.3f}% last 30-40 min)
""")

if __name__ == '__main__':
    analyze()
