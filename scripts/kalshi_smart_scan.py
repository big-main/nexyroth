#!/usr/bin/env python3
"""
Kalshi Smart Market Scanner — Fast Targeted Scan
Focuses on top-volume, liquid, and crypto/finance markets only
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

def get_prices():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": "bitcoin,ethereum,solana", "vs_currencies": "usd", "include_24hr_change": "true"}, timeout=10)
        return r.json()
    except:
        return {}

print("=" * 80)
print("  KALSHI SMART MARKET SCAN")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
print("=" * 80)

# Balance
bal = kget("/portfolio/balance")
balance_cents = bal.get("balance", 0)
print(f"\n💰 Account Balance: ${balance_cents/100:.4f}")

# Crypto prices
prices = get_prices()
btc = prices.get("bitcoin", {}).get("usd", 0)
btc_chg = prices.get("bitcoin", {}).get("usd_24h_change", 0)
eth = prices.get("ethereum", {}).get("usd", 0)
eth_chg = prices.get("ethereum", {}).get("usd_24h_change", 0)
sol = prices.get("solana", {}).get("usd", 0)
sol_chg = prices.get("solana", {}).get("usd_24h_change", 0)
print(f"📈 BTC: ${btc:,.2f} ({btc_chg:+.2f}%) | ETH: ${eth:,.2f} ({eth_chg:+.2f}%) | SOL: ${sol:,.2f} ({sol_chg:+.2f}%)")

# ─── Fetch first 3 pages (600 markets) — enough to find top opportunities ────
print("\n⏳ Fetching top markets (3 pages × 200)...")
all_markets = []
cursor = None
for page in range(3):
    path = "/markets?limit=200&status=open"
    if cursor:
        path += f"&cursor={cursor}"
    data = kget(path)
    batch = data.get("markets", [])
    all_markets.extend(batch)
    cursor = data.get("cursor")
    print(f"  Page {page+1}: +{len(batch)} markets")
    if not cursor or not batch:
        break

# Also search specific event categories
print("\n⏳ Fetching crypto/finance events directly...")
for event_kw in ["KXBTC", "KXETH", "KXCRYPTO", "KXFED", "KXINFL", "KXSP500", "KXNASD"]:
    data = kget(f"/markets?limit=50&status=open&ticker={event_kw}")
    batch = data.get("markets", [])
    if batch:
        all_markets.extend(batch)
        print(f"  {event_kw}: +{len(batch)} markets")

# Deduplicate
seen = set()
unique = []
for m in all_markets:
    t = m.get("ticker", "")
    if t not in seen:
        seen.add(t)
        unique.append(m)
all_markets = unique
print(f"\n✅ Total unique markets loaded: {len(all_markets)}")

# ─── Categorize ──────────────────────────────────────────────────────────────
categories = {}
for m in all_markets:
    cat = m.get("category", "other") or "other"
    categories.setdefault(cat, []).append(m)

print("\n📊 MARKET CATEGORIES:")
for cat, mlist in sorted(categories.items(), key=lambda x: -len(x[1])):
    total_vol = sum(m.get("volume", 0) for m in mlist)
    print(f"  {cat:35s} {len(mlist):4d} markets | total vol: {total_vol:>12,}")

# ─── Liquid markets ───────────────────────────────────────────────────────────
liquid = [m for m in all_markets if m.get("yes_ask", 0) > 0 or m.get("no_ask", 0) > 0]
print(f"\n💧 Markets with active bid/ask: {len(liquid)}")

# ─── Top 25 by volume ─────────────────────────────────────────────────────────
by_vol = sorted(all_markets, key=lambda m: m.get("volume", 0), reverse=True)
print("\n🔥 TOP 25 MARKETS BY VOLUME:")
print(f"{'#':>3} {'Ticker':<42} {'Volume':>10} {'YES¢':>6} {'NO¢':>6} {'Closes':>12}")
print("-" * 85)
for i, m in enumerate(by_vol[:25], 1):
    ticker = m.get("ticker", "?")[:41]
    vol = m.get("volume", 0)
    ya = m.get("yes_ask", 0)
    na = m.get("no_ask", 0)
    close = m.get("close_time", "?")[:10] if m.get("close_time") else "?"
    print(f"{i:>3} {ticker:<42} {vol:>10,} {ya:>6} {na:>6} {close:>12}")

# ─── Crypto markets ───────────────────────────────────────────────────────────
crypto_kw = ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol", "xrp", "ripple", "doge", "coinbase", "binance", "kxbtc", "kxeth"]
crypto_markets = [m for m in all_markets if any(k in (m.get("title","") + m.get("ticker","")).lower() for k in crypto_kw)]
print(f"\n₿  CRYPTO MARKETS ({len(crypto_markets)} found):")
if crypto_markets:
    for m in sorted(crypto_markets, key=lambda x: x.get("volume", 0), reverse=True)[:15]:
        ya = m.get("yes_ask", 0)
        na = m.get("no_ask", 0)
        vol = m.get("volume", 0)
        close = m.get("close_time", "?")[:10] if m.get("close_time") else "?"
        print(f"  YES:{ya:>3}¢ NO:{na:>3}¢ vol={vol:>8,} close={close} | {m.get('ticker','?')[:40]}")
        print(f"       {m.get('title','?')[:72]}")
else:
    print("  ⚠️  No crypto markets open right now.")
    print("  Note: Kalshi crypto markets (BTC/ETH price contracts) typically open")
    print("  on specific schedule. Check kalshi.com/markets/crypto for next open time.")

# ─── Finance/Macro markets ────────────────────────────────────────────────────
fin_kw = ["fed", "interest rate", "inflation", "cpi", "gdp", "unemployment", "s&p", "nasdaq", "dow", "fomc", "rate cut", "rate hike", "treasury", "yield"]
fin_markets = [m for m in all_markets if any(k in (m.get("title","") + m.get("ticker","")).lower() for k in fin_kw)]
print(f"\n🏦 FINANCE/MACRO MARKETS ({len(fin_markets)} found):")
if fin_markets:
    for m in sorted(fin_markets, key=lambda x: x.get("volume", 0), reverse=True)[:10]:
        ya = m.get("yes_ask", 0)
        na = m.get("no_ask", 0)
        vol = m.get("volume", 0)
        close = m.get("close_time", "?")[:10] if m.get("close_time") else "?"
        print(f"  YES:{ya:>3}¢ NO:{na:>3}¢ vol={vol:>8,} close={close} | {m.get('ticker','?')[:40]}")
        print(f"       {m.get('title','?')[:72]}")
else:
    print("  ⚠️  No finance/macro markets in current batch.")

# ─── Best opportunities ───────────────────────────────────────────────────────
print("\n🎯 BEST BETTING OPPORTUNITIES (liquid, high-edge):")
opps = []
for m in liquid:
    ya = m.get("yes_ask", 0)
    na = m.get("no_ask", 0)
    yb = m.get("yes_bid", 0)
    nb = m.get("no_bid", 0)
    vol = m.get("volume", 0)
    oi = m.get("open_interest", 0)
    title = m.get("title", "")
    ticker = m.get("ticker", "")
    close = m.get("close_time", "?")[:16] if m.get("close_time") else "?"

    # YES underpriced (cheap YES = high upside)
    if 3 <= ya <= 20 and vol > 50:
        payout = round(100 / ya, 1)
        opps.append({"rank": ya, "type": f"CHEAP YES ({payout}x payout)", "ticker": ticker, "title": title,
                     "ya": ya, "na": na, "vol": vol, "oi": oi, "close": close,
                     "note": f"Bet {ya}¢ to win $1 — {payout}x return if YES"})
    # NO underpriced
    elif 3 <= na <= 20 and vol > 50:
        payout = round(100 / na, 1)
        opps.append({"rank": na, "type": f"CHEAP NO ({payout}x payout)", "ticker": ticker, "title": title,
                     "ya": ya, "na": na, "vol": vol, "oi": oi, "close": close,
                     "note": f"Bet {na}¢ to win $1 — {payout}x return if NO"})
    # Tight spread high-vol scalp
    elif ya > 0 and na > 0 and vol > 2000:
        spread = abs(ya - na)
        if spread <= 4:
            opps.append({"rank": 50 - spread, "type": f"SCALP (spread={spread}¢)", "ticker": ticker, "title": title,
                         "ya": ya, "na": na, "vol": vol, "oi": oi, "close": close,
                         "note": f"High-vol tight spread — scalp YES/NO"})

opps.sort(key=lambda x: (-x["vol"], x["rank"]))

if opps:
    for opp in opps[:15]:
        print(f"\n  [{opp['type']}]")
        print(f"  Ticker: {opp['ticker'][:50]}")
        print(f"  Title:  {opp['title'][:70]}")
        print(f"  YES:{opp['ya']}¢ | NO:{opp['na']}¢ | Vol:{opp['vol']:,} | OI:{opp['oi']:,}")
        print(f"  Note:   {opp['note']}")
        print(f"  Closes: {opp['close']}")
else:
    print("  No high-edge opportunities in current batch.")
    print("  Tip: Most Kalshi edge comes from crypto/finance markets — check back when BTC markets open.")

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SCAN SUMMARY")
print("=" * 80)
print(f"  Markets scanned:         {len(all_markets):,}")
print(f"  Markets with liquidity:  {len(liquid):,}")
print(f"  Crypto markets:          {len(crypto_markets):,}")
print(f"  Finance/macro markets:   {len(fin_markets):,}")
print(f"  Betting opportunities:   {len(opps):,}")
print(f"  Account balance:         ${balance_cents/100:.4f}")
print(f"  BTC:  ${btc:,.2f} ({btc_chg:+.2f}%)")
print(f"  ETH:  ${eth:,.2f} ({eth_chg:+.2f}%)")
print(f"  SOL:  ${sol:,.2f} ({sol_chg:+.2f}%)")
print("=" * 80)

# Save
results = {
    "scan_time": datetime.now().isoformat(),
    "balance_cents": balance_cents,
    "btc_price": btc, "eth_price": eth, "sol_price": sol,
    "btc_change_24h": btc_chg, "eth_change_24h": eth_chg,
    "total_markets_scanned": len(all_markets),
    "liquid_markets": len(liquid),
    "crypto_markets": len(crypto_markets),
    "finance_markets": len(fin_markets),
    "top_opportunities": opps[:10],
    "top_by_volume": [{"ticker": m.get("ticker"), "title": m.get("title"), "volume": m.get("volume"),
                       "yes_ask": m.get("yes_ask"), "no_ask": m.get("no_ask"),
                       "close_time": m.get("close_time")} for m in by_vol[:25]],
    "categories": {k: len(v) for k, v in categories.items()},
}
with open("/home/ubuntu/trading_sniper/kalshi_scan_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("\n✅ Full results saved to /home/ubuntu/trading_sniper/kalshi_scan_results.json")
