#!/usr/bin/env python3
"""
NEXYROTH Bitunix Daily Digest v1.0
Runs at 11:50 PM EDT (03:50 UTC) every day.

Reads today's bitunix_YYYY-MM-DD.json snapshot log,
uses Claude AI to generate insights, and sends a rich HTML email to big.main@protonmail.com.

Covers:
- BTC/ETH/SOL OHLC for the day
- BEST ENTRY signals seen throughout the day (neg FR + near low)
- Funding rate extremes (squeeze opportunities)
- Top LONG/SHORT setups with entry rationale
- Tomorrow's watchlist priorities
"""
import json, os, requests
from datetime import datetime, timezone
from anthropic import Anthropic

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL    = os.getenv("ALERT_EMAIL_TO", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
DATA_DIR       = "/home/ubuntu/trading_sniper/data"
LOG_FILE       = "/home/ubuntu/trading_sniper/bitunix_digest.log"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_today():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path  = os.path.join(DATA_DIR, f"bitunix_{today}.json")
    if not os.path.exists(path):
        log(f"No data file for {today}")
        return None, today
    with open(path) as f:
        return json.load(f), today

def analyze(day_log):
    snaps = day_log.get("snapshots", [])
    if not snaps:
        return None

    # Build per-symbol history across all snapshots
    sym_history = {}
    for snap in snaps:
        ts = snap.get("ts_local", snap.get("ts", ""))
        for s in snap.get("symbols", []):
            sym = s["symbol"]
            if sym not in sym_history:
                sym_history[sym] = []
            sym_history[sym].append({
                "ts":     ts,
                "price":  s["price"],
                "pct":    s["pct"],
                "fr":     s["fr"],
                "vol_m":  s["vol_m"],
                "dist_low": s["dist_low"],
                "signal": s["signal"],
                "setup":  s["setup"],
            })

    # OHLC per symbol
    def ohlc(history):
        prices = [h["price"] for h in history if h["price"] > 0]
        if not prices:
            return {}
        return {
            "open":       prices[0],
            "high":       max(prices),
            "low":        min(prices),
            "close":      prices[-1],
            "change_pct": round((prices[-1] - prices[0]) / prices[0] * 100, 2) if prices[0] else 0,
        }

    # Collect all BEST ENTRY signals seen today
    best_entries_seen = []
    funding_squeezes  = []
    all_signals       = []

    for sym, history in sym_history.items():
        for h in history:
            if "BEST ENTRY" in h["setup"]:
                best_entries_seen.append({"symbol": sym, **h})
            if "SQUEEZE" in h["setup"]:
                funding_squeezes.append({"symbol": sym, **h})
            if h["signal"] in ("LONG", "SHORT"):
                all_signals.append({"symbol": sym, **h})

    # Deduplicate best entries (keep first occurrence per symbol)
    # Filter out avoid-tier symbols and sort by EV tier (T1 > T2 > T3 > T4)
    EV_TIER_ORDER = {
        "TIER_1_STRONG": 0, "TIER_2_SOLID": 1, "TIER_3_MARGINAL": 2,
        "TIER_4_NEUTRAL": 3, "TIER_5_AVOID": 99,
    }
    seen = set()
    unique_best = []
    for e in best_entries_seen:
        if e["symbol"] not in seen and e.get("signal") != "AVOID":
            seen.add(e["symbol"])
            unique_best.append(e)
    unique_best.sort(key=lambda x: EV_TIER_ORDER.get(x.get("ev_tier", "TIER_4_NEUTRAL"), 3))

    # FR extremes (most negative = best long squeeze)
    fr_extremes = sorted(
        [{"symbol": sym, "fr": history[-1]["fr"], "price": history[-1]["price"],
          "pct": history[-1]["pct"], "signal": history[-1]["signal"]}
         for sym, history in sym_history.items() if history],
        key=lambda x: x["fr"]
    )

    # End-of-day snapshot (last snapshot)
    last_snap = snaps[-1].get("symbols", [])
    eod = {s["symbol"]: s for s in last_snap}

    # FR extremes: exclude avoid symbols from LONG recommendations
    AVOID_SYMS = {"SOLUSDT","XAGUSDT","SUIUSDT","ARBUSDT","MEMEUSDT","SENTUSDT","ADAUSDT"}
    fr_extremes_clean = [e for e in fr_extremes if e["symbol"] not in AVOID_SYMS]

    return {
        "date":              day_log.get("date", "?"),
        "total_snapshots":   len(snaps),
        "symbols_tracked":   len(sym_history),
        "btc_ohlc":          ohlc(sym_history.get("BTCUSDT", [])),
        "eth_ohlc":          ohlc(sym_history.get("ETHUSDT", [])),
        "sol_ohlc":          ohlc(sym_history.get("SOLUSDT", [])),
        "best_entries_seen": unique_best[:10],
        "funding_squeezes":  funding_squeezes[:5],
        "fr_extremes_top5":  fr_extremes_clean[:5],
        "fr_extremes_bot5":  fr_extremes_clean[-5:],
        "all_signals_count": len(all_signals),
        "eod_snapshot":      {k: v for k, v in eod.items()
                              if k in ["BTCUSDT","ETHUSDT","JUPUSDT","AAVEUSDT","AVAXUSDT","WIFUSDT","LTCUSDT","NEARUSDT"]},
    }

def ai_summarize(analytics):
    try:
        client = Anthropic(api_key=ANTHROPIC_KEY)
        prompt = f"""You are NEXYROTH, an elite crypto futures trading analyst for a small account trader ($8-20 balance).
Analyze today's Bitunix market data and write a concise, actionable trading intelligence report.

DATA:
{json.dumps(analytics, indent=2, default=str)[:5000]}

Write a report with these exact sections (use HTML, no markdown):
1. <b>📊 Market Summary</b> — 2-3 sentences on BTC/ETH/SOL price action and overall market direction today
2. <b>✅ BEST ENTRY Signals (Today)</b> — List each BEST ENTRY signal seen: symbol, time first seen, why it qualifies (neg FR + near low), and whether it played out
3. <b>🔥 Funding Rate Opportunities</b> — Top 3 symbols with most negative funding rates right now (shorts paying longs). Label each LONG or SHORT.
4. <b>⚡ Tomorrow's Top LONG Setups</b> — 2-3 specific LONG trade ideas with entry price, stop loss, target, and 1-sentence rationale. Use maker limit orders.
5. <b>📉 Tomorrow's Top SHORT Setups</b> — 1-2 SHORT trade ideas with entry, stop, target.
6. <b>🎯 Small Account Play ($8-20)</b> — Single best trade for tomorrow for a small account that cannot afford to lose. Be very specific: symbol, entry, stop, target, leverage (max 2x).

Keep each section tight. Be direct and data-driven. Always label signals as LONG or SHORT explicitly."""

        resp = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1400,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as e:
        log(f"Claude error: {e} — trying OpenRouter fallback")
        return ai_summarize_openrouter(analytics, prompt)

def ai_summarize_openrouter(analytics, prompt):
    free_models = [
        "google/gemma-4-31b-it:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-20b:free",
        "google/gemma-4-26b-a4b-it:free",
    ]
    for model in free_models:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 1200},
                timeout=30,
            )
            if resp.status_code == 200:
                log(f"AI summary via {model}")
                return resp.json()["choices"][0]["message"]["content"]
            log(f"OpenRouter {model} error {resp.status_code}: {resp.text[:120]}")
        except Exception as e:
            log(f"OpenRouter {model} error: {e}")
    log("All AI models failed — using rule-based fallback")
    return fallback_summary(analytics)

