#!/usr/bin/env python3
"""
Kalshi BTC Daily Digest v1.0
Runs at 11:45 PM EDT (03:45 UTC) every day.
Reads today's kalshi_btc_YYYY-MM-DD.json snapshot log,
uses Claude AI to generate insights, and sends a rich HTML email digest.

Covers:
- BTC/ETH/SOL price summary (open, high, low, close, % change)
- Kalshi market activity timeline (when markets opened/closed, volume spikes)
- YES/NO price trends across the day
- Implied probability analysis (what the crowd was pricing in)
- Actionable trade ideas for tomorrow (LONG/SHORT signals)
- Account balance tracking
"""
import json, os, requests
from datetime import datetime, timezone
from anthropic import Anthropic

# ── Config ────────────────────────────────────────────────────────────────────
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL    = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")
DATA_DIR       = "/home/ubuntu/trading_sniper/data"
LOG_FILE       = "/home/ubuntu/trading_sniper/kalshi_digest.log"
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── Load today's data ─────────────────────────────────────────────────────────
def load_today_data():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data_file = os.path.join(DATA_DIR, f"kalshi_btc_{today}.json")
    if not os.path.exists(data_file):
        log(f"No data file for {today} — nothing to summarize.")
        return None, today
    with open(data_file) as f:
        return json.load(f), today

# ── Build analytics from snapshots ───────────────────────────────────────────
def analyze(day_log):
    snaps = day_log.get("snapshots", [])
    if not snaps:
        return None

    btc_prices = [s["btc"]["price"] for s in snaps if s["btc"]["price"] > 0]
    eth_prices = [s["eth"]["price"] for s in snaps if s["eth"]["price"] > 0]
    sol_prices = [s["sol"]["price"] for s in snaps if s["sol"]["price"] > 0]

    # Price OHLC
    def ohlc(prices):
        if not prices:
            return {"open": 0, "high": 0, "low": 0, "close": 0, "change_pct": 0}
        return {
            "open":       prices[0],
            "high":       max(prices),
            "low":        min(prices),
            "close":      prices[-1],
            "change_pct": round((prices[-1] - prices[0]) / prices[0] * 100, 2) if prices[0] else 0,
        }

    # Market activity timeline
    market_timeline = []
    seen_tickers = set()
    for s in snaps:
        ts = s.get("ts_local", s.get("ts", "?"))
        for m in s.get("markets", []):
            ticker = m.get("ticker", "")
            if ticker not in seen_tickers and m.get("liquid"):
                seen_tickers.add(ticker)
                market_timeline.append({
                    "first_seen": ts,
                    "ticker":     ticker,
                    "title":      m.get("title", ""),
                    "yes_ask":    m.get("yes_ask", 0),
                    "no_ask":     m.get("no_ask", 0),
                    "volume":     m.get("volume", 0),
                    "close_time": m.get("close_time", ""),
                })

    # Volume peak
    all_vols = []
    for s in snaps:
        for m in s.get("markets", []):
            all_vols.append((s.get("ts_local", ""), m.get("ticker", ""), m.get("volume", 0)))
    all_vols.sort(key=lambda x: -x[2])
    top_volume = all_vols[:5]

    # YES/NO price history per market
    price_history = {}
    for s in snaps:
        ts = s.get("ts_local", "")
        for m in s.get("markets", []):
            t = m.get("ticker", "")
            if t not in price_history:
                price_history[t] = []
            price_history[t].append({
                "ts":      ts,
                "yes_ask": m.get("yes_ask", 0),
                "no_ask":  m.get("no_ask", 0),
                "volume":  m.get("volume", 0),
            })

    # Implied probability trend (YES ask = market's probability of YES)
    prob_trends = {}
    for ticker, history in price_history.items():
        if len(history) >= 2:
            first_ya = history[0]["yes_ask"]
            last_ya  = history[-1]["yes_ask"]
            if first_ya > 0 and last_ya > 0:
                prob_trends[ticker] = {
                    "title":      next((m.get("title","") for s in snaps for m in s.get("markets",[]) if m.get("ticker")==ticker), ""),
                    "open_prob":  first_ya,
                    "close_prob": last_ya,
                    "drift":      last_ya - first_ya,
                    "direction":  "↑ YES gaining" if last_ya > first_ya else "↓ YES losing",
                }

    # Balance trend
    balances = [(s.get("ts_local",""), s.get("balance_cents", 0)) for s in snaps]

    return {
        "date":           day_log.get("date", "?"),
        "total_snapshots": len(snaps),
        "btc_ohlc":       ohlc(btc_prices),
        "eth_ohlc":       ohlc(eth_prices),
        "sol_ohlc":       ohlc(sol_prices),
        "market_timeline": market_timeline,
        "top_volume":     top_volume,
        "price_history":  price_history,
        "prob_trends":    prob_trends,
        "balances":       balances,
        "markets_seen_today": len(seen_tickers),
        "liquid_markets_peak": max((s.get("crypto_markets_liquid", 0) for s in snaps), default=0),
    }

