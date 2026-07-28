#!/usr/bin/env python3
"""
Kalshi Universal Auto-Trader v3.0
==================================
Expands beyond crypto to scan ALL market categories on Kalshi:
- Crypto (BTC/ETH/SOL price)
- Weather (temperature, precipitation)
- Economics (CPI, jobs, GDP, Fed rate)
- Politics (elections, policy)
- Finance (S&P 500, NASDAQ, earnings)
- Sports (game outcomes — when available)

Edge detection strategies per category:
1. Crypto: Compare strike vs live price (existing logic)
2. Weather: Compare Kalshi implied vs NWS forecast
3. Economics: Compare implied vs consensus estimates
4. Finance: Compare strike vs current index level
5. General: Identify extreme mispricing (YES < 5¢ or > 95¢ with high confidence)

Runs every 15 min via cron. Places orders when edge >= 1.5% and balance >= $1.
"""
import sys
import os
import time
import json
import re
import requests
import base64
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
LOG_FILE = os.path.expanduser("~/trading_sniper/kalshi_universal.log")
TRADE_HISTORY_FILE = os.path.expanduser("~/trading_sniper/kalshi_universal_history.json")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = "big.main@protonmail.com"

# ── Config ────────────────────────────────────────────────────────────────────
MIN_EDGE = 1.5        # Minimum edge % to place a trade
MIN_BALANCE = 100     # Minimum balance in cents ($1)
MAX_BET_PCT = 0.15    # Max 15% of balance per trade
MAX_BET_CENTS = 500   # Max $5 per trade
MIN_VOLUME = 5        # Minimum contracts traded on market

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
        log(f"  GET {path} → {resp.status_code}")
    except Exception as e:
        log(f"  GET {path} error: {e}")
    return {}

def kalshi_post(path: str, body: dict) -> dict:
    full_path = (API_PREFIX + path).split("?")[0]
    headers = get_auth_headers("POST", full_path)
    try:
        resp = requests.post(BASE_URL + path, headers=headers, json=body, timeout=15)
        return {"status": resp.status_code, "body": resp.json() if resp.text else {}}
    except Exception as e:
        log(f"  POST {path} error: {e}")
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

# ── Market Data ───────────────────────────────────────────────────────────────
def get_btc_price() -> float:
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10
        )
        return resp.json()["bitcoin"]["usd"]
    except:
        return 0.0

def get_eth_price() -> float:
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ethereum", "vs_currencies": "usd"}, timeout=10
        )
        return resp.json()["ethereum"]["usd"]
    except:
        return 0.0

def get_sp500() -> float:
    """Get approximate S&P 500 level from a free source."""
    try:
        # Use Yahoo Finance informal endpoint
        resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1m&range=1d",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        data = resp.json()
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except:
        return 0.0

def get_balance_cents() -> int:
    data = kalshi_get("/portfolio/balance")
    return data.get("balance", 0)

# ── Market Scanning ───────────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol", "xrp"],
    "weather": ["temperature", "weather", "rain", "snow", "hurricane", "heat", "cold", "fahrenheit"],
    "economics": ["cpi", "inflation", "jobs", "unemployment", "gdp", "fed", "rate", "nonfarm", "payroll"],
    "finance": ["s&p", "sp500", "nasdaq", "dow", "stock", "market", "index"],
    "politics": ["election", "president", "congress", "senate", "vote", "poll"],
}

def categorize_market(market: dict) -> str:
    """Categorize a market by its title/ticker."""
    title = (market.get("title", "") + " " + market.get("ticker", "")).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in title for k in keywords):
            return cat
    return "other"

def scan_all_markets() -> list:
    """Fetch all open markets from Kalshi (paginated)."""
    all_markets = []
    cursor = None
    for _ in range(10):  # max 10 pages = 1000 markets
        path = "/markets?limit=100&status=open"
        if cursor:
            path += f"&cursor={cursor}"
        data = kalshi_get(path)
        markets = data.get("markets", [])
        all_markets.extend(markets)
        cursor = data.get("cursor")
        if not cursor or not markets:
            break
        time.sleep(0.3)  # rate limit
    return all_markets