def fallback_summary(a):
    btc = a.get("btc_ohlc", {})
    eth = a.get("eth_ohlc", {})
    be  = a.get("best_entries_seen", [])
    fr5 = a.get("fr_extremes_top5", [])

    direction = "bullish" if btc.get("change_pct", 0) > 0 else "bearish"
    signal    = "LONG" if btc.get("change_pct", 0) > 1 else ("SHORT" if btc.get("change_pct", 0) < -1 else "NEUTRAL")

    be_html = ""
    for e in be[:5]:
        be_html += f"<b>{e['symbol']}</b> at {e['ts'][11:16]} — FR: {e['fr']:+.4f}%, {e['dist_low']:.1f}% above daily low<br>"
    if not be_html:
        be_html = "No BEST ENTRY signals today (no symbols had both negative FR and price near daily low simultaneously).<br>"

    fr_html = ""
    for e in fr5[:3]:
        fr_html += f"<b>{e['symbol']}</b> FR: {e['fr']:+.4f}% — <b>LONG</b> (shorts paying longs)<br>"

    return f"""<b>📊 Market Summary</b><br>
BTC closed at ${btc.get('close',0):,.0f} ({btc.get('change_pct',0):+.2f}%), range ${btc.get('low',0):,.0f}–${btc.get('high',0):,.0f}.
ETH closed at ${eth.get('close',0):,.0f} ({eth.get('change_pct',0):+.2f}%). Overall sentiment: {direction}.<br><br>

<b>✅ BEST ENTRY Signals (Today)</b><br>
{be_html}<br>

<b>🔥 Funding Rate Opportunities</b><br>
{fr_html}<br>

<b>⚡ Tomorrow's Top LONG Setups</b><br>
<b>LONG BTC</b> — Entry: ${btc.get('close',0):,.0f}, Stop: -2%, Target: +3%, 2x leverage. Negative FR pays you to hold.<br><br>

<b>📉 Tomorrow's Top SHORT Setups</b><br>
Monitor for any symbol with FR > +20% — that is the short signal.<br><br>

<b>🎯 Small Account Play ($8-20)</b><br>
<b>LONG BTCUSDT</b> — Entry: ${btc.get('close',0):,.0f} (limit order), Stop: -2%, Target: +3%, Leverage: 2x.
Negative funding rate means you get paid while you wait. Most liquid, tightest spread, lowest risk of liquidation."""

