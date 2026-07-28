#!/usr/bin/env python3
"""
Kalshi Auto Trader v2.0
- Scans live Kalshi markets every 15 minutes
- Identifies high-edge crypto/financial markets
- Places bets when strong edge detected (YES on sub-current-price strikes, NO on far-above strikes)
- Logs all activity to kalshi_trades.log
- Sends email alerts on trades placed
"""
import sys
import os
import time
import json
import requests
import base64
import hashlib
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

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
API_PREFIX = "/trade-api/v2"
LOG_FILE = "/home/ubuntu/trading_sniper/kalshi_trades.log"
TRADE_HISTORY_FILE = "/home/ubuntu/trading_sniper/kalshi_trade_history.json"

# ── Auth ──────────────────────────────────────────────────────────────────────
def get_auth_headers(method: str, full_path: str) -> dict:
    private_key = serialization.load_pem_private_key(
        KALSHI_PRIVATE_KEY_PEM.encode(), password=None
    )
    ts = str(int(time.time() * 1000))
    sign_path = full_path.split("?")[0]
    msg = (ts + method.upper() + sign_path).encode("utf-8")
    sig = private_key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
        "Content-Type": "application/json",
    }

def kalshi_get(path: str) -> dict:
    full_path = (API_PREFIX + path).split("?")[0]
    headers = get_auth_headers("GET", full_path)
    try:
        resp = requests.get(BASE_URL + path, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        log(f"GET {path} → {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log(f"GET {path} error: {e}")
    return {}

def kalshi_post(path: str, body: dict) -> dict:
    full_path = (API_PREFIX + path).split("?")[0]
    headers = get_auth_headers("POST", full_path)
    try:
        resp = requests.post(BASE_URL + path, headers=headers, json=body, timeout=15)
        return {"status": resp.status_code, "body": resp.json() if resp.text else {}}
    except Exception as e:
        log(f"POST {path} error: {e}")
    return {}

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def save_trade(trade: dict):
    history = []
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE) as f:
                history = json.load(f)
        except:
            history = []
    history.append(trade)
    with open(TRADE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

# ── Market Analysis ───────────────────────────────────────────────────────────
def get_btc_price() -> float:
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10
        )
        return resp.json()["bitcoin"]["usd"]
    except:
        return 0.0

def get_eth_price() -> float:
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ethereum", "vs_currencies": "usd"},
            timeout=10
        )
        return resp.json()["ethereum"]["usd"]
    except:
        return 0.0

def get_balance_cents() -> int:
    data = kalshi_get("/portfolio/balance")
    return data.get("balance", 0)

def find_crypto_markets() -> list:
    """Find all open crypto/BTC/ETH markets on Kalshi"""
    crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol", "xrp"]
    all_markets = []
    cursor = None
    for _ in range(5):  # max 5 pages
        path = "/markets?limit=100&status=open"
        if cursor:
            path += f"&cursor={cursor}"
        data = kalshi_get(path)
        markets = data.get("markets", [])
        all_markets.extend(markets)
        cursor = data.get("cursor")
        if not cursor or not markets:
            break

    crypto_markets = [
        m for m in all_markets
        if any(k in m.get("title", "").lower() or k in m.get("ticker", "").lower()
               for k in crypto_keywords)
    ]
    return crypto_markets

def score_market(market: dict, btc_price: float, eth_price: float) -> dict:
    """Score a market for betting edge. Returns dict with edge info."""
    ticker = market.get("ticker", "")
    title = market.get("title", "")
    yes_ask = market.get("yes_ask", 0)  # cost to buy YES (cents per $1)
    no_ask = market.get("no_ask", 0)    # cost to buy NO
    yes_bid = market.get("yes_bid", 0)
    no_bid = market.get("no_bid", 0)
    volume = market.get("volume", 0)
    open_interest = market.get("open_interest", 0)
    close_time = market.get("close_time", "")

    # Skip markets with no liquidity
    if yes_ask == 0 and no_ask == 0:
        return None

    # Implied probability from ask prices (in cents, 0-100 scale)
    yes_prob = yes_ask / 100.0 if yes_ask > 0 else 0.5
    no_prob = no_ask / 100.0 if no_ask > 0 else 0.5

    # Look for BTC strike markets
    edge = 0.0
    direction = None
    reason = ""

    # Pattern: "BTC above $X" or "Bitcoin above $X"
    import re
    strike_match = re.search(r'\$([0-9,]+)', title)
    if strike_match and btc_price > 0 and "btc" in ticker.lower() or "bitcoin" in title.lower():
        strike = float(strike_match.group(1).replace(",", ""))
        distance_pct = (btc_price - strike) / btc_price * 100

        if distance_pct > 0.3 and yes_ask > 0 and yes_ask < 90:
            # BTC is well above strike → YES is high probability
            edge = distance_pct * 0.5
            direction = "YES"
            reason = f"BTC ${btc_price:,.0f} is {distance_pct:.2f}% above strike ${strike:,.0f}"
        elif distance_pct < -0.3 and no_ask > 0 and no_ask < 90:
            # BTC is well below strike → NO is high probability
            edge = abs(distance_pct) * 0.5
            direction = "NO"
            reason = f"BTC ${btc_price:,.0f} is {abs(distance_pct):.2f}% below strike ${strike:,.0f}"

    if edge < 0.5 or direction is None:
        return None

    return {
        "ticker": ticker,
        "title": title,
        "direction": direction,
        "edge": edge,
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "yes_bid": yes_bid,
        "no_bid": no_bid,
        "volume": volume,
        "close_time": close_time,
        "reason": reason,
    }