def score_crypto_market(market: dict, btc_price: float, eth_price: float) -> dict | None:
    """Score crypto markets by comparing strike to live price."""
    title = market.get("title", "")
    ticker = market.get("ticker", "")
    yes_ask = market.get("yes_ask", 0)
    no_ask = market.get("no_ask", 0)

    if yes_ask == 0 and no_ask == 0:
        return None

    strike_match = re.search(r'\$([0-9,]+)', title)
    if not strike_match:
        return None

    strike = float(strike_match.group(1).replace(",", ""))
    
    # Determine which asset
    ref_price = 0
    if "btc" in ticker.lower() or "bitcoin" in title.lower():
        ref_price = btc_price
    elif "eth" in ticker.lower() or "ethereum" in title.lower():
        ref_price = eth_price
    
    if ref_price == 0:
        return None

    distance_pct = (ref_price - strike) / ref_price * 100
    
    edge = 0.0
    direction = None
    reason = ""

    if distance_pct > 0.5 and yes_ask > 0 and yes_ask < 92:
        edge = distance_pct * 0.6
        direction = "YES"
        reason = f"Price ${ref_price:,.0f} is {distance_pct:.1f}% above strike ${strike:,.0f}"
    elif distance_pct < -0.5 and no_ask > 0 and no_ask < 92:
        edge = abs(distance_pct) * 0.6
        direction = "NO"
        reason = f"Price ${ref_price:,.0f} is {abs(distance_pct):.1f}% below strike ${strike:,.0f}"

    if edge < MIN_EDGE or direction is None:
        return None

    return {
        "ticker": ticker, "title": title, "category": "crypto",
        "direction": direction, "edge": edge,
        "yes_ask": yes_ask, "no_ask": no_ask,
        "volume": market.get("volume", 0),
        "close_time": market.get("close_time", ""),
        "reason": reason,
    }

def score_finance_market(market: dict, sp500: float) -> dict | None:
    """Score S&P 500 / NASDAQ markets by comparing strike to live index."""
    title = market.get("title", "")
    ticker = market.get("ticker", "")
    yes_ask = market.get("yes_ask", 0)
    no_ask = market.get("no_ask", 0)

    if yes_ask == 0 and no_ask == 0:
        return None
    if sp500 == 0:
        return None

    # Look for numeric strike in title
    strike_match = re.search(r'([0-9,]+)', title)
    if not strike_match:
        return None

    try:
        strike = float(strike_match.group(1).replace(",", ""))
    except:
        return None

    # Only process if strike is in reasonable S&P range
    if strike < 3000 or strike > 8000:
        return None

    distance_pct = (sp500 - strike) / sp500 * 100
    
    edge = 0.0
    direction = None
    reason = ""

    if distance_pct > 0.3 and yes_ask > 0 and yes_ask < 92:
        edge = distance_pct * 0.5
        direction = "YES"
        reason = f"S&P ${sp500:,.0f} is {distance_pct:.1f}% above strike {strike:,.0f}"
    elif distance_pct < -0.3 and no_ask > 0 and no_ask < 92:
        edge = abs(distance_pct) * 0.5
        direction = "NO"
        reason = f"S&P ${sp500:,.0f} is {abs(distance_pct):.1f}% below strike {strike:,.0f}"

    if edge < MIN_EDGE or direction is None:
        return None

    return {
        "ticker": ticker, "title": title, "category": "finance",
        "direction": direction, "edge": edge,
        "yes_ask": yes_ask, "no_ask": no_ask,
        "volume": market.get("volume", 0),
        "close_time": market.get("close_time", ""),
        "reason": reason,
    }

