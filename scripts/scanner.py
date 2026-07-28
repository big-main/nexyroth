#!/usr/bin/env python3
import requests
import json
import argparse
from datetime import datetime, timezone

BITUNIX_API = 'https://fapi.bitunix.com'
KALSHI_API = 'https://api.elections.kalshi.com/trade-api/v2'

def scan_bitunix(min_vol=1.0, top_n=15):
    print(f"\n=== 🚀 BITUNIX FAST-PROFIT SCANNER (Min Vol: ${min_vol}M) ===")
    try:
        r_t = requests.get(f'{BITUNIX_API}/api/v1/futures/market/tickers', timeout=10)
        tickers = r_t.json().get('data', [])
        def get_pct(t):
            try:
                l, o = float(t.get('lastPrice', 0)), float(t.get('open', 0))
                return ((l-o)/o)*100 if o else 0
            except: return 0
        tickers.sort(key=get_pct, reverse=True)
        print(f"{'Symbol':<12} | {'Price':>10} | {'24h%':>8} | {'FR%':>10} | {'Vol(M)':>7} | {'Setup'}")
        print("-" * 75)
        for t in tickers[:top_n]:
            sym = t['symbol']
            try:
                fr_r = requests.get(f'{BITUNIX_API}/api/v1/futures/market/funding_rate', params={'symbol': sym}, timeout=5)
                fr = float(fr_r.json().get('data', {}).get('fundingRate', 0)) * 100
                vol = float(t.get('quoteVol', 0)) / 1e6
                pct = get_pct(t)
                if vol > min_vol:
                    setup = "MOMENTUM"
                    if fr < -20: setup = "SQUEEZE / FUNDING ARB"
                    elif fr > 20: setup = "SHORT OPPORTUNITY"
                    elif pct > 50 and fr > 0: setup = "DANGER (Longs Paying)"
                    print(f"{sym:<12} | {t['lastPrice']:>10} | {pct:>+7.2f}% | {fr:>+10.4f}% | {vol:>7.1f}M | {setup}")
            except Exception as e: pass
    except Exception as e: print(f"Bitunix Scan Error: {e}")

def scan_kalshi(top_n=5):
    print(f"\n=== 📊 KALSHI LIQUIDITY SCANNER (Top {top_n}) ===")
    try:
        r_k = requests.get(f'{KALSHI_API}/events', params={'status': 'open', 'with_nested_markets': 'true'}, timeout=10)
        events = r_k.json().get('events', [])
        events.sort(key=lambda x: x.get('volume_24h', 0), reverse=True)
        for e in events[:top_n]:
            vol = e.get("volume_24h", 0) / 1e3
            print(f"{e['title'][:50]:<50} | Vol: ${vol:.1f}K")
    except Exception as e: print(f"Kalshi Scan Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bitunix & Kalshi Scanner")
    parser.add_argument("--min-vol", type=float, default=1.0, help="Minimum 24h volume in millions for Bitunix")
    parser.add_argument("--top", type=int, default=15, help="Number of top assets to display")
    args = parser.parse_args()
    print(f"Scan Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    scan_bitunix(min_vol=args.min_vol, top_n=args.top)
    scan_kalshi(top_n=5)