# ── AI Summarization ──────────────────────────────────────────────────────────
def ai_summarize(analytics):
    """Use Claude to generate trading insights from the day's data."""
    if not ANTHROPIC_KEY:
        return generate_fallback_summary(analytics)

    try:
        client = Anthropic(api_key=ANTHROPIC_KEY)
        prompt = f"""You are NEXYROTH, an elite crypto prediction market analyst.
Analyze today's Kalshi BTC market data and produce a concise, actionable trading intelligence report.

DATA:
{json.dumps(analytics, indent=2, default=str)[:6000]}

Write a report with these exact sections (use HTML formatting, no markdown):
1. <b>📊 Day Summary</b> — 2-3 sentences on BTC/ETH price action and overall market sentiment
2. <b>₿ Kalshi BTC Market Activity</b> — What markets were open, peak volume, when they opened/closed
3. <b>🎯 Implied Probability Analysis</b> — What the crowd was pricing in for BTC (YES/NO drift, sentiment shifts)
4. <b>⚡ LONG/SHORT Signals for Tomorrow</b> — 2-3 specific trade ideas with entry rationale (label each LONG or SHORT)
5. <b>🔮 Tomorrow's Outlook</b> — Key levels to watch, expected market open times, risk factors

Keep each section under 5 sentences. Be direct, data-driven, and specific. No filler text."""

        resp = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as e:
        log(f"Claude API error: {e} — using fallback summary")
        return generate_fallback_summary(analytics)

def generate_fallback_summary(a):
    """Rule-based summary when AI is unavailable."""
    btc = a["btc_ohlc"]
    eth = a["eth_ohlc"]
    direction = "bullish" if btc["change_pct"] > 0 else "bearish"
    signal = "LONG" if btc["change_pct"] > 1 else ("SHORT" if btc["change_pct"] < -1 else "NEUTRAL")

    lines = [
        f"<b>📊 Day Summary</b><br>",
        f"BTC closed at ${btc['close']:,.0f} ({btc['change_pct']:+.2f}%), range ${btc['low']:,.0f}–${btc['high']:,.0f}. ",
        f"ETH closed at ${eth['close']:,.0f} ({eth['change_pct']:+.2f}%). ",
        f"Overall sentiment: {direction}.<br><br>",
        f"<b>₿ Kalshi BTC Market Activity</b><br>",
        f"{a['markets_seen_today']} unique crypto markets observed today. ",
        f"Peak liquid markets: {a['liquid_markets_peak']}. ",
        f"Total data snapshots: {a['total_snapshots']} (every 15 min).<br><br>",
        f"<b>🎯 Implied Probability Analysis</b><br>",
    ]
    if a["prob_trends"]:
        for ticker, pt in list(a["prob_trends"].items())[:3]:
            lines.append(f"{pt['title'][:50]}: {pt['open_prob']}¢ → {pt['close_prob']}¢ ({pt['direction']})<br>")
    else:
        lines.append("No liquid markets with probability data today.<br>")
    lines += [
        f"<br><b>⚡ LONG/SHORT Signals for Tomorrow</b><br>",
        f"Signal: <b>{signal}</b> BTC based on today's {btc['change_pct']:+.2f}% close. ",
        f"Watch for Kalshi BTC markets opening — bet YES if BTC momentum continues {direction}.<br><br>",
        f"<b>🔮 Tomorrow's Outlook</b><br>",
        f"Key level: ${btc['close']:,.0f} (today's close). ",
        f"Kalshi crypto markets typically open in morning/afternoon windows. ",
        f"Monitor for new KXBTC/KXETH contracts with YES ask 20–80¢ range for best edge.",
    ]
    return "".join(lines)

