#!/usr/bin/env python3
"""
Kalshi API Trader — RSA Authentication + Order Placement
Uses Kalshi's RSA-signed authentication for trade-api v2
"""
import base64
import hashlib
import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ── Credentials ──────────────────────────────────────────────────────────────
KALSHI_KEY_ID = "c8be0335-1b9c-4c9c-8254-f0bc86f85e9b"
KALSHI_PRIVATE_KEY_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAixfgY0gYvxIbgwl6liQRDroowQk/F3DdoPaOjDvvb5bTPwvS
6LYLTq62BmUSyqiJ4HUAqXvMc00b+0eBhPmHfL0Z7pF31miSPcXrpyYGYLJTHuP9
81ZMM7arxIuzVfVKdqkGa+1zLN1VbZammuMAi67tQ2TKnlG5lVcWB/7nbtAVOT3M
DNkv8EFYJVc7HNO/2A/UeTFxJfNRwcH7vuQfAQwAXMK0BgL3hb0m7DE0rm21MKly
8IS9HhvXoR0G1kBr0E88Sjj5o8O4d/V2LRPnS8b8Pyes+ymqyTDt9VRvffxy6fua
zp1/oPhs9emHZ5uzCD6JcMvwIVC3hPeM22/gKwIDAQABAoIBAAdJHhiy6rYO2Ila
8BtdCY0fAG7EnyYt0eqkavINEe0aMbfCngEHflhF8qArRHE3Ng7D+QRDEkscrKgu
nQVeSzhtOd1J9Xt7FuQxTSTbtD6H9mVX5bsxLqTHFe4PZl8oDfSqMo+N9bOIi4sz
myMrEusr2oyvXlwtl9cq7IaSQ03O5obcKc1M9E2nmjJ85BFrirEEIUm+AA5oHKvS
rU1FFWM5RN5eHsvX9zKvHI1KxH4gFHuI1ybHRRALWjxFFAbaj9VWHrjb29GG6wau
LVkNEFTfKAAuWuYKmAj7yajad65CQrkbWUZqnPyI85O7bOZKxY2zrrawpIrUSMu9
C4N3hFkCgYEAwH1rAkPGJMZxesEn+Qc9wkr0Uapcr8y0ZHmoZoBGTR0Ev7Q5tP2i
aweGEnMhmsSYsEFAAEyd+NSW1Vn1m3G5PPW1clkvsSwjfFlTV05y6cR670ZDSbPb
U5832VumHhj0rdyySeV+FRM5C9hdjHaNDQHFglYuDFlhUPblY89lKLkCgYEAuPxV
I3mo109BcsDGB1VUJJ5tcN2+8krxBawqDgR3mV827P2woZqE8DRiVlG0QfBaHJPc
7IpKcVjVx4ZoUJ64zzP82MHFX+iJQEncaNS+XZzQGGDcRkVxNDQtI53dFwR7PWTV
A7YH/FDCsIjlt1K7fNRz31VCZ/0T05T4aGiElgMCgYEArQdQTK3djCsx0NWWd/0x
X9h+vHY2cPTC51qQrOr7xs+h+C0qfm5MNIeD1kvV1kiItE9DF8HHcuiuWURPSha1
G34HR62x+EIj9+BX0TA8jbRHiZSQYc0iB44k5ubCcWWfdDXhshlv98Pa0LICjYP3
kMyZ3WpYZFNn7h6x3sGMPkkCgYEAgox53VZfpMvnKYAIgWZjwpAYNl4YAtCGtnUh
HNFkQlYi4i/LdtEg3pBpkfeJWjuwrJhhgoG6NbH29R/TAIpzbK+I0sQ1chEew8Mc
jNMPIeuoJHw/GEyrrqbf8FHZlQPxoYtGlZ7ildu8+m8yhyUY8ejReZynB9JgKqLo
iG6ym1cCgYBlJght71kJYERYhtZj3mzHiIU0WPaBzAcngSwYtniFmTYlxlQYpYJ7
GRiFbBPKxNqyhIpYfl5+nsM6ARfi0d8FNnakH3Nyv3bG1ufJwCr4SjZOU/Cg/tV9
QEGYEhyorUzfqar8BCWTO8OMthkDKCWu2bfXZ9X+93jkv20rPwCQTA==
-----END RSA PRIVATE KEY-----"""

BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"
# Note: trading-api redirects to elections API for some routes
# Try both
BASE_URLS = [
    "https://api.elections.kalshi.com/trade-api/v2",
]

# ── Auth ──────────────────────────────────────────────────────────────────────
def get_auth_headers(method: str, path: str) -> dict:
    """Generate RSA-signed auth headers for Kalshi API"""
    private_key = serialization.load_pem_private_key(
        KALSHI_PRIVATE_KEY_PEM.encode(), password=None
    )
    
    # Timestamp in milliseconds
    ts = str(int(time.time() * 1000))
    
    # Message to sign: timestamp + method + path (no query string)
    msg_string = ts + method.upper() + path
    msg_bytes = msg_string.encode("utf-8")
    
    # Sign with RSA-PSS SHA256 (Kalshi requirement per docs)
    signature = private_key.sign(
        msg_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=32  # SHA256 digest length = 32 bytes
        ),
        hashes.SHA256(),
    )
    
    sig_b64 = base64.b64encode(signature).decode("utf-8")
    
    return {
        "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "Content-Type": "application/json",
    }


def kalshi_get(path: str, params: dict = None) -> dict:
    """Make authenticated GET request to Kalshi API"""
    # Kalshi requires signing the FULL path from root: /trade-api/v2/...
    # path here is relative (e.g. /portfolio/balance), so prepend the prefix
    API_PREFIX = "/trade-api/v2"
    sign_path = (API_PREFIX + path).split("?")[0]
    headers = get_auth_headers("GET", sign_path)
    
    for base in BASE_URLS:
        try:
            url = base + path
            resp = requests.get(url, headers=headers, params=params, timeout=10, allow_redirects=False)
            if resp.status_code in (301, 302, 307, 308):
                continue
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"  [{base}] {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"  [{base}] Error: {e}")
    return {}


def kalshi_post(path: str, body: dict) -> dict:
    """Make authenticated POST request to Kalshi API"""
    API_PREFIX = "/trade-api/v2"
    sign_path = (API_PREFIX + path).split("?")[0]
    headers = get_auth_headers("POST", sign_path)
    
    for base in BASE_URLS:
        try:
            url = base + path
            resp = requests.post(url, headers=headers, json=body, timeout=10, allow_redirects=False)
            if resp.status_code in (301, 302, 307, 308):
                continue
            return {"status_code": resp.status_code, "body": resp.json() if resp.text else {}}
        except Exception as e:
            print(f"  [{base}] Error: {e}")
    return {}


# ── Account ───────────────────────────────────────────────────────────────────
def get_balance() -> float:
    """Get account balance in cents"""
    data = kalshi_get("/portfolio/balance")
    if data:
        balance_cents = data.get("balance", 0)
        print(f"✅ Account Balance: ${balance_cents/100:.2f}")
        return balance_cents
    print("❌ Could not fetch balance")
    return 0


# ── Markets ───────────────────────────────────────────────────────────────────
def get_markets_for_event(event_ticker: str) -> list:
    """Get all markets for an event"""
    data = kalshi_get(f"/markets?event_ticker={event_ticker}&limit=50")
    return data.get("markets", [])


def find_best_market(event_ticker: str, target_strike: float, side: str) -> dict:
    """Find the market closest to target strike"""
    markets = get_markets_for_event(event_ticker)
    
    best = None
    best_diff = float('inf')
    
    for m in markets:
        if m.get('status') != 'active':
            continue
        subtitle = m.get('subtitle', '')
        ticker = m.get('ticker', '')
        yes_ask = m.get('yes_ask', 0)
        no_ask = m.get('no_ask', 0)
        
        # Parse strike from subtitle
        try:
            # Format: "$64,000 to 64,099.99" or "$64,000 or above"
            import re
            nums = re.findall(r'[\d,]+\.?\d*', subtitle.replace(',', ''))
            if nums:
                strike_val = float(nums[0])
                diff = abs(strike_val - target_strike)
                if diff < best_diff:
                    best_diff = diff
                    best = {
                        'ticker': ticker,
                        'subtitle': subtitle,
                        'yes_ask': yes_ask,
                        'no_ask': no_ask,
                        'strike': strike_val,
                        'side': side
                    }
        except:
            pass
    
    return best


# ── Order Placement ───────────────────────────────────────────────────────────
def place_order(ticker: str, side: str, count: int, price_cents: int) -> dict:
    """
    Place a limit order on Kalshi
    ticker: market ticker e.g. KXBTCD-26JUL1013-B64050
    side: 'yes' or 'no'
    count: number of contracts (1 contract = $0.01 to $1.00)
    price_cents: price in cents (1-99)
    """
    body = {
        "ticker": ticker,
        "action": "buy",
        "side": side,
        "type": "limit",
        "count": count,
        "yes_price": price_cents if side == "yes" else 100 - price_cents,
        "no_price": price_cents if side == "no" else 100 - price_cents,
        "client_order_id": f"nexyroth_{int(time.time())}_{ticker[:10]}",
    }
    
    print(f"\n📤 Placing order: {side.upper()} {count}x {ticker} @ {price_cents}¢")
    result = kalshi_post("/portfolio/orders", body)
    return result


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("🎲 KALSHI TRADER — NEXYROTH SYSTEM")
    print("=" * 70)
    
    current_edt = datetime.now(timezone.utc) - timedelta(hours=4)
    print(f"Time: {current_edt.strftime('%H:%M:%S EDT')}\n")
    
    # Step 1: Test auth + get balance
    print("📡 Testing authentication...")
    balance = get_balance()
    
    if balance == 0:
        print("\n⚠️  Auth may have failed. Trying alternate approach...")
        # Try fetching portfolio positions as auth test
        data = kalshi_get("/portfolio/positions")
        print(f"Portfolio response: {data}")