def score_extreme_mispricing(market: dict) -> dict | None:
    """
    Find markets where the implied probability is extreme (< 5% or > 95%)
    but the ask price doesn't reflect it — potential free money.
    Also catches markets expiring very soon where outcome is nearly certain.
    """
    title = market.get("title", "")
    ticker = market.get("ticker", "")
    yes_ask = market.get("yes_ask", 0)
    no_ask = market.get("no_ask", 0)
    volume = market.get("volume", 0)
    close_time = market.get("close_time", "")

    if yes_ask == 0 and no_ask == 0:
        return None
    if volume < MIN_VOLUME:
        return None

    # Strategy: Buy YES when it's very cheap (< 8¢) on markets closing soon
    # or buy NO when YES is very expensive (> 92¢) — these are often mispriced
    edge = 0.0
    direction = None
    reason = ""

    # Cheap YES on expiring markets (closing within 24h)
    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            hours_left = (close_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            
            if hours_left < 24 and hours_left > 0:
                if yes_ask > 0 and yes_ask <= 8:
                    # Very cheap YES on expiring market — potential lottery ticket
                    edge = (100 - yes_ask) / yes_ask * 0.1  # Risk-adjusted
                    direction = "YES"
                    reason = f"YES at {yes_ask}¢ expiring in {hours_left:.0f}h — lottery play"
                elif no_ask > 0 and no_ask <= 8:
                    edge = (100 - no_ask) / no_ask * 0.1
                    direction = "NO"
                    reason = f"NO at {no_ask}¢ expiring in {hours_left:.0f}h — lottery play"
        except:
            pass

    # High-confidence plays: YES > 93¢ means market thinks it's near-certain
    # If we can buy YES at 93-97¢, the expected value is positive if probability > price
    if yes_ask >= 93 and yes_ask <= 97 and volume >= 20:
        # These are "near-certain" outcomes — small edge but high win rate
        edge = 2.0  # Fixed edge for near-certain plays
        direction = "YES"
        reason = f"Near-certain YES at {yes_ask}¢ (vol={volume}) — high win rate"

    if edge < MIN_EDGE or direction is None:
        return None

    return {
        "ticker": ticker, "title": title, "category": categorize_market(market),
        "direction": direction, "edge": edge,
        "yes_ask": yes_ask, "no_ask": no_ask,
        "volume": volume,
        "close_time": close_time,
        "reason": reason,
    }

# ── Order Placement ───────────────────────────────────────────────────────────
def place_order(ticker: str, side: str, count: int, price_cents: int) -> dict:
    body = {
        "ticker": ticker,
        "client_order_id": f"nexyroth_uni_{int(time.time())}",
        "type": "limit",
        "action": "buy",
        "side": side,
        "count": count,
        "yes_price": price_cents if side == "yes" else (100 - price_cents),
        "no_price": price_cents if side == "no" else (100 - price_cents),
    }
    return kalshi_post("/portfolio/orders", body)

def send_trade_alert(opp: dict, count: int, cost: float, balance: float):
    """Send email alert when a trade is placed."""
    subject = f"🎯 Kalshi Trade: {opp['direction']} on {opp['ticker']} | Edge: {opp['edge']:.1f}%"
    html = f"""
    <div style="font-family:'Courier New',monospace;background:#0a0a1a;color:#e0e0e0;padding:20px;border-radius:12px">
        <h2 style="color:#00ff88;margin:0 0 12px">🎯 KALSHI TRADE PLACED</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr><td style="color:#888;padding:4px 8px">Market</td><td style="color:#fff;padding:4px 8px">{opp['title'][:60]}</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Ticker</td><td style="color:#22d3ee;padding:4px 8px">{opp['ticker']}</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Direction</td><td style="color:#00ff88;padding:4px 8px;font-weight:bold">{opp['direction']}</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Category</td><td style="color:#a855f7;padding:4px 8px">{opp['category']}</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Edge</td><td style="color:#ffd700;padding:4px 8px">{opp['edge']:.1f}%</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Contracts</td><td style="color:#fff;padding:4px 8px">{count}</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Cost</td><td style="color:#fff;padding:4px 8px">${cost:.2f}</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Reason</td><td style="color:#e0e0e0;padding:4px 8px;font-size:11px">{opp['reason']}</td></tr>
            <tr><td style="color:#888;padding:4px 8px">Balance After</td><td style="color:#fff;padding:4px 8px">${(balance - cost*100)/100:.2f}</td></tr>
        </table>
        <p style="color:#444;font-size:9px;margin-top:12px">Kalshi Universal Trader v3.0 • NEXYROTH</p>
    </div>
    """
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=10
        )
    except:
        pass

