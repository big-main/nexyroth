#!/usr/bin/env python3
import subprocess
import re
import os
import json
from datetime import datetime

SCANNER_SCRIPT = "/home/ubuntu/trading_sniper/scripts/scanner.py"
SNIPER_SCRIPT = "/home/ubuntu/trading_sniper/scripts/orderbook_sniper.py"
SNIPE_LOG = "/home/ubuntu/trading_sniper/snipe_results.log"

def get_top_movers():
    try:
        output = subprocess.check_output(["python3", SCANNER_SCRIPT, "--top", "5"], text=True)
        # Extract symbols from the Bitunix scanner table
        symbols = re.findall(r"([A-Z0-9]+USDT)\s+\|", output)
        return list(dict.fromkeys(symbols))[:3] # Top 3 unique symbols
    except Exception as e:
        print(f"Error getting top movers: {e}")
        return []

def run_snipes():
    symbols = get_top_movers()
    if not symbols:
        print("No symbols found to snipe.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(SNIPE_LOG, "a") as log:
        log.write(f"\n\n--- AUTO SNIPE: {timestamp} ---\n")
        for sym in symbols:
            print(f"Sniping {sym}...")
            try:
                result = subprocess.check_output(["python3", SNIPER_SCRIPT, sym], text=True)
                log.write(result + "\n")
            except Exception as e:
                log.write(f"Failed to snipe {sym}: {e}\n")
        log.write(f"--- END AUTO SNIPE: {timestamp} ---\n")

if __name__ == "__main__":
    run_snipes()
