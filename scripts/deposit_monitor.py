#!/usr/bin/env python3
"""
Deposit Monitor — polls Bitunix futures balance every 2 minutes.
Fires the auto-executor immediately when balance >= MIN_BALANCE.
Sends email notification when deposit detected.
Auth: Double-SHA256 (same as auto-executor)
"""
import os, time, hashlib, random, string, json, requests
from datetime import datetime

BITUNIX_API  = "https://fapi.bitunix.com"
MIN_BALANCE  = 3.0
CHECK_EVERY  = 120  # seconds
RESEND_KEY   = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL  = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")
LOG_FILE     = os.path.expanduser("~/trading_sniper/deposit_monitor.log")

def _read_secret(env_var, path):
    val = os.getenv(env_var, "")
    if not val and os.path.exists(path):
        try:
            with open(path) as f: val = f.read().strip()
        except: pass
    return val

API_KEY    = _read_secret("BITUNIX_API_KEY",    os.path.expanduser("~/.secrets/bitunix_api_key"))
SECRET_KEY = _read_secret("BITUNIX_SECRET_KEY", os.path.expanduser("~/.secrets/bitunix_secret_key"))

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f: f.write(line + "\n")
    except: pass

def make_sign(query_params='', body=''):
    """Double-SHA256: digest = SHA256(nonce+ts+apiKey+queryParams+body), sign = SHA256(digest+secretKey)"""
    ts = str(int(time.time() * 1000))
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    digest = hashlib.sha256((nonce + ts + API_KEY + query_params + body).encode()).hexdigest()
    sign = hashlib.sha256((digest + SECRET_KEY).encode()).hexdigest()
    return ts, nonce, sign

def get_balance():
    try:
        # Query params sorted in ASCII order: marginCoin=USDT → "marginCoinUSDT"
        query_params = "marginCoinUSDT"
        ts, nonce, sign = make_sign(query_params=query_params)
        headers = {
            "api-key": API_KEY, "sign": sign,
            "timestamp": ts, "nonce": nonce,
            "Content-Type": "application/json"
        }
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/account",
            params={"marginCoin": "USDT"},
            headers=headers,
            timeout=10
        )
        resp = r.json()
        if resp.get("code") != 0:
            log(f"  API error: {resp.get('msg', resp)}")
            return -1.0
        data = resp.get("data", {})
        return float(data.get("available", 0) or 0)
    except Exception as e:
        log(f"  Balance check error: {e}")
        return -1.0

def send_email(subject, body):
    try:
        requests.post("https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": [ALERT_EMAIL],
                  "subject": subject, "text": body}, timeout=10)
    except: pass

def fire_executor():
    log("  🚀 Firing auto-executor NOW...")
    os.system("cd ~/trading_sniper && python3 scripts/bitunix_auto_executor.py >> bitunix_auto_executor.log 2>&1 &")

def main():
    log("=" * 60)
    log("NEXYROTH Deposit Monitor — watching for Bitunix deposit")
    log(f"  Checking every {CHECK_EVERY}s | Min balance: ${MIN_BALANCE}")
    log("=" * 60)

    if not API_KEY or not SECRET_KEY:
        log("  ❌ No API keys found — exiting")
        return

    notified = False
    while True:
        balance = get_balance()
        if balance < 0:
            log(f"  ⏳ Could not read balance — retrying in {CHECK_EVERY}s")
        elif balance < MIN_BALANCE:
            log(f"  ⏳ Balance ${balance:.4f} USDT — waiting for deposit (need ${MIN_BALANCE}+)")
        else:
            log(f"  ✅ DEPOSIT DETECTED! Balance: ${balance:.4f} USDT")
            if not notified:
                send_email(
                    "🚀 NEXYROTH: Deposit Detected — Auto-Executor Firing",
                    f"Bitunix futures balance: ${balance:.4f} USDT\n\n"
                    f"Auto-executor is now placing trades on zero-fee tokens.\n"
                    f"Top opportunities (last scan):\n"
                    f"  LABUSDT: +2.02%/8h = 2,211% annualized\n"
                    f"  XRPUSDT: +1.00%/8h = 1,091% annualized\n"
                    f"  DOGEUSDT: +0.95%/8h = 1,037% annualized\n\n"
                    f"Check your Bitunix account for open positions.\n"
                    f"Positions are managed automatically every 10 minutes."
                )
                notified = True
            fire_executor()
            log("  ✅ Executor fired. Checking again in 10 min.")
            time.sleep(600)
            notified = False
            continue

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
