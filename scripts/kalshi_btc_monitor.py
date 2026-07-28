#!/usr/bin/env python3
"""
Kalshi BTC Market Open Monitor v1.0
- Checks every 5 minutes for live BTC/ETH/crypto markets on Kalshi
- Sends email alert the moment a liquid crypto market opens
- Tracks which markets have already been alerted to avoid duplicates
- Logs all activity to kalshi_btc_monitor.log
"""
import base64, time, requests, json, os
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ── Credentials ───────────────────────────────────────────────────────────────
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

RESEND_API_KEY = os.getenv('RESEND_API_KEY', 're_dJrtkV1k_QHTeiziapzTXFvUMMS5uwWfU')
ALERT_EMAIL   = os.getenv('ALERT_EMAIL_TO', 'big.main@protonmail.com')

BASE_URL   = "https://api.elections.kalshi.com/trade-api/v2"
API_PREFIX = "/trade-api/v2"
LOG_FILE   = "/home/ubuntu/trading_sniper/kalshi_btc_monitor.log"
STATE_FILE = "/home/ubuntu/trading_sniper/kalshi_btc_monitor_state.json"

# Crypto keywords that indicate a real price market (not sports parlays)
CRYPTO_TICKERS = ["KXBTC", "KXETH", "KXSOL", "KXCRYPTO", "KXXRP", "KXDOGE"]
CRYPTO_TITLE_KW = [
    "bitcoin above", "bitcoin below", "btc above", "btc below",
    "btc price", "bitcoin price", "ethereum above", "ethereum below",
    "eth above", "eth below", "eth price", "solana above", "solana below",
    "crypto above", "crypto below", "will bitcoin", "will btc", "will eth",
    "will ethereum", "will solana",
]

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
        log(f"API error: {e}")
    return {}

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── State (track already-alerted markets) ─────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"alerted_tickers": [], "last_check": None, "total_alerts_sent": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── Email ─────────────────────────────────────────────────────────────────────
def send_alert(markets, btc_price):
    """Send email alert for newly opened crypto markets."""
    subject = f"🚨 KALSHI CRYPTO MARKETS OPEN — {len(markets)} market(s) live! BTC ${btc_price:,.0f}"

    rows = ""
    for m in markets:
        ya = m.get("yes_ask", 0)
        na = m.get("no_ask", 0)
        vol = m.get("volume", 0)
        close = m.get("close_time", "?")[:16] if m.get("close_time") else "?"
        ticker = m.get("ticker", "?")
        title = m.get("title", "?")
        rows += f"""
        <tr>
          <td style="padding:8px;border:1px solid #333;font-family:monospace;font-size:12px">{ticker[:40]}</td>
          <td style="padding:8px;border:1px solid #333">{title[:60]}</td>
          <td style="padding:8px;border:1px solid #333;text-align:center;color:#00ff88">{ya}¢</td>
          <td style="padding:8px;border:1px solid #333;text-align:center;color:#ff4444">{na}¢</td>
          <td style="padding:8px;border:1px solid #333;text-align:right">{vol:,}</td>
          <td style="padding:8px;border:1px solid #333">{close}</td>
        </tr>"""

    html = f"""
    <div style="background:#0a0a0a;color:#e0e0e0;font-family:Arial,sans-serif;padding:24px;max-width:800px">
      <div style="background:#111;border:2px solid #f7931a;border-radius:8px;padding:20px;margin-bottom:20px">
        <h1 style="color:#f7931a;margin:0 0 8px 0;font-size:24px">🚨 KALSHI CRYPTO MARKETS OPEN</h1>
        <p style="color:#aaa;margin:0;font-size:14px">{datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}</p>
      </div>

      <div style="background:#111;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:20px">
        <h2 style="color:#00ff88;margin:0 0 12px 0;font-size:18px">📊 Current Prices</h2>
        <p style="font-size:20px;margin:4px 0"><strong style="color:#f7931a">BTC:</strong> ${btc_price:,.2f}</p>
      </div>

      <div style="background:#111;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:20px">
        <h2 style="color:#00ff88;margin:0 0 12px 0;font-size:18px">🎯 Open Markets ({len(markets)} found)</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:#1a1a1a">
              <th style="padding:8px;border:1px solid #333;text-align:left">Ticker</th>
              <th style="padding:8px;border:1px solid #333;text-align:left">Title</th>
              <th style="padding:8px;border:1px solid #333">YES¢</th>
              <th style="padding:8px;border:1px solid #333">NO¢</th>
              <th style="padding:8px;border:1px solid #333">Volume</th>
              <th style="padding:8px;border:1px solid #333">Closes</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>

      <div style="background:#111;border:1px solid #f7931a;border-radius:8px;padding:16px">
        <h2 style="color:#f7931a;margin:0 0 8px 0;font-size:16px">⚡ Quick Action</h2>
        <p style="margin:4px 0;font-size:14px">→ <a href="https://kalshi.com/markets/crypto" style="color:#00ff88">Open Kalshi Crypto Markets</a></p>
        <p style="margin:4px 0;font-size:14px">→ Auto-trader will place orders if edge ≥ 2% and balance ≥ $2</p>
        <p style="margin:4px 0;color:#aaa;font-size:12px">NEXYROTH Trade Intelligence | Cloud Computer Monitor</p>
      </div>
    </div>"""

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            log(f"✅ Alert email sent to {ALERT_EMAIL}: {resp.json().get('id','?')}")
            return True
        else:
            log(f"❌ Email failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log(f"❌ Email exception: {e}")
    return False

# ── Market Detection ──────────────────────────────────────────────────────────
def is_real_crypto_market(m):
    """Return True if this is a genuine BTC/ETH price market (not a sports parlay)."""
    ticker = m.get("ticker", "").upper()
    title  = m.get("title",  "").lower()
    # Must match a known crypto ticker prefix OR a title keyword
    ticker_match = any(ticker.startswith(kw) for kw in CRYPTO_TICKERS)
    title_match  = any(kw in title for kw in CRYPTO_TITLE_KW)
    # Exclude multi-game parlays (they contain "yes " many times)
    is_parlay = title.count("yes ") > 2 or "multigame" in ticker.lower()
    return (ticker_match or title_match) and not is_parlay

def get_btc_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10)
        return r.json().get("bitcoin", {}).get("usd", 0)
    except:
        return 0