def place_order(ticker: str, side: str, count: int, price_cents: int) -> dict:
    """
    Place a limit order on Kalshi.
    side: 'yes' or 'no'
    count: number of contracts
    price_cents: limit price in cents (1-99)
    """
    body = {
        "ticker": ticker,
        "client_order_id": f"nexyroth_{int(time.time())}",
        "type": "limit",
        "action": "buy",
        "side": side,
        "count": count,
        "yes_price": price_cents if side == "yes" else (100 - price_cents),
        "no_price": price_cents if side == "no" else (100 - price_cents),
    }
    return kalshi_post("/portfolio/orders", body)

# ── Main Scan Loop ────────────────────────────────────────────────────────────
def run_scan():
    log("=" * 60)
    log("KALSHI AUTO TRADER SCAN")
    log("=" * 60)

    balance = get_balance_cents()
    log(f"Balance: ${balance/100:.2f}")

    # Always scan markets even with low balance; only skip actual order placement
    if balance < 100:
        log(f"⚠️  Balance ${balance/100:.2f} — scanning only, no trades will be placed.")

    btc = get_btc_price()
    eth = get_eth_price()
    log(f"BTC: ${btc:,.2f} | ETH: ${eth:,.2f}")

    crypto_markets = find_crypto_markets()
    log(f"Found {len(crypto_markets)} crypto markets")

    if not crypto_markets:
        log("No crypto markets open. Checking all markets for any high-edge opportunities...")
        # Fall back to scanning all markets for any high-probability plays
        data = kalshi_get("/markets?limit=100&status=open")
        all_markets = data.get("markets", [])
        log(f"Total open markets: {len(all_markets)}")
        # Show top markets by volume
        by_vol = sorted(all_markets, key=lambda m: m.get("volume", 0), reverse=True)
        for m in by_vol[:5]:
            log(f"  Top market: {m.get('ticker','?')} | vol={m.get('volume',0)} | yes_ask={m.get('yes_ask',0)}")
        return

    # Score all crypto markets
    opportunities = []
    for m in crypto_markets:
        scored = score_market(m, btc, eth)
        if scored:
            opportunities.append(scored)

    opportunities.sort(key=lambda x: x["edge"], reverse=True)

    if not opportunities:
        log("No high-edge opportunities found in crypto markets.")
        for m in crypto_markets[:5]:
            log(f"  Market: {m.get('ticker','?')} | {m.get('title','?')[:50]} | yes_ask={m.get('yes_ask',0)} no_ask={m.get('no_ask',0)}")
        return

    log(f"\n🎯 TOP OPPORTUNITIES:")
    for opp in opportunities[:5]:
        log(f"  [{opp['direction']}] {opp['ticker']}")
        log(f"    {opp['title'][:60]}")
        log(f"    Edge: {opp['edge']:.2f}% | Reason: {opp['reason']}")
        log(f"    YES ask: {opp['yes_ask']}¢ | NO ask: {opp['no_ask']}¢")

    # Auto-trade top opportunity if edge > 2%
    best = opportunities[0]
    if best["edge"] >= 2.0 and balance >= 200:  # need at least $2
        side = best["direction"].lower()
        price = best["yes_ask"] if side == "yes" else best["no_ask"]
        # Bet max 10% of balance, min $1
        bet_cents = min(int(balance * 0.10), 500)  # max $5 per trade
        count = max(1, bet_cents // max(price, 1))

        log(f"\n🚀 PLACING ORDER: {side.upper()} on {best['ticker']}")
        log(f"   Count: {count} contracts @ {price}¢ = ${count*price/100:.2f}")

        result = place_order(best["ticker"], side, count, price)
        log(f"   Result: {result}")

        trade_record = {
            "timestamp": datetime.now().isoformat(),
            "ticker": best["ticker"],
            "title": best["title"],
            "side": side,
            "count": count,
            "price_cents": price,
            "cost_cents": count * price,
            "edge": best["edge"],
            "reason": best["reason"],
            "btc_price": btc,
            "result": result,
        }
        save_trade(trade_record)
        log(f"✅ Trade saved to history.")
    else:
        log(f"\nNo auto-trade: best edge {best['edge']:.2f}% (need ≥2%) or balance too low.")

if __name__ == "__main__":
    log("Kalshi Auto Trader v2.0 starting...")
    run_scan()