# ── Build HTML email ──────────────────────────────────────────────────────────
def build_email(analytics, ai_summary, date):
    btc = analytics["btc_ohlc"]
    eth = analytics["eth_ohlc"]
    sol = analytics["sol_ohlc"]
    bal = analytics["balances"][-1][1] / 100 if analytics["balances"] else 0

    # Price table rows
    def price_row(name, ohlc, color):
        chg_color = "#00ff88" if ohlc["change_pct"] >= 0 else "#ff4444"
        arrow = "▲" if ohlc["change_pct"] >= 0 else "▼"
        return f"""<tr>
          <td style="padding:8px 12px;color:{color};font-weight:bold">{name}</td>
          <td style="padding:8px 12px;text-align:right">${ohlc['open']:,.2f}</td>
          <td style="padding:8px 12px;text-align:right">${ohlc['high']:,.2f}</td>
          <td style="padding:8px 12px;text-align:right">${ohlc['low']:,.2f}</td>
          <td style="padding:8px 12px;text-align:right;font-weight:bold">${ohlc['close']:,.2f}</td>
          <td style="padding:8px 12px;text-align:right;color:{chg_color};font-weight:bold">{arrow} {ohlc['change_pct']:+.2f}%</td>
        </tr>"""

    price_table = price_row("BTC", btc, "#f7931a") + price_row("ETH", eth, "#627eea") + price_row("SOL", sol, "#9945ff")

    # Market timeline
    timeline_rows = ""
    for m in analytics["market_timeline"][:10]:
        ya = m.get("yes_ask", 0)
        na = m.get("no_ask", 0)
        vol = m.get("volume", 0)
        timeline_rows += f"""<tr>
          <td style="padding:6px 10px;font-size:12px;color:#aaa">{m['first_seen'][11:16]}</td>
          <td style="padding:6px 10px;font-size:11px;font-family:monospace">{m['ticker'][:35]}</td>
          <td style="padding:6px 10px;font-size:12px">{m['title'][:45]}</td>
          <td style="padding:6px 10px;text-align:center;color:#00ff88">{ya}¢</td>
          <td style="padding:6px 10px;text-align:center;color:#ff4444">{na}¢</td>
          <td style="padding:6px 10px;text-align:right">{vol:,}</td>
        </tr>"""
    if not timeline_rows:
        timeline_rows = '<tr><td colspan="6" style="padding:12px;text-align:center;color:#666">No liquid crypto markets were open today</td></tr>'

    html = f"""
<div style="background:#0a0a0a;color:#e0e0e0;font-family:Arial,sans-serif;padding:24px;max-width:860px;margin:0 auto">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#111 0%,#1a1a2e 100%);border:2px solid #f7931a;border-radius:12px;padding:24px;margin-bottom:20px">
    <h1 style="color:#f7931a;margin:0 0 6px 0;font-size:26px;letter-spacing:1px">⚡ NEXYROTH DAILY DIGEST</h1>
    <p style="color:#aaa;margin:0;font-size:14px">Kalshi BTC Market Intelligence — {date} | {analytics['total_snapshots']} snapshots collected</p>
    <p style="color:#666;margin:4px 0 0 0;font-size:12px">Account Balance: <span style="color:#00ff88">${bal:.4f}</span></p>
  </div>

  <!-- Price Summary -->
  <div style="background:#111;border:1px solid #222;border-radius:8px;padding:16px;margin-bottom:16px">
    <h2 style="color:#00ff88;margin:0 0 12px 0;font-size:16px">📊 Price Summary (Day OHLC)</h2>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#1a1a1a;color:#888;font-size:11px;text-transform:uppercase">
          <th style="padding:8px 12px;text-align:left">Asset</th>
          <th style="padding:8px 12px;text-align:right">Open</th>
          <th style="padding:8px 12px;text-align:right">High</th>
          <th style="padding:8px 12px;text-align:right">Low</th>
          <th style="padding:8px 12px;text-align:right">Close</th>
          <th style="padding:8px 12px;text-align:right">Change</th>
        </tr>
      </thead>
      <tbody>{price_table}</tbody>
    </table>
  </div>

  <!-- AI Insights -->
  <div style="background:#111;border:1px solid #f7931a;border-radius:8px;padding:20px;margin-bottom:16px">
    <h2 style="color:#f7931a;margin:0 0 14px 0;font-size:16px">🤖 AI Market Intelligence</h2>
    <div style="font-size:14px;line-height:1.7;color:#ddd">{ai_summary}</div>
  </div>

  <!-- Market Timeline -->
  <div style="background:#111;border:1px solid #222;border-radius:8px;padding:16px;margin-bottom:16px">
    <h2 style="color:#00ff88;margin:0 0 12px 0;font-size:16px">⏱ Kalshi Crypto Market Timeline</h2>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#1a1a1a;color:#888;font-size:11px;text-transform:uppercase">
          <th style="padding:6px 10px;text-align:left">Time</th>
          <th style="padding:6px 10px;text-align:left">Ticker</th>
          <th style="padding:6px 10px;text-align:left">Title</th>
          <th style="padding:6px 10px;text-align:center">YES</th>
          <th style="padding:6px 10px;text-align:center">NO</th>
          <th style="padding:6px 10px;text-align:right">Volume</th>
        </tr>
      </thead>
      <tbody>{timeline_rows}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="background:#111;border:1px solid #333;border-radius:8px;padding:14px;text-align:center">
    <p style="margin:0;font-size:12px;color:#666">NEXYROTH Trade Intelligence | Cloud Computer 24/7 Monitor</p>
    <p style="margin:4px 0 0 0;font-size:12px">
      <a href="https://kalshi.com/markets/crypto" style="color:#f7931a">Open Kalshi Crypto Markets</a> &nbsp;|&nbsp;
      <a href="https://kalshi.com/account/deposits" style="color:#00ff88">Fund Account</a>
    </p>
  </div>
</div>"""
    return html

