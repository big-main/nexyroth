#!/usr/bin/env python3
"""
Kalshi BTC Intraday Data Collector v1.0
Runs every 15 minutes. Appends a snapshot to today's JSON log file:
  /home/ubuntu/trading_sniper/data/kalshi_btc_YYYY-MM-DD.json

Each snapshot captures:
- BTC/ETH/SOL prices
- All open Kalshi crypto markets (real price markets only)
- YES/NO bid-ask, volume, open interest per market
- Account balance
"""
import base64, time, requests, json, os
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ── Config ────────────────────────────────────────────────────────────────────
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

BASE_URL   = "https://api.elections.kalshi.com/trade-api/v2"
API_PREFIX = "/trade-api/v2"
DATA_DIR   = "/home/ubuntu/trading_sniper/data"
LOG_FILE   = "/home/ubuntu/trading_sniper/kalshi_collector.log"

CRYPTO_TICKERS  = ["KXBTC", "KXETH", "KXSOL", "KXCRYPTO", "KXXRP", "KXDOGE"]
CRYPTO_TITLE_KW = [
    "bitcoin above", "bitcoin below", "btc above", "btc below",
    "btc price", "bitcoin price", "ethereum above", "ethereum below",
    "eth above", "eth below", "eth price", "solana above", "solana below",
    "will bitcoin", "will btc", "will eth", "will ethereum", "will solana",
]

os.makedirs(DATA_DIR, exist_ok=True)

# ── Auth ──────────────────────────────────────────────────────────────────────
def auth_headers(method, path):
    pk = serialization.load_pem_private_key(KALSHI_PRIVATE_KEY_PEM.encode(), password=None)
    ts = str(int(time.time() * 1000))
    sign_path = (API_PREFIX + path).split("?")[0]
    msg = (ts + method.upper() + sign_path).encode()
    sig = pk.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
    return {
        "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }

def kget(path):
    try:
        r = requests.get(BASE_URL + path, headers=auth_headers("GET", path), timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"API error on {path}: {e}")
    return {}

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── Market filtering ──────────────────────────────────────────────────────────
def is_real_crypto_market(m):
    ticker = m.get("ticker", "").upper()
    title  = m.get("title",  "").lower()
    ticker_match = any(ticker.startswith(kw) for kw in CRYPTO_TICKERS)
    title_match  = any(kw in title for kw in CRYPTO_TITLE_KW)
    is_parlay = title.count("yes ") > 2 or "multigame" in ticker.lower()
    return (ticker_match or title_match) and not is_parlay

def get_crypto_markets():
    """Fetch all real crypto price markets from Kalshi."""
    found = {}
    # Search by known prefixes
    for prefix in CRYPTO_TICKERS:
        data = kget(f"/markets?limit=100&status=open&ticker={prefix}")
        for m in data.get("markets", []):
            if is_real_crypto_market(m):
                found[m["ticker"]] = m
    # Also check first 2 pages of open markets
    cursor = None
    for _ in range(2):
        path = "/markets?limit=200&status=open"
        if cursor:
            path += f"&cursor={cursor}"
        data = kget(path)
        for m in data.get("markets", []):
            if is_real_crypto_market(m) and m["ticker"] not in found:
                found[m["ticker"]] = m
        cursor = data.get("cursor")
        if not cursor:
            break
    return list(found.values())

def get_prices():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum,solana", "vs_currencies": "usd",
                    "include_24hr_change": "true", "include_24hr_vol": "true"},
            timeout=10,
        )
        return r.json()
    except:
        return {}

# ── Main ──────────────────────────────────────────────────────────────────────
def collect():
    now_utc = datetime.now(timezone.utc)
    today   = now_utc.strftime("%Y-%m-%d")
    data_file = os.path.join(DATA_DIR, f"kalshi_btc_{today}.json")

    log(f"Collecting snapshot #{today}...")

    # Prices
    prices = get_prices()
    btc_data = prices.get("bitcoin", {})
    eth_data = prices.get("ethereum", {})
    sol_data = prices.get("solana", {})

    # Balance
    bal = kget("/portfolio/balance")
    balance_cents = bal.get("balance", 0)

    # Crypto markets
    markets = get_crypto_markets()
    liquid  = [m for m in markets if m.get("yes_ask", 0) > 0 or m.get("no_ask", 0) > 0]

    # Build snapshot
    snapshot = {
        "ts":           now_utc.isoformat(),
        "ts_local":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "balance_cents": balance_cents,
        "btc": {
            "price":      btc_data.get("usd", 0),
            "change_24h": btc_data.get("usd_24h_change", 0),
            "vol_24h":    btc_data.get("usd_24h_vol", 0),
        },
        "eth": {
            "price":      eth_data.get("usd", 0),
            "change_24h": eth_data.get("usd_24h_change", 0),
        },
        "sol": {
            "price":      sol_data.get("usd", 0),
            "change_24h": sol_data.get("usd_24h_change", 0),
        },
        "crypto_markets_open":  len(markets),
        "crypto_markets_liquid": len(liquid),
        "markets": [
            {
                "ticker":        m.get("ticker"),
                "title":         m.get("title"),
                "yes_ask":       m.get("yes_ask", 0),
                "yes_bid":       m.get("yes_bid", 0),
                "no_ask":        m.get("no_ask", 0),
                "no_bid":        m.get("no_bid", 0),
                "volume":        m.get("volume", 0),
                "open_interest": m.get("open_interest", 0),
                "close_time":    m.get("close_time"),
                "liquid":        m.get("yes_ask", 0) > 0 or m.get("no_ask", 0) > 0,
            }
            for m in markets
        ],
    }

    # Load existing day log or start fresh
    if os.path.exists(data_file):
        with open(data_file) as f:
            day_log = json.load(f)
    else:
        day_log = {"date": today, "snapshots": []}

    day_log["snapshots"].append(snapshot)

    with open(data_file, "w") as f:
        json.dump(day_log, f, indent=2)

    log(f"Snapshot saved → {data_file} | BTC=${btc_data.get('usd',0):,.0f} | "
        f"crypto_markets={len(markets)} (liquid={len(liquid)}) | balance=${balance_cents/100:.4f}")

if __name__ == "__main__":
    collect()