def scan_for_crypto_markets():
    """Scan Kalshi for real, liquid crypto markets. Returns list of matching markets."""
    found = []

    # 1. Search by known crypto event tickers
    for prefix in CRYPTO_TICKERS:
        data = kget(f"/markets?limit=100&status=open&ticker={prefix}")
        for m in data.get("markets", []):
            if is_real_crypto_market(m) and (m.get("yes_ask", 0) > 0 or m.get("no_ask", 0) > 0):
                found.append(m)

    # 2. Search first 2 pages of open markets for any liquid crypto
    cursor = None
    for _ in range(2):
        path = "/markets?limit=200&status=open"
        if cursor:
            path += f"&cursor={cursor}"
        data = kget(path)
        for m in data.get("markets", []):
            if is_real_crypto_market(m) and (m.get("yes_ask", 0) > 0 or m.get("no_ask", 0) > 0):
                if m not in found:
                    found.append(m)
        cursor = data.get("cursor")
        if not cursor:
            break

    # Deduplicate by ticker
    seen = set()
    unique = []
    for m in found:
        t = m.get("ticker", "")
        if t not in seen:
            seen.add(t)
            unique.append(m)

    return unique

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    state = load_state()
    alerted = set(state.get("alerted_tickers", []))

    log("Kalshi BTC Monitor — checking for open crypto markets...")
    btc = get_btc_price()
    log(f"BTC: ${btc:,.2f}")

    markets = scan_for_crypto_markets()
    log(f"Real crypto markets found: {len(markets)}")

    # Find newly opened markets (not yet alerted)
    new_markets = [m for m in markets if m.get("ticker", "") not in alerted]

    if new_markets:
        log(f"🚨 NEW CRYPTO MARKETS DETECTED: {len(new_markets)}")
        for m in new_markets:
            log(f"  → {m.get('ticker','?')} | {m.get('title','?')[:60]} | YES:{m.get('yes_ask',0)}¢ NO:{m.get('no_ask',0)}¢")

        # Send email alert
        sent = send_alert(new_markets, btc)

        if sent:
            # Mark as alerted
            for m in new_markets:
                alerted.add(m.get("ticker", ""))
            state["alerted_tickers"] = list(alerted)
            state["total_alerts_sent"] = state.get("total_alerts_sent", 0) + 1
    else:
        if markets:
            log(f"ℹ️  {len(markets)} crypto market(s) open but already alerted.")
        else:
            log("No live crypto markets right now. Will check again in 5 min.")

        # Clear alerted list for markets that are now closed
        open_tickers = {m.get("ticker", "") for m in markets}
        state["alerted_tickers"] = [t for t in alerted if t in open_tickers]

    state["last_check"] = datetime.now().isoformat()
    save_state(state)
    log(f"State saved. Total alerts sent: {state.get('total_alerts_sent', 0)}")

if __name__ == "__main__":
    run()
