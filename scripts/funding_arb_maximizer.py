#!/usr/bin/env python3
"""
NEXYROTH Funding Rate Arbitrage Maximizer v1.0
==============================================
Dedicated scanner for extreme funding rate opportunities on Bitunix.
This is the LOWEST RISK, HIGHEST CONSISTENCY strategy:
- When FR is deeply negative → shorts are paying longs → go LONG (free money)
- When FR is extremely positive → longs are paying shorts → go SHORT
- FR is paid every 8 hours → position earns funding passively

Strategy:
1. Scan ALL Bitunix symbols (not just watchlist) for extreme FR
2. Rank by absolute FR magnitude
3. Filter for sufficient volume/liquidity
4. Calculate expected daily yield from FR alone
5. Send IMMEDIATE email alert for top opportunities
6. Track FR history to detect FR compression (exit signal)

Risk: Very low — you're paid to hold the position.
Edge: FR extremes mean-revert within 24-72h, so you profit from:
  a) FR payments while holding (guaranteed income)
  b) Price movement toward equilibrium (bonus profit)

Runs every 10 minutes via cron.
"""
import os
import json
import time
import requests
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
BITUNIX_API = "https://fapi.bitunix.com"
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")
LOG_FILE = "/home/ubuntu/trading_sniper/funding_arb_maximizer.log"
STATE_FILE = "/home/ubuntu/trading_sniper/data/funding_arb_state.json"
HISTORY_FILE = "/home/ubuntu/trading_sniper/data/funding_arb_history.json"

# Thresholds
EXTREME_FR_THRESHOLD = 0.05    # 0.05% = 5 basis points (very profitable)
ALERT_FR_THRESHOLD = 0.10      # 0.10% = 10 basis points (MUST trade)
MEGA_FR_THRESHOLD = 0.50       # 0.50% = 50 basis points (extremely rare, massive edge)
MIN_VOLUME_24H = 500_000       # $500k minimum 24h volume
MIN_VOLUME_ALERT = 1_000_000   # $1M for high-priority alerts

# Annualized yield calculation
# FR is paid every 8 hours = 3x per day = 1095x per year
FR_PAYMENTS_PER_DAY = 3
FR_PAYMENTS_PER_YEAR = 1095

# Avoid list (from backtest)
AVOID_SYMBOLS = {"SOLUSDT", "XAGUSDT", "SUIUSDT", "ARBUSDT", "MEMEUSDT", "SENTUSDT", "ADAUSDT"}

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def fetch_all_tickers():
    """Fetch all Bitunix futures tickers."""
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/tickers", timeout=15)
        data = r.json().get("data", [])
        return data
    except Exception as e:
        log(f"  Error fetching tickers: {e}")
        return []

def fetch_single_funding_rate(symbol):
    """Fetch funding rate for a single symbol via dedicated endpoint."""
    try:
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/market/funding_rate",
            params={"symbol": symbol},
            timeout=5
        )
        data = r.json().get("data", {})
        return float(data.get("fundingRate", 0) or 0)
    except:
        return 0.0

def fetch_funding_rates_bulk():
    """Fetch funding rates for all symbols with sufficient volume."""
    tickers = fetch_all_tickers()
    # First filter by volume to reduce API calls
    candidates = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        try:
            last_price = float(t.get("last", 0) or 0)
            volume_24h = float(t.get("quoteVol", 0) or 0)
        except (ValueError, TypeError):
            continue
        if last_price > 0 and volume_24h >= MIN_VOLUME_24H:
            candidates.append({
                "symbol": symbol,
                "price": last_price,
                "volume_24h": volume_24h,
            })
    
    log(f"  Fetching FR for {len(candidates)} liquid symbols...")
    results = []
    
    for c in candidates:
        symbol = c["symbol"]
        fr = fetch_single_funding_rate(symbol)
        
        results.append({
            "symbol": symbol,
            "price": c["price"],
            "volume_24h": c["volume_24h"],
            "change_24h": 0,
            "funding_rate": fr,
            "fr_pct": fr * 100,
            "daily_yield_pct": abs(fr) * FR_PAYMENTS_PER_DAY * 100,
            "annual_yield_pct": abs(fr) * FR_PAYMENTS_PER_YEAR * 100,
        })
        
        # Rate limit: small delay between calls
        time.sleep(0.1)
    
    return results

def classify_opportunity(fr_pct, volume_24h):
    """Classify the FR opportunity tier."""
    abs_fr = abs(fr_pct)
    
    if abs_fr >= MEGA_FR_THRESHOLD * 100:
        return "🔥 MEGA", "IMMEDIATE — Extremely rare, massive edge"
    elif abs_fr >= ALERT_FR_THRESHOLD * 100:
        return "🟢 HIGH", "Strong entry — high probability of mean reversion"
    elif abs_fr >= EXTREME_FR_THRESHOLD * 100:
        return "🟡 MODERATE", "Good entry — monitor for continuation"
    else:
        return "⚪ LOW", "Below threshold"