def build_html(analytics, ai_summary, date):
    btc = analytics.get("btc_ohlc", {})
    eth = analytics.get("eth_ohlc", {})
    sol = analytics.get("sol_ohlc", {})
    be  = analytics.get("best_entries_seen", [])
    fr5 = analytics.get("fr_extremes_top5", [])
    eod = analytics.get("eod_snapshot", {})

    def price_row(name, ohlc, color):
        if not ohlc:
            return ""
        chg_color = "#00ff88" if ohlc.get("change_pct", 0) >= 0 else "#ff4444"
        arrow = "▲" if ohlc.get("change_pct", 0) >= 0 else "▼"
        return f"""<tr>
          <td style="padding:8px 12px;color:{color};font-weight:bold">{name}</td>
          <td style="padding:8px 12px;text-align:right">${ohlc.get('open',0):,.2f}</td>
          <td style="padding:8px 12px;text-align:right">${ohlc.get('high',0):,.2f}</td>
          <td style="padding:8px 12px;text-align:right">${ohlc.get('low',0):,.2f}</td>
          <td style="padding:8px 12px;text-align:right;font-weight:bold">${ohlc.get('close',0):,.2f}</td>
          <td style="padding:8px 12px;text-align:right;color:{chg_color};font-weight:bold">{arrow} {ohlc.get('change_pct',0):+.2f}%</td>
        </tr>"""

    price_rows = price_row("BTC", btc, "#f7931a") + price_row("ETH", eth, "#627eea") + price_row("SOL", sol, "#9945ff")

    # BEST ENTRY table
    # EV tier badge colors
    EV_COLORS = {
        "TIER_1_STRONG":  ("#00ff88", "T1★"),
        "TIER_2_SOLID":   ("#7fff00", "T2"),
        "TIER_3_MARGINAL":("#ffd700", "T3"),
        "TIER_4_NEUTRAL": ("#888888", "—"),
        "TIER_5_AVOID":   ("#ff4444", "AVOID"),
    }
    be_rows = ""
    for e in be[:10]:
        sig_color = "#00ff88" if e.get("signal") == "LONG" else "#ff4444"
        ev_tier = e.get("ev_tier", "TIER_4_NEUTRAL")
        ev_color, ev_label = EV_COLORS.get(ev_tier, ("#888", "—"))
        be_rows += f"""<tr>
          <td style="padding:6px 10px;font-weight:bold;color:#f7931a">{e['symbol']}</td>
          <td style="padding:6px 10px;color:{ev_color};font-weight:bold;font-size:11px">{ev_label}</td>
          <td style="padding:6px 10px;color:#aaa;font-size:12px">{e['ts'][11:16] if len(e.get('ts',''))>11 else '—'}</td>
          <td style="padding:6px 10px">${e.get('price',0):.6g}</td>
          <td style="padding:6px 10px;text-align:right;color:{'#00ff88' if e.get('fr',0)<=0 else '#ff4444'}">{e.get('fr',0):+.4f}%</td>
          <td style="padding:6px 10px;text-align:right">{e.get('dist_low',0):.1f}%</td>
          <td style="padding:6px 10px;text-align:right">{e.get('vol_m',0):.1f}M</td>
          <td style="padding:6px 10px;color:{sig_color};font-weight:bold">{e.get('signal','—')}</td>
        </tr>"""
    if not be_rows:
        be_rows = '<tr><td colspan="8" style="padding:12px;text-align:center;color:#666">No BEST ENTRY signals today</td></tr>'

    # FR extremes table (most negative = best long)
    fr_rows = ""
    for e in fr5[:5]:
        fr_rows += f"""<tr>
          <td style="padding:6px 10px;font-weight:bold;color:#f7931a">{e['symbol']}</td>
          <td style="padding:6px 10px;text-align:right;color:#00ff88;font-weight:bold">{e['fr']:+.4f}%</td>
          <td style="padding:6px 10px">${e['price']:.6g}</td>
          <td style="padding:6px 10px;text-align:right;color:{'#00ff88' if e['pct']>=0 else '#ff4444'}">{e['pct']:+.2f}%</td>
          <td style="padding:6px 10px;color:#00ff88;font-weight:bold">LONG</td>
        </tr>"""

    # EOD snapshot
    eod_rows = ""
    for sym, s in eod.items():
        sig_color = "#00ff88" if s.get("signal") == "LONG" else ("#ff4444" if s.get("signal") == "SHORT" else "#888")
        eod_rows += f"""<tr>
          <td style="padding:6px 10px;font-weight:bold">{sym}</td>
          <td style="padding:6px 10px">${s.get('price',0):.6g}</td>
          <td style="padding:6px 10px;text-align:right;color:{'#00ff88' if s.get('pct',0)>=0 else '#ff4444'}">{s.get('pct',0):+.2f}%</td>
          <td style="padding:6px 10px;text-align:right;color:{'#00ff88' if s.get('fr',0)<=0 else '#ff4444'}">{s.get('fr',0):+.4f}%</td>
          <td style="padding:6px 10px;color:{sig_color}">{s.get('signal','—')}</td>
          <td style="padding:6px 10px;font-size:11px;color:#aaa">{s.get('setup','—')}</td>
        </tr>"""

    btc_close = btc.get('close', 0)
    btc_chg   = btc.get('change_pct', 0)

    html = f"""
<div style="background:#0a0a0a;color:#e0e0e0;font-family:Arial,sans-serif;padding:24px;max-width:900px;margin:0 auto">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#111 0%,#0d1b2a 100%);border:2px solid #f7931a;border-radius:12px;padding:24px;margin-bottom:20px">
    <h1 style="color:#f7931a;margin:0 0 6px 0;font-size:26px;letter-spacing:1px">⚡ NEXYROTH BITUNIX DAILY DIGEST</h1>
    <p style="color:#aaa;margin:0;font-size:14px">{date} | {analytics['total_snapshots']} snapshots | {analytics['symbols_tracked']} symbols tracked | {len(be)} BEST ENTRY signals</p>
  </div>

  <!-- Price OHLC -->
  <div style="background:#111;border:1px solid #222;border-radius:8px;padding:16px;margin-bottom:16px">
    <h2 style="color:#00ff88;margin:0 0 12px 0;font-size:16px">📊 Day OHLC</h2>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#1a1a1a;color:#888;font-size:11px;text-transform:uppercase">
        <th style="padding:8px 12px;text-align:left">Asset</th>
        <th style="padding:8px 12px;text-align:right">Open</th>
        <th style="padding:8px 12px;text-align:right">High</th>
        <th style="padding:8px 12px;text-align:right">Low</th>
        <th style="padding:8px 12px;text-align:right">Close</th>
        <th style="padding:8px 12px;text-align:right">Change</th>
      </tr></thead>
      <tbody>{price_rows}</tbody>
    </table>
  </div>

  <!-- AI Insights -->
  <div style="background:#111;border:2px solid #f7931a;border-radius:8px;padding:20px;margin-bottom:16px">
    <h2 style="color:#f7931a;margin:0 0 14px 0;font-size:16px">🤖 AI Trade Intelligence</h2>
    <div style="font-size:14px;line-height:1.8;color:#ddd">{ai_summary}</div>
  </div>

  <!-- BEST ENTRY Signals -->
  <div style="background:#111;border:1px solid #00ff88;border-radius:8px;padding:16px;margin-bottom:16px">
    <h2 style="color:#00ff88;margin:0 0 12px 0;font-size:16px">✅ BEST ENTRY Signals Seen Today</h2>
    <p style="color:#888;font-size:12px;margin:0 0 10px 0">Negative funding rate + price near daily low = highest quality long setup</p>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="background:#1a1a1a;color:#888;font-size:11px;text-transform:uppercase">
        <th style="padding:6px 10px;text-align:left">Symbol</th>
        <th style="padding:6px 10px;text-align:left">EV Tier</th>
        <th style="padding:6px 10px;text-align:left">Time</th>
        <th style="padding:6px 10px">Price</th>
        <th style="padding:6px 10px;text-align:right">FR%</th>
        <th style="padding:6px 10px;text-align:right">Dist/Low</th>
        <th style="padding:6px 10px;text-align:right">Vol</th>
        <th style="padding:6px 10px">Signal</th>
      </tr></thead>
      <tbody>{be_rows}</tbody>
    </table>
  </div>

  <!-- Funding Rate Extremes -->
  <div style="background:#111;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:16px">
    <h2 style="color:#f7931a;margin:0 0 12px 0;font-size:16px">🔥 Most Negative Funding Rates (Shorts Paying Longs)</h2>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="background:#1a1a1a;color:#888;font-size:11px;text-transform:uppercase">
        <th style="padding:6px 10px;text-align:left">Symbol</th>
        <th style="padding:6px 10px;text-align:right">FR%</th>
        <th style="padding:6px 10px">Price</th>
        <th style="padding:6px 10px;text-align:right">24h%</th>
        <th style="padding:6px 10px">Signal</th>
      </tr></thead>
      <tbody>{fr_rows}</tbody>
    </table>
  </div>

  <!-- EOD Snapshot -->
  <div style="background:#111;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:16px">
    <h2 style="color:#aaa;margin:0 0 12px 0;font-size:16px">📋 End-of-Day Snapshot (Key Symbols)</h2>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="background:#1a1a1a;color:#888;font-size:11px;text-transform:uppercase">
        <th style="padding:6px 10px;text-align:left">Symbol</th>
        <th style="padding:6px 10px">Price</th>
        <th style="padding:6px 10px;text-align:right">24h%</th>
        <th style="padding:6px 10px;text-align:right">FR%</th>
        <th style="padding:6px 10px">Signal</th>
        <th style="padding:6px 10px;text-align:left">Setup</th>
      </tr></thead>
      <tbody>{eod_rows}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="background:#111;border:1px solid #333;border-radius:8px;padding:14px;text-align:center">
    <p style="margin:0;font-size:12px;color:#666">NEXYROTH Trade Intelligence | Bitunix 24/7 Monitor | Cloud Computer</p>
    <p style="margin:4px 0 0 0;font-size:12px">
      <a href="https://www.bitunix.com/futures/BTCUSDT" style="color:#f7931a">Trade BTC on Bitunix</a> &nbsp;|&nbsp;
      <a href="https://www.bitunix.com/futures/SOLUSDT" style="color:#9945ff">Trade SOL</a> &nbsp;|&nbsp;
      <a href="https://www.bitunix.com/futures/ETHUSDT" style="color:#627eea">Trade ETH</a>
    </p>
  </div>
</div>"""
    return html

