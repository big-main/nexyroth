#!/usr/bin/env python3
"""
NEXYROTH Watchlist Scanner v2.0
- Always scans your priority watchlist symbols (from watchlist.json)
- Also scans top dynamic movers from Bitunix
- Combines both into a ranked output with funding rates, momentum, and setup labels
- Sends email alert if any symbol hits a trigger condition
"""
import requests, json, os, time
from datetime import datetime, timezone

BITUNIX_API  = "https://fapi.bitunix.com"
WATCHLIST    = "/home/ubuntu/trading_sniper/watchlist.json"
LOG_FILE     = "/home/ubuntu/trading_sniper/watchlist_scanner.log"
RESEND_KEY   = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL  = os.getenv("ALERT_EMAIL_TO", "")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_watchlist():
    try:
        with open(WATCHLIST) as f:
            data = json.load(f)
        priority = data.get("priority_watchlist", [])
        added    = data.get("added_high_value", [])
        settings = data.get("scan_settings", {})
        return priority, added, settings
    except Exception as e:
        log(f"Failed to load watchlist: {e}")
        return [], [], {}

def get_all_tickers():
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/tickers", timeout=12)
        return {t["symbol"]: t for t in r.json().get("data", [])}
    except Exception as e:
        log(f"Ticker fetch error: {e}")
        return {}

def get_funding_rate(symbol):
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/funding_rate",
                         params={"symbol": symbol}, timeout=5)
        return float(r.json().get("data", {}).get("fundingRate", 0)) * 100
    except:
        return 0.0

def pct_change(ticker):
    try:
        l, o = float(ticker.get("lastPrice", 0)), float(ticker.get("open", 0))
        return ((l - o) / o) * 100 if o else 0
    except:
        return 0.0

def classify_setup(pct, fr, vol):
    """Return setup label, signal direction, and priority score."""
    score = 0
    signal = "NEUTRAL"
    label  = "WATCH"

    # Funding rate extremes
    if fr <= -50:
        label = "🔥 EXTREME SQUEEZE"
        signal = "LONG"
        score += 100
    elif fr <= -20:
        label = "⚡ FUNDING ARB (SHORT SQUEEZE)"
        signal = "LONG"
        score += 60
    elif fr >= 50:
        label = "🩸 EXTREME LONGS PAYING"
        signal = "SHORT"
        score += 80
    elif fr >= 20:
        label = "📉 SHORT OPPORTUNITY"
        signal = "SHORT"
        score += 40

    # Momentum
    if pct >= 10:
        label = label if score > 30 else "🚀 STRONG MOMENTUM"
        signal = signal if signal != "NEUTRAL" else "LONG"
        score += 30
    elif pct <= -10:
        label = label if score > 30 else "💀 STRONG DUMP"
        signal = signal if signal != "NEUTRAL" else "SHORT"
        score += 20
    elif abs(pct) >= 5:
        score += 10

    # Volume bonus
    if vol >= 50:
        score += 15
    elif vol >= 10:
        score += 5

    return label, signal, score

def scan():
    priority, added, settings = load_watchlist()
    all_watchlist = list(dict.fromkeys(priority + added))  # deduplicate, preserve order
    min_vol = settings.get("min_vol_millions", 0.5)
    top_dynamic = settings.get("top_dynamic_movers", 10)
    fr_alert_threshold = settings.get("funding_rate_alert_threshold_pct", 15)
    momentum_threshold = settings.get("momentum_alert_threshold_pct", 5)

    log(f"Scanning {len(all_watchlist)} watchlist symbols + top {top_dynamic} dynamic movers...")

    tickers = get_all_tickers()
    if not tickers:
        log("No ticker data — aborting scan.")
        return []

    # Get top dynamic movers (by abs % change, min vol)
    dynamic_movers = sorted(
        [t for t in tickers.values() if float(t.get("quoteVol", 0)) / 1e6 >= min_vol],
        key=lambda t: abs(pct_change(t)),
        reverse=True,
    )[:top_dynamic]
    dynamic_symbols = [t["symbol"] for t in dynamic_movers]

    # Combine: priority watchlist + added + dynamic movers
    scan_symbols = list(dict.fromkeys(all_watchlist + dynamic_symbols))

    results = []
    for sym in scan_symbols:
        ticker = tickers.get(sym)
        if not ticker:
            continue
        vol = float(ticker.get("quoteVol", 0)) / 1e6
        price = float(ticker.get("lastPrice", 0))
        pct   = pct_change(ticker)
        fr    = get_funding_rate(sym)
        label, signal, score = classify_setup(pct, fr, vol)
        is_priority = sym in priority
        is_dynamic  = sym in dynamic_symbols

        results.append({
            "symbol":      sym,
            "price":       price,
            "pct":         pct,
            "fr":          fr,
            "vol":         vol,
            "label":       label,
            "signal":      signal,
            "score":       score,
            "is_priority": is_priority,
            "is_dynamic":  is_dynamic,
        })
        time.sleep(0.05)  # rate limit

    # Sort: by score desc, then priority first
    results.sort(key=lambda x: (-x["score"], -x["is_priority"], -abs(x["pct"])))
    return results

