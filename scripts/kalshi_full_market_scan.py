#!/usr/bin/env python3
"""
Full Kalshi Marketplace Scanner
- Scans ALL open markets across all categories
- Shows volume, liquidity, bid/ask spreads
- Identifies best betting opportunities
"""
import base64, time, requests, json
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

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
        print(f"  ERROR {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"  EXCEPTION: {e}")
    return {}

def get_btc():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": "bitcoin,ethereum,solana", "vs_currencies": "usd", "include_24hr_change": "true"}, timeout=10)
        return r.json()
    except:
        return {}

# ─────────────────────────────────────────────────────────────────────────────
print("=" * 80)
print("  KALSHI FULL MARKETPLACE SCAN")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
print("=" * 80)

# Account balance
bal = kget("/portfolio/balance")
balance_cents = bal.get("balance", 0)
print(f"\n💰 Account Balance: ${balance_cents/100:.4f}")

# Crypto prices
prices = get_btc()
btc = prices.get("bitcoin", {}).get("usd", 0)
btc_chg = prices.get("bitcoin", {}).get("usd_24h_change", 0)
eth = prices.get("ethereum", {}).get("usd", 0)
eth_chg = prices.get("ethereum", {}).get("usd_24h_change", 0)
sol = prices.get("solana", {}).get("usd", 0)
sol_chg = prices.get("solana", {}).get("usd_24h_change", 0)
print(f"📈 BTC: ${btc:,.2f} ({btc_chg:+.2f}%) | ETH: ${eth:,.2f} ({eth_chg:+.2f}%) | SOL: ${sol:,.2f} ({sol_chg:+.2f}%)")

# ─── Fetch ALL open markets (paginate) ───────────────────────────────────────
print("\n⏳ Fetching all open markets...")
all_markets = []
cursor = None
page = 0
while True:
    path = "/markets?limit=200&status=open"
    if cursor:
        path += f"&cursor={cursor}"
    data = kget(path)
    batch = data.get("markets", [])
    all_markets.extend(batch)
    cursor = data.get("cursor")
    page += 1
    print(f"  Page {page}: +{len(batch)} markets (total: {len(all_markets)})")
    if not cursor or not batch:
        break

print(f"\n✅ Total open markets: {len(all_markets)}")

# ─── Categorize markets ───────────────────────────────────────────────────────
categories = {}
for m in all_markets:
    cat = m.get("category", "other") or "other"
    categories.setdefault(cat, []).append(m)

print("\n📊 MARKET CATEGORIES:")
for cat, mlist in sorted(categories.items(), key=lambda x: -len(x[1])):
    total_vol = sum(m.get("volume", 0) for m in mlist)
    print(f"  {cat:30s} {len(mlist):4d} markets | vol: {total_vol:,}")

# ─── Find markets WITH liquidity (bid/ask > 0) ───────────────────────────────
liquid = [m for m in all_markets if m.get("yes_ask", 0) > 0 or m.get("no_ask", 0) > 0]
print(f"\n💧 Markets with active liquidity: {len(liquid)}")

# ─── Top markets by volume ────────────────────────────────────────────────────
by_vol = sorted(all_markets, key=lambda m: m.get("volume", 0), reverse=True)
print("\n🔥 TOP 20 MARKETS BY VOLUME:")
print(f"{'#':>3} {'Ticker':<45} {'Volume':>10} {'YES ask':>8} {'NO ask':>8} {'Close':>12}")
print("-" * 95)
for i, m in enumerate(by_vol[:20], 1):
    ticker = m.get("ticker", "?")[:44]
    vol = m.get("volume", 0)
    yes_ask = m.get("yes_ask", 0)
    no_ask = m.get("no_ask", 0)
    close = m.get("close_time", "?")[:10] if m.get("close_time") else "?"
    print(f"{i:>3} {ticker:<45} {vol:>10,} {yes_ask:>8} {no_ask:>8} {close:>12}")

# ─── Crypto / Finance markets ─────────────────────────────────────────────────
crypto_kw = ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol", "xrp", "ripple", "doge", "coinbase", "binance"]
finance_kw = ["fed", "interest rate", "inflation", "cpi", "gdp", "unemployment", "s&p", "nasdaq", "dow", "stock", "market", "rate cut", "rate hike", "fomc"]
crypto_markets = [m for m in all_markets if any(k in (m.get("title","") + m.get("ticker","")).lower() for k in crypto_kw)]
finance_markets = [m for m in all_markets if any(k in (m.get("title","") + m.get("ticker","")).lower() for k in finance_kw)]

print(f"\n₿ CRYPTO MARKETS ({len(crypto_markets)} found):")
if crypto_markets:
    for m in sorted(crypto_markets, key=lambda x: x.get("volume", 0), reverse=True)[:15]:
        print(f"  [{m.get('yes_ask',0):>3}¢/{m.get('no_ask',0):>3}¢] vol={m.get('volume',0):>8,} | {m.get('ticker','?')[:40]}")
        print(f"         {m.get('title','?')[:70]}")
else:
    print("  ⚠️  No crypto markets currently open on Kalshi.")

print(f"\n🏦 FINANCE/MACRO MARKETS ({len(finance_markets)} found):")
if finance_markets:
    for m in sorted(finance_markets, key=lambda x: x.get("volume", 0), reverse=True)[:10]:
        print(f"  [{m.get('yes_ask',0):>3}¢/{m.get('no_ask',0):>3}¢] vol={m.get('volume',0):>8,} | {m.get('ticker','?')[:40]}")
        print(f"         {m.get('title','?')[:70]}")
else:
    print("  ⚠️  No finance/macro markets currently open.")

# ─── Best betting opportunities (liquid + high edge) ─────────────────────────
print("\n🎯 BEST BETTING OPPORTUNITIES (liquid markets with edge):")
opportunities = []
for m in liquid:
    yes_ask = m.get("yes_ask", 0)
    no_ask = m.get("no_ask", 0)
    yes_bid = m.get("yes_bid", 0)
    no_bid = m.get("no_bid", 0)
    vol = m.get("volume", 0)
    title = m.get("title", "")
    ticker = m.get("ticker", "")

    # Strong YES signal: yes_ask < 25 (market thinks NO is very likely → YES is cheap)
    if 5 <= yes_ask <= 25 and vol > 100:
        opportunities.append({
            "type": "YES cheap",
            "ticker": ticker,
            "title": title,
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "volume": vol,
            "edge_note": f"YES costs only {yes_ask}¢ — potential 4-20x if YES wins",
            "close": m.get("close_time", "?")[:16] if m.get("close_time") else "?",
        })
    # Strong NO signal: no_ask < 25 (market thinks YES is very likely → NO is cheap)
    elif 5 <= no_ask <= 25 and vol > 100:
        opportunities.append({
            "type": "NO cheap",
            "ticker": ticker,
            "title": title,
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "volume": vol,
            "edge_note": f"NO costs only {no_ask}¢ — potential 4-20x if NO wins",
            "close": m.get("close_time", "?")[:16] if m.get("close_time") else "?",
        })
    # Tight spread high-vol (good for scalping)
    elif yes_ask > 0 and no_ask > 0 and vol > 1000:
        spread = abs(yes_ask - no_ask)
        if spread <= 5:
            opportunities.append({
                "type": "tight spread",
                "ticker": ticker,
                "title": title,
                "yes_ask": yes_ask,
                "no_ask": no_ask,
                "volume": vol,
                "edge_note": f"Tight {spread}¢ spread, high vol — good scalp",
                "close": m.get("close_time", "?")[:16] if m.get("close_time") else "?",
            })

opportunities.sort(key=lambda x: x["volume"], reverse=True)

if opportunities:
    for opp in opportunities[:15]:
        print(f"\n  [{opp['type'].upper()}] {opp['ticker'][:45]}")
        print(f"    Title: {opp['title'][:70]}")
        print(f"    YES: {opp['yes_ask']}¢ | NO: {opp['no_ask']}¢ | Vol: {opp['volume']:,}")
        print(f"    Edge: {opp['edge_note']}")
        print(f"    Closes: {opp['close']}")
else:
    print("  No high-edge opportunities found in currently liquid markets.")

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SCAN SUMMARY")
print("=" * 80)
print(f"  Total open markets:      {len(all_markets):,}")
print(f"  Markets with liquidity:  {len(liquid):,}")
print(f"  Crypto markets:          {len(crypto_markets):,}")
print(f"  Finance/macro markets:   {len(finance_markets):,}")
print(f"  Betting opportunities:   {len(opportunities):,}")
print(f"  Account balance:         ${balance_cents/100:.4f}")
print(f"  BTC price:               ${btc:,.2f}")
print("=" * 80)

# Save results
results = {
    "scan_time": datetime.now().isoformat(),
    "balance_cents": balance_cents,
    "btc_price": btc,
    "eth_price": eth,
    "total_markets": len(all_markets),
    "liquid_markets": len(liquid),
    "crypto_markets": len(crypto_markets),
    "finance_markets": len(finance_markets),
    "top_opportunities": opportunities[:10],
    "top_by_volume": [{"ticker": m.get("ticker"), "title": m.get("title"), "volume": m.get("volume"), "yes_ask": m.get("yes_ask"), "no_ask": m.get("no_ask")} for m in by_vol[:20]],
}
with open("/home/ubuntu/kalshi_scan_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("\n✅ Results saved to /home/ubuntu/kalshi_scan_results.json")