def calculate_position_metrics(fr_pct, balance=10.0, leverage=2):
    """Calculate expected returns for a given FR opportunity."""
    abs_fr = abs(fr_pct) / 100  # Convert back to decimal
    
    position_size = balance * leverage
    daily_fr_income = position_size * abs_fr * FR_PAYMENTS_PER_DAY
    weekly_fr_income = daily_fr_income * 7
    
    # Expected hold time for FR to mean-revert: 1-3 days
    expected_income_3d = daily_fr_income * 3
    
    return {
        "position_size": position_size,
        "daily_fr_income": daily_fr_income,
        "weekly_fr_income": weekly_fr_income,
        "expected_3d_income": expected_income_3d,
        "annual_yield_pct": abs_fr * FR_PAYMENTS_PER_YEAR * 100,
    }

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"alerted_symbols": {}, "last_run": None, "total_alerts": 0}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def save_history(opportunities):
    """Append current scan to history for trend analysis."""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        except:
            history = []
    
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "top_opportunities": [{
            "symbol": o["symbol"],
            "fr_pct": o["fr_pct"],
            "volume_24h": o["volume_24h"],
        } for o in opportunities[:10]]
    }
    history.append(entry)
    
    # Keep last 7 days (7 * 24 * 6 = 1008 entries at 10min intervals)
    history = history[-1008:]
    
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def send_alert(opportunities, state):
    """Send email alert for extreme FR opportunities."""
    if not opportunities:
        return
    
    # Only alert for symbols not alerted in last 4 hours
    new_alerts = []
    now = datetime.now(timezone.utc)
    
    for opp in opportunities:
        symbol = opp["symbol"]
        last_alert = state.get("alerted_symbols", {}).get(symbol, "")
        if last_alert:
            try:
                last_dt = datetime.fromisoformat(last_alert.replace("Z", "+00:00"))
                if (now - last_dt).total_seconds() < 14400:  # 4 hours
                    continue
            except:
                pass
        new_alerts.append(opp)
    
    if not new_alerts:
        log("  No new alerts (all recently alerted)")
        return
    
    # Build email
    rows = ""
    for opp in new_alerts[:8]:
        tier, desc = classify_opportunity(opp["fr_pct"], opp["volume_24h"])
        direction = "🟢 LONG" if opp["fr_pct"] < 0 else "🔴 SHORT"
        metrics = calculate_position_metrics(opp["fr_pct"])
        avoid_flag = " ⚠️AVOID" if opp["symbol"] in AVOID_SYMBOLS else ""
        
        rows += f"""
        <tr style="border-bottom:1px solid #222">
            <td style="padding:8px;color:#22d3ee;font-weight:bold">{opp['symbol']}{avoid_flag}</td>
            <td style="padding:8px;color:{'#ff6b6b' if opp['fr_pct'] > 0 else '#00ff88'};font-weight:bold">{opp['fr_pct']:+.4f}%</td>
            <td style="padding:8px;color:#ffd700">{direction}</td>
            <td style="padding:8px;color:#e0e0e0">{tier}</td>
            <td style="padding:8px;color:#00ff88">${metrics['daily_fr_income']:.4f}/day</td>
            <td style="padding:8px;color:#888">${opp['volume_24h']/1e6:.1f}M</td>
        </tr>"""
    
    top = new_alerts[0]
    top_metrics = calculate_position_metrics(top["fr_pct"])
    
    subject = f"⚡ FR ARB: {top['symbol']} {top['fr_pct']:+.4f}% | {'LONG' if top['fr_pct'] < 0 else 'SHORT'} | ${top_metrics['daily_fr_income']:.3f}/day"
    
    html = f"""
    <div style="font-family:'Courier New',monospace;background:#0a0a1a;color:#e0e0e0;padding:24px;border-radius:12px;max-width:700px">
        <h2 style="color:#a855f7;margin:0 0 4px">⚡ NEXYROTH Funding Rate Arbitrage</h2>
        <p style="color:#22d3ee;font-size:12px;margin:0 0 16px">Extreme FR detected — passive income opportunity</p>
        
        <div style="background:#0f1a0f;padding:12px;border-radius:8px;border:1px solid #00ff88;margin-bottom:16px">
            <p style="color:#00ff88;margin:0;font-size:13px">
                <strong>Strategy:</strong> When FR is negative → go LONG (shorts pay you every 8h)<br>
                When FR is positive → go SHORT (longs pay you every 8h)<br>
                <strong>Risk:</strong> Very low — you earn FR payments regardless of price direction
            </p>
        </div>
        
        <table style="width:100%;border-collapse:collapse;font-size:12px">
            <tr style="background:#111;border-bottom:2px solid #333">
                <th style="padding:8px;color:#888;text-align:left">Symbol</th>
                <th style="padding:8px;color:#888;text-align:left">FR</th>
                <th style="padding:8px;color:#888;text-align:left">Direction</th>
                <th style="padding:8px;color:#888;text-align:left">Tier</th>
                <th style="padding:8px;color:#888;text-align:left">Daily Yield</th>
                <th style="padding:8px;color:#888;text-align:left">Volume</th>
            </tr>
            {rows}
        </table>
        
        <div style="background:#111;padding:12px;border-radius:8px;margin-top:16px;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px;font-size:12px">💰 Top Pick: {top['symbol']}</h3>
            <table style="font-size:11px">
                <tr><td style="color:#888;padding:2px 8px">Direction</td><td style="color:#22d3ee">{'LONG (shorts pay you)' if top['fr_pct'] < 0 else 'SHORT (longs pay you)'}</td></tr>
                <tr><td style="color:#888;padding:2px 8px">FR per 8h</td><td style="color:#ffd700">{top['fr_pct']:+.4f}%</td></tr>
                <tr><td style="color:#888;padding:2px 8px">Daily income ($10, 2x)</td><td style="color:#00ff88">${top_metrics['daily_fr_income']:.4f}</td></tr>
                <tr><td style="color:#888;padding:2px 8px">Weekly income</td><td style="color:#00ff88">${top_metrics['weekly_fr_income']:.4f}</td></tr>
                <tr><td style="color:#888;padding:2px 8px">Annualized yield</td><td style="color:#00ff88">{top_metrics['annual_yield_pct']:.1f}%</td></tr>
                <tr><td style="color:#888;padding:2px 8px">Entry</td><td style="color:#e0e0e0">Market order + 2% SL</td></tr>
                <tr><td style="color:#888;padding:2px 8px">Exit</td><td style="color:#e0e0e0">When FR normalizes (< 0.02%)</td></tr>
            </table>
        </div>
        
        <p style="color:#555;font-size:10px;margin-top:12px">Use LIMIT orders (0.02% maker fee). Max 2x leverage. SL at 2%. Expected hold: 1-3 days.</p>
        <p style="color:#444;font-size:9px;margin-top:8px">NEXYROTH FR Arb Maximizer • Scans every 10 min • {datetime.now(timezone.utc).strftime("%H:%M UTC")}</p>
    </div>
    """
    
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=15
        )
        if resp.status_code == 200:
            log(f"  📧 FR alert sent: {subject}")
            # Update alerted state
            for opp in new_alerts[:8]:
                state.setdefault("alerted_symbols", {})[opp["symbol"]] = now.isoformat()
            state["total_alerts"] = state.get("total_alerts", 0) + 1
        else:
            log(f"  ⚠️ Email failed: {resp.status_code}")
    except Exception as e:
        log(f"  ⚠️ Email error: {e}")