# ── Main Scan ─────────────────────────────────────────────────────────────────
def run_scan():
    log("=" * 60)
    log("KALSHI UNIVERSAL AUTO-TRADER v3.0 — Full Market Scan")
    log("=" * 60)

    balance = get_balance_cents()
    log(f"Balance: ${balance/100:.2f}")

    # Get reference prices
    btc = get_btc_price()
    eth = get_eth_price()
    sp500 = get_sp500()
    log(f"BTC: ${btc:,.2f} | ETH: ${eth:,.2f} | S&P500: {sp500:,.2f}")

    # Scan all markets
    all_markets = scan_all_markets()
    log(f"Total open markets: {len(all_markets)}")

    # Categorize
    by_cat = {}
    for m in all_markets:
        cat = categorize_market(m)
        by_cat.setdefault(cat, []).append(m)
    
    for cat, markets in sorted(by_cat.items()):
        log(f"  {cat}: {len(markets)} markets")

    # Score all markets
    opportunities = []

    # 1. Crypto markets
    for m in by_cat.get("crypto", []):
        scored = score_crypto_market(m, btc, eth)
        if scored:
            opportunities.append(scored)

    # 2. Finance markets
    for m in by_cat.get("finance", []):
        scored = score_finance_market(m, sp500)
        if scored:
            opportunities.append(scored)

    # 3. Extreme mispricing across ALL categories
    for m in all_markets:
        scored = score_extreme_mispricing(m)
        if scored:
            # Avoid duplicates
            if not any(o["ticker"] == scored["ticker"] for o in opportunities):
                opportunities.append(scored)

    opportunities.sort(key=lambda x: x["edge"], reverse=True)

    if not opportunities:
        log("No opportunities found above threshold.")
        # Show top markets by volume for awareness
        by_vol = sorted(all_markets, key=lambda m: m.get("volume", 0), reverse=True)
        log("\nTop 5 markets by volume:")
        for m in by_vol[:5]:
            log(f"  {m.get('ticker','?')} | vol={m.get('volume',0)} | yes={m.get('yes_ask',0)}¢")
        return

    log(f"\n🎯 FOUND {len(opportunities)} OPPORTUNITIES:")
    for opp in opportunities[:8]:
        log(f"  [{opp['category'].upper()}] {opp['direction']} {opp['ticker']}")
        log(f"    {opp['title'][:55]}")
        log(f"    Edge: {opp['edge']:.1f}% | {opp['reason']}")

    # Auto-trade best opportunity if balance allows
    best = opportunities[0]
    if best["edge"] >= MIN_EDGE and balance >= MIN_BALANCE:
        side = best["direction"].lower()
        price = best["yes_ask"] if side == "yes" else best["no_ask"]
        
        if price <= 0 or price >= 99:
            log("  ⚠️ Price out of range, skipping.")
            return

        bet_cents = min(int(balance * MAX_BET_PCT), MAX_BET_CENTS)
        count = max(1, bet_cents // max(price, 1))
        cost = count * price / 100

        log(f"\n🚀 PLACING ORDER: {side.upper()} on {best['ticker']}")
        log(f"   Count: {count} contracts @ {price}¢ = ${cost:.2f}")

        result = place_order(best["ticker"], side, count, price)
        log(f"   Result: {result}")

        trade_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": best["ticker"],
            "title": best["title"],
            "category": best["category"],
            "side": side,
            "count": count,
            "price_cents": price,
            "cost_cents": int(cost * 100),
            "edge": best["edge"],
            "reason": best["reason"],
            "btc_price": btc,
            "sp500": sp500,
            "result": result,
        }
        save_trade(trade_record)
        send_trade_alert(best, count, cost, balance)
        log("✅ Trade saved and alert sent.")
    else:
        if balance < MIN_BALANCE:
            log(f"\n⚠️ Balance ${balance/100:.2f} below minimum ${MIN_BALANCE/100:.2f}")
        else:
            log(f"\nBest edge {best['edge']:.1f}% — monitoring only.")

    log("=" * 60)

if __name__ == "__main__":
    run_scan()
