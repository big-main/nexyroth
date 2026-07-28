#!/usr/bin/env python3
import os
import re
import subprocess
from datetime import datetime

LOG_FILE = "/home/ubuntu/trading_sniper/scanner.log"
SNIPE_LOG = "/home/ubuntu/trading_sniper/snipe_results.log"
REPORT_DIR = "/home/ubuntu/trading_sniper/reports"
BACKTESTER = "/home/ubuntu/trading_sniper/scripts/backtester.py"
AUTO_SNIPER = "/home/ubuntu/trading_sniper/scripts/auto_sniper.py"

def generate_report():
    os.makedirs(REPORT_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(REPORT_DIR, f"daily_report_{today}.md")
    
    # 1. Get Consistency Data
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, "r") as f:
        logs = f.read()
    symbols = re.findall(r"([A-Z0-9]+USDT)\s+\|", logs)
    consistency = {}
    for sym in symbols:
        consistency[sym] = consistency.get(sym, 0) + 1
    sorted_consistency = sorted(consistency.items(), key=lambda x: x[1], reverse=True)[:5]

    # 2. Get Deep Snipe Results
    deep_snipes = ""
    if os.path.exists(SNIPE_LOG):
        with open(SNIPE_LOG, "r") as f:
            snipe_content = f.read()
            blocks = snipe_content.split("--- AUTO SNIPE:")
            if len(blocks) > 1:
                deep_snipes = blocks[-1].split("--- END AUTO SNIPE:")[0].strip()

    # 3. Run Backtests for Top 3 Movers
    backtest_results = ""
    top_movers = [s[0] for s in sorted_consistency[:3]]
    for sym in top_movers:
        try:
            res = subprocess.check_output(["python3", BACKTESTER, sym], text=True)
            backtest_results += res + "\n"
        except:
            pass

    # 4. Write Report
    with open(report_path, "w") as r:
        r.write(f"# 🎯 Daily Trading Sniper Report: {today}\n\n")
        
        r.write("## 🔥 Most Consistent Opportunities (Last 24h)\n")
        r.write("| Symbol | Frequency (Scans) | Status |\n")
        r.write("|---|---|---|\n")
        for sym, count in sorted_consistency:
            r.write(f"| **{sym}** | {count} | Active |\n")
        
        r.write("\n## 📊 Strategy Backtest (7-Day Performance)\n")
        if backtest_results:
            r.write("```\n" + backtest_results + "\n```\n")
        
        r.write("\n## 🔬 Deep Order-Book Snipes (Current Snapshot)\n")
        if deep_snipes:
            r.write("```\n" + deep_snipes + "\n```\n")

        r.write("\n\n*Report generated automatically by Manus Trading Sniper Hub.*")

    print(f"Report generated: {report_path}")

if __name__ == "__main__":
    # Update data first
    try:
        subprocess.run(["python3", AUTO_SNIPER])
    except:
        pass
    generate_report()
