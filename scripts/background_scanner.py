#!/usr/bin/env python3
import time
import subprocess
import os
from datetime import datetime

LOG_FILE = "/home/ubuntu/trading_sniper/scanner.log"
SCANNER_SCRIPT = "/home/ubuntu/trading_sniper/scripts/scanner.py"

def run_scan():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as log:
        log.write(f"\n\n--- SCAN START: {timestamp} ---\n")
        try:
            result = subprocess.check_output(["python3", SCANNER_SCRIPT, "--min-vol", "0.5"], stderr=subprocess.STDOUT, text=True)
            log.write(result)
        except subprocess.CalledProcessError as e:
            log.write(f"Scan failed: {e.output}\n")
        log.write(f"--- SCAN END: {timestamp} ---\n")

if __name__ == "__main__":
    print("Starting 24/7 Trading Sniper Background Service...")
    while True:
        run_scan()
        # Sleep for 15 minutes
        time.sleep(900)