def send_email(html, date, analytics):
    btc = analytics.get("btc_ohlc", {})
    btc_close = btc.get("close", 0)
    btc_chg   = btc.get("change_pct", 0)
    be_count  = len(analytics.get("best_entries_seen", []))
    arrow = "▲" if btc_chg >= 0 else "▼"
    subject = f"⚡ NEXYROTH Bitunix Digest {date} | BTC ${btc_close:,.0f} {arrow}{btc_chg:+.2f}% | {be_count} BEST ENTRY signal(s)"

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            log(f"✅ Digest sent | id={resp.json().get('id','?')}")
            return True
        else:
            log(f"❌ Email failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log(f"❌ Email error: {e}")
    return False

def run():
    log("=== Bitunix Daily Digest starting ===")
    day_log, today = load_today()
    if not day_log:
        log("No data. Exiting.")
        return

    analytics = analyze(day_log)
    if not analytics:
        log("No snapshots. Exiting.")
        return

    log(f"Analyzed {analytics['total_snapshots']} snapshots | "
        f"BTC {analytics['btc_ohlc'].get('change_pct',0):+.2f}% | "
        f"BEST ENTRIES: {len(analytics['best_entries_seen'])}")

    log("Generating AI summary...")
    ai_summary = ai_summarize(analytics)

    log("Building email...")
    html = build_html(analytics, ai_summary, today)

    log("Sending digest...")
    send_email(html, today, analytics)

    out_file = os.path.join(DATA_DIR, f"bitunix_digest_{today}.html")
    with open(out_file, "w") as f:
        f.write(html)
    log(f"Digest saved → {out_file}")
    log("=== Done ===")

if __name__ == "__main__":
    run()