def print_results(results):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*95}")
    print(f"  NEXYROTH WATCHLIST SCANNER v2.0 — {now}")
    print(f"{'='*95}")
    print(f"{'#':>3} {'Symbol':<16} {'Price':>12} {'24h%':>8} {'FR%':>10} {'Vol(M)':>8} {'Sig':>7}  Setup")
    print(f"{'-'*95}")
    for i, r in enumerate(results[:30], 1):
        tag = ""
        if r["is_priority"]: tag += "★"
        if r["is_dynamic"]:  tag += "↑"
        print(f"{i:>3} {r['symbol']:<14}{tag:<2} {r['price']:>12.6g} {r['pct']:>+7.2f}% "
              f"{r['fr']:>+9.4f}% {r['vol']:>8.1f}M {r['signal']:>7}  {r['label']}")
    print(f"{'='*95}")
    print(f"  ★ = priority watchlist  ↑ = top dynamic mover")
    print(f"{'='*95}\n")

def check_alerts(results, fr_threshold, momentum_threshold):
    """Return results that hit alert conditions."""
    alerts = []
    for r in results:
        if abs(r["fr"]) >= fr_threshold:
            alerts.append(r)
        elif abs(r["pct"]) >= momentum_threshold and r["vol"] >= 5:
            alerts.append(r)
    return alerts

def send_alert_email(alerts, all_results):
    if not alerts:
        return
    rows = ""
    for r in alerts[:10]:
        sig_color = "#00ff88" if r["signal"] == "LONG" else ("#ff4444" if r["signal"] == "SHORT" else "#aaa")
        rows += f"""<tr>
          <td style="padding:8px;border:1px solid #333;font-weight:bold;color:#f7931a">{r['symbol']}</td>
          <td style="padding:8px;border:1px solid #333">${r['price']:.6g}</td>
          <td style="padding:8px;border:1px solid #333;text-align:right;color:{'#00ff88' if r['pct']>=0 else '#ff4444'}">{r['pct']:+.2f}%</td>
          <td style="padding:8px;border:1px solid #333;text-align:right;color:{'#00ff88' if r['fr']<=0 else '#ff4444'}">{r['fr']:+.4f}%</td>
          <td style="padding:8px;border:1px solid #333;text-align:right">{r['vol']:.1f}M</td>
          <td style="padding:8px;border:1px solid #333;color:{sig_color};font-weight:bold">{r['signal']}</td>
          <td style="padding:8px;border:1px solid #333;font-size:12px">{r['label']}</td>
        </tr>"""

    subject = f"⚡ NEXYROTH Alert — {len(alerts)} signal(s): {', '.join(r['symbol'] for r in alerts[:3])}"
    html = f"""
<div style="background:#0a0a0a;color:#e0e0e0;font-family:Arial,sans-serif;padding:24px;max-width:860px">
  <div style="background:#111;border:2px solid #f7931a;border-radius:8px;padding:20px;margin-bottom:16px">
    <h1 style="color:#f7931a;margin:0 0 4px 0">⚡ NEXYROTH WATCHLIST ALERT</h1>
    <p style="color:#aaa;margin:0;font-size:13px">{datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')} — {len(alerts)} signal(s) triggered</p>
  </div>
  <div style="background:#111;border:1px solid #333;border-radius:8px;padding:16px">
    <h2 style="color:#00ff88;margin:0 0 12px 0;font-size:16px">🎯 Triggered Signals</h2>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#1a1a1a;color:#888;font-size:11px;text-transform:uppercase">
        <th style="padding:8px;border:1px solid #333;text-align:left">Symbol</th>
        <th style="padding:8px;border:1px solid #333">Price</th>
        <th style="padding:8px;border:1px solid #333">24h%</th>
        <th style="padding:8px;border:1px solid #333">FR%</th>
        <th style="padding:8px;border:1px solid #333">Vol</th>
        <th style="padding:8px;border:1px solid #333">Signal</th>
        <th style="padding:8px;border:1px solid #333;text-align:left">Setup</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            log(f"✅ Alert email sent: {resp.json().get('id','?')}")
        else:
            log(f"❌ Email failed {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log(f"❌ Email error: {e}")

def main():
    priority, added, settings = load_watchlist()
    fr_threshold  = settings.get("funding_rate_alert_threshold_pct", 15)
    mom_threshold = settings.get("momentum_alert_threshold_pct", 5)

    results = scan()
    if not results:
        log("No results from scan.")
        return

    print_results(results)

    # Save results JSON
    out = {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "total_scanned": len(results),
        "results": results[:30],
    }
    with open("/home/ubuntu/trading_sniper/watchlist_scan_latest.json", "w") as f:
        json.dump(out, f, indent=2)

    # Check and send alerts
    alerts = check_alerts(results, fr_threshold, mom_threshold)
    if alerts:
        log(f"🚨 {len(alerts)} alert(s) triggered — sending email...")
        send_alert_email(alerts, results)
    else:
        log(f"No alerts triggered. Scan complete ({len(results)} symbols).")

if __name__ == "__main__":
    main()