def main():
    log("=" * 60)
    log("NEXYROTH Funding Rate Arb Maximizer — Scanning")
    log("=" * 60)
    
    state = load_state()
    
    # Fetch all tickers with funding rates
    all_data = fetch_funding_rates_bulk()
    log(f"  Scanned {len(all_data)} symbols with sufficient volume")
    
    if not all_data:
        log("  No data available")
        return
    
    # Sort by absolute FR (most extreme first)
    all_data.sort(key=lambda x: abs(x["fr_pct"]), reverse=True)
    
    # Filter for extreme FR only
    extreme = [d for d in all_data if abs(d["fr_pct"]) >= EXTREME_FR_THRESHOLD * 100]
    high_priority = [d for d in all_data if abs(d["fr_pct"]) >= ALERT_FR_THRESHOLD * 100]
    mega = [d for d in all_data if abs(d["fr_pct"]) >= MEGA_FR_THRESHOLD * 100]
    
    log(f"  Extreme FR (>{EXTREME_FR_THRESHOLD*100}%): {len(extreme)} symbols")
    log(f"  High Priority (>{ALERT_FR_THRESHOLD*100}%): {len(high_priority)} symbols")
    log(f"  MEGA (>{MEGA_FR_THRESHOLD*100}%): {len(mega)} symbols")
    
    # Log top 5
    for opp in all_data[:5]:
        direction = "LONG" if opp["fr_pct"] < 0 else "SHORT"
        avoid = " [AVOID]" if opp["symbol"] in AVOID_SYMBOLS else ""
        log(f"    {opp['symbol']:<14} FR={opp['fr_pct']:+.4f}% → {direction} | Daily: ${opp['daily_yield_pct']:.3f}% | Vol: ${opp['volume_24h']/1e6:.1f}M{avoid}")
    
    # Save history
    save_history(all_data)
    
    # Send alert if high priority opportunities exist (excluding avoid list)
    tradeable = [d for d in high_priority if d["symbol"] not in AVOID_SYMBOLS]
    if tradeable:
        send_alert(tradeable, state)
    elif extreme:
        # Still log but don't alert for moderate opportunities
        tradeable_extreme = [d for d in extreme if d["symbol"] not in AVOID_SYMBOLS]
        if tradeable_extreme and len(tradeable_extreme) >= 3:
            send_alert(tradeable_extreme[:3], state)
    
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    
    log("=" * 60)

if __name__ == "__main__":
    main()
