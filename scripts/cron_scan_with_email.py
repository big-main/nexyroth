#!/usr/bin/env python3
"""
🔄 NEXYROTH CRON SCAN WITH EMAIL ALERTS
15-minute interval scan + email notifications on GO signals
"""
import subprocess
import os
from datetime import datetime
import sys
sys.path.insert(0, '/home/ubuntu/trading_sniper/scripts')
from email_alerts import send_daily_summary

def run_scanner():
    """Run the scanner and return output"""
    try:
        result = subprocess.run(
            ['python3', '/home/ubuntu/trading_sniper/scripts/scanner.py'],
            capture_output=True,
            text=True,
            timeout=30,
            cwd='/home/ubuntu/trading_sniper/scripts'
        )
        return result.stdout
    except Exception as e:
        print(f"❌ Scanner error: {e}")
        return ""

def parse_scanner_output(output):
    """Extract symbols from scanner output
    Format: Symbol | Price | 24h% | FR% | Vol(M) | Setup
    Index:  [0]    | [1]   | [2]  | [3] | [4]    | [5]
    """
    symbols = []
    in_table = False
    for line in output.split('\n'):
        if 'BITUNIX FAST-PROFIT' in line:
            in_table = True
            continue
        if in_table and '===' in line:
            break
        if in_table and 'USDT' in line and '|' in line and '---' not in line:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 5:
                try:
                    sym = parts[0]
                    price = float(parts[1])
                    # Parse gain: "+54.60%" -> 54.60
                    gain_str = parts[2].replace('%', '').replace('+', '').strip()
                    gain = float(gain_str)
                    # Parse FR: "-4.6067%" -> -4.6067
                    fr_str = parts[3].replace('%', '').replace('+', '').strip()
                    fr = float(fr_str)
                    # Parse volume: "26.4M" -> 26.4
                    vol = float(parts[4].replace('M', ''))
                    
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

def score_symbol(sym):
    """Score against TLMUSDT criteria"""
    score = 0
    
    if sym['gain_24h'] >= 15:
        score += 30
    else:
        return None
    
    if sym['volume_m'] >= 1:
        score += 20
    else:
        return None
    
    if sym['funding_rate'] <= -0.1:
        score += 25
    else:
        score -= 10
    
    if sym['gain_24h'] > 30 and sym['funding_rate'] < -1:
        score += 25
    
    return {'score': score, **sym}

def main():
    print(f"\n{'='*70}")
    print(f"🔄 NEXYROTH CRON SCAN - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*70}\n")
    
    # Run scanner
    print("📊 Running market scan...")
    scanner_output = run_scanner()
    symbols = parse_scanner_output(scanner_output)
    
    if not symbols:
        print("❌ No symbols found")
        return
    
    print(f"✅ Found {len(symbols)} symbols")
    
    # Score symbols
    scored = [score_symbol(s) for s in symbols if score_symbol(s)]
    scored.sort(key=lambda x: x['score'], reverse=True)
    
    if not scored:
        print("❌ No high-conviction candidates")
        return
    
    print(f"✅ Found {len(scored)} high-conviction candidates\n")
    
    # Display top 5
    print("🏆 TOP 5 CANDIDATES:\n")
    for i, sym in enumerate(scored[:5], 1):
        print(f"{i}. {sym['symbol']:<12} ${sym['price']:>10.6f} {sym['gain_24h']:>+6.2f}% {sym['funding_rate']:>6.2f}% Score: {sym['score']:.0f}")
    
    # Send daily summary email
    print("\n📧 Sending daily summary email...")
    send_daily_summary(scored)
    
    print(f"\n{'='*70}")
    print(f"✅ Scan complete - Next scan in 15 minutes")
    print(f"{'='*70}\n")

if __name__ == '__main__':
    main()