# ── Send email ────────────────────────────────────────────────────────────────
def send_digest(html, date, analytics):
    btc_close = analytics["btc_ohlc"]["close"]
    btc_chg   = analytics["btc_ohlc"]["change_pct"]
    arrow = "▲" if btc_chg >= 0 else "▼"
    subject = f"⚡ NEXYROTH Daily Digest {date} | BTC ${btc_close:,.0f} {arrow}{btc_chg:+.2f}% | Kalshi Markets: {analytics['markets_seen_today']}"

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            log(f"✅ Daily digest sent to {ALERT_EMAIL} | id={resp.json().get('id','?')}")
            return True
        else:
            log(f"❌ Email failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log(f"❌ Email exception: {e}")
    return False

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    log("=== Kalshi BTC Daily Digest starting ===")

    day_log, today = load_today_data()
    if not day_log:
        log("No data to summarize. Exiting.")
        return

    analytics = analyze(day_log)
    if not analytics:
        log("No snapshots in today's log. Exiting.")
        return

    log(f"Analyzed {analytics['total_snapshots']} snapshots | "
        f"BTC {analytics['btc_ohlc']['change_pct']:+.2f}% | "
        f"Markets seen: {analytics['markets_seen_today']}")

    log("Generating AI summary...")
    ai_summary = ai_summarize(analytics)

    log("Building email...")
    html = build_email(analytics, ai_summary, today)

    log("Sending digest email...")
    send_digest(html, today, analytics)

    # Save digest to file
    digest_file = f"/home/ubuntu/trading_sniper/data/digest_{today}.html"
    with open(digest_file, "w") as f:
        f.write(html)
    log(f"Digest saved to {digest_file}")
    log("=== Daily Digest complete ===")

if __name__ == "__main__":
    run()
