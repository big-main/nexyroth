#!/usr/bin/env python3
"""
🎯 STRATEGY FILTER - Apply TLMUSDT winning criteria to current market
"""
import subprocess
from datetime import datetime

CRITERIA = {
    'min_24h_gain': 15,
    'min_volume_m': 1,
    'max_funding_rate': -0.1,
}

def get_scanner_data():
    try:
        result = subprocess.run(['python3', '/home/ubuntu/trading_sniper/scripts/scanner.py'],
                              capture_output=True, text=True, timeout=10)
        return result.stdout
    except:
        return ""

def parse_symbols(text):
    symbols = []
    lines = text.split('\n')
    for line in lines:
        if 'USDT' in line and '|' in line and '---' not in line and 'Symbol' not in line:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 6:
                try:
                    sym = parts[1]
                    price = float(parts[2])
                    gain_str = parts[3].strip().replace('%', '').replace('+', '')
                    gain = float(gain_str.split()[0])
                    fr_str = parts[4].strip().replace('%', '').replace('+', '')
                    fr = float(fr_str.split()[0])
                    vol = float(parts[5].strip().replace('M', ''))
                    
                    symbols.append({
                        'symbol': sym,
                        'price': price,
                        'gain_24h': gain,
                        'funding_rate': fr,
                        'volume_m': vol,
                    })
                except Exception as e:
                    pass
    return symbols

def score(sym):
    score = 0
    reasons = []
    
    if sym['gain_24h'] >= CRITERIA['min_24h_gain']:
        score += 30
        reasons.append(f"✅ Gain: {sym['gain_24h']:+.2f}%")
    else:
        return None
    
    if sym['volume_m'] >= CRITERIA['min_volume_m']:
        score += 20
        reasons.append(f"✅ Volume: ${sym['volume_m']:.1f}M")
    else:
        return None
    
    if sym['funding_rate'] <= CRITERIA['max_funding_rate']:
        score += 25
        reasons.append(f"✅ Funding: {sym['funding_rate']:.2f}% (negative)")
    else:
        reasons.append(f"⚠️  Funding: {sym['funding_rate']:.2f}% (positive)")
        score -= 10
    
    if sym['gain_24h'] > 30 and sym['funding_rate'] < -1:
        score += 25
        reasons.append(f"🔥 EXTREME SETUP")
    
    return {'score': score, 'reasons': reasons, **sym}

def main():
    print("=" * 90)
    print("🎯 STRATEGY FILTER - TLMUSDT WINNING PATTERN")
    print("=" * 90)
    print(f"Scan Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    
    data = get_scanner_data()
    symbols = parse_symbols(data)
    
    if not symbols:
        print("❌ No symbols found")
        return
    
    scored = [score(s) for s in symbols if score(s)]
    scored.sort(key=lambda x: x['score'], reverse=True)
    
    if not scored:
        print("❌ No symbols match criteria")
        return
    
    print(f"✅ Found {len(scored)} HIGH-CONVICTION candidates:\n")
    print("🏆 TOP 5 PRIORITY ENTRIES:\n")
    for i, sym in enumerate(scored[:5], 1):
        print(f"{i}. {sym['symbol']}")
        print(f"   Price: ${sym['price']:.6f}")
        print(f"   Score: {sym['score']}/100")
        for reason in sym['reasons']:
            print(f"   {reason}")
        print()
    
    print("\n" + "=" * 90)
    print("📊 ALL CANDIDATES:\n")
    print(f"{'#':<3} {'Symbol':<12} {'Price':<12} {'24h%':<8} {'FR%':<8} {'Vol(M)':<8} {'Score':<8}")
    print("-" * 90)
    
    for i, sym in enumerate(scored, 1):
        print(f"{i:<3} {sym['symbol']:<12} ${sym['price']:>10.6f} {sym['gain_24h']:>6.2f}% {sym['funding_rate']:>6.2f}% {sym['volume_m']:>6.1f}M {sym['score']:>6.0f}")

if __name__ == '__main__':
    main()
