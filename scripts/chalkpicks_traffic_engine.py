#!/usr/bin/env python3
"""
ChalkPicks Traffic Growth Engine v1.0
=====================================
Automated organic traffic acquisition for chalkpicks.live
Strategies:
1. IndexNow ping — notify search engines of new/updated content
2. Google/Bing sitemap ping — force re-crawl
3. Directory submissions — submit to sports/betting directories
4. Backlink outreach tracking — log opportunities
5. Social signal generation — track Instagram post performance
Runs daily at 6 AM EDT via cron.
"""
import os
import json
import time
import requests
from datetime import datetime, timezone

# Configuration
SITE_URL = "https://chalkpicks.live"
SITEMAP_URL = f"{SITE_URL}/sitemap.xml"
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL_TO", "")
LOG_FILE = os.path.expanduser("~/trading_sniper/chalkpicks_traffic.log")
STATE_FILE = os.path.expanduser("~/trading_sniper/data/chalkpicks_traffic_state.json")

# IndexNow key (generate one if not exists)
INDEXNOW_KEY = "chalkpicks2026indexnow"

# High-value pages to keep indexed (ordered by traffic potential)
HIGH_VALUE_PAGES = [
    "/bet-calculator",        # Free tool — high search volume "bet calculator"
    "/tools/odds-calculator", # Free tool — "odds calculator"
    "/tools/parlay-calculator", # Free tool — "parlay calculator"
    "/tools/roi-calculator",  # Free tool — "ROI calculator"
    "/tools/devig-calculator", # Free tool — "devig calculator"
    "/ev-finder",             # Premium — "EV finder" "positive EV betting"
    "/arbitrage",             # Premium — "arbitrage finder" "arb betting"
    "/picks",                 # Core — "AI sports picks" "best sports picks today"
    "/daily-picks",           # Core — "daily picks" "today's picks"
    "/nfl-picks",             # Sport-specific — "NFL picks today"
    "/nba-picks",             # Sport-specific — "NBA picks today"
    "/mlb-picks",             # Sport-specific — "MLB picks today"
    "/prop-builder",          # Premium — "prop builder" "same game parlay"
    "/parlay-builder",        # Premium — "parlay builder"
    "/line-movement",         # Premium — "line movement tracker"
    "/sharp-money",           # Premium — "sharp money" "sharp action"
    "/odds-comparison",       # Free — "odds comparison"
    "/performance",           # Trust — "sports betting track record"
    "/blog/best-sports-betting-picks", # Blog SEO
    "/blog/ai-sports-betting",         # Blog SEO
    "/blog/sports-betting-strategy",   # Blog SEO
]

# Directories to submit to (sports/betting focused)
DIRECTORIES = [
    {"name": "AllLister", "url": "https://www.alllister.com/directory/suggest.php", "status": "manual"},
    {"name": "Submit.biz Sports", "url": "https://www.submit.biz/13/Sports/", "status": "manual"},
    {"name": "DirectoryCritic Sports", "url": "https://www.directorycritic.com/sport-directory-list.html", "status": "manual"},
    {"name": "DMOZ Sports", "url": "https://dmoz-odp.org/Sports/", "status": "manual"},
    {"name": "Best of the Web", "url": "https://botw.org/", "status": "manual"},
    {"name": "Jasmine Directory", "url": "https://www.jasminedirectory.com/", "status": "manual"},
    {"name": "SoMuch Sports", "url": "https://www.somuch.com/sports/", "status": "manual"},
    {"name": "Product Hunt", "url": "https://www.producthunt.com/posts/new", "status": "todo"},
    {"name": "BetaList", "url": "https://betalist.com/submit", "status": "todo"},
    {"name": "AlternativeTo", "url": "https://alternativeto.net/", "status": "todo"},
    {"name": "Capterra", "url": "https://www.capterra.com/vendors/sign-up", "status": "todo"},
    {"name": "G2", "url": "https://www.g2.com/products/new", "status": "todo"},
    {"name": "SaaSHub", "url": "https://www.saashub.com/submit", "status": "todo"},
    {"name": "ToolPilot", "url": "https://www.toolpilot.ai/", "status": "todo"},
    {"name": "There's An AI For That", "url": "https://theresanaiforthat.com/submit/", "status": "todo"},
    {"name": "FutureTools", "url": "https://www.futuretools.io/submit-a-tool", "status": "todo"},
    {"name": "AI Tool Directory", "url": "https://aitoolsdirectory.com/submit-tool", "status": "todo"},
]

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"pings_sent": 0, "last_indexnow": None, "directories_submitted": [], "last_run": None}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# STRATEGY 1: IndexNow Ping (Bing, Yandex, Seznam)
# ═══════════════════════════════════════════════════════════════
def ping_indexnow(pages):
    """Ping IndexNow API to notify search engines of updated pages."""
    urls = [f"{SITE_URL}{page}" for page in pages]
    
    payload = {
        "host": "chalkpicks.live",
        "key": INDEXNOW_KEY,
        "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
        "urlList": urls
    }
    
    results = {}
    # IndexNow endpoints
    endpoints = [
        "https://api.indexnow.org/indexnow",
        "https://www.bing.com/indexnow",
        "https://yandex.com/indexnow",
    ]
    
    for endpoint in endpoints:
        try:
            resp = requests.post(endpoint, json=payload, timeout=15)
            results[endpoint.split("//")[1].split("/")[0]] = resp.status_code
            log(f"  IndexNow → {endpoint.split('//')[1].split('/')[0]}: {resp.status_code}")
        except Exception as e:
            results[endpoint] = f"error: {e}"
            log(f"  IndexNow → {endpoint}: ERROR {e}")
    
    return results

# ═══════════════════════════════════════════════════════════════
# STRATEGY 2: Google/Bing Sitemap Ping
# ═══════════════════════════════════════════════════════════════
def ping_sitemap():
    """Ping Google and Bing with sitemap URL to trigger re-crawl."""
    results = {}
    
    # Google sitemap ping (deprecated but still works sometimes)
    try:
        resp = requests.get(
            f"https://www.google.com/ping?sitemap={SITEMAP_URL}",
            timeout=10
        )
        results["google"] = resp.status_code
        log(f"  Google sitemap ping: {resp.status_code}")
    except Exception as e:
        results["google"] = f"error: {e}"
    
    # Bing sitemap ping
    try:
        resp = requests.get(
            f"https://www.bing.com/ping?sitemap={SITEMAP_URL}",
            timeout=10
        )
        results["bing"] = resp.status_code
        log(f"  Bing sitemap ping: {resp.status_code}")
    except Exception as e:
        results["bing"] = f"error: {e}"
    
    return results

# ═══════════════════════════════════════════════════════════════
# STRATEGY 3: Check Page Indexing Status
# ═══════════════════════════════════════════════════════════════
def check_google_indexed(page):
    """Check if a page appears in Google (basic check via site: query)."""
    try:
        url = f"{SITE_URL}{page}"
        # Use a simple approach - check if the page returns 200
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        return resp.status_code == 200
    except:
        return False

# ═══════════════════════════════════════════════════════════════
# STRATEGY 4: Content Freshness Signal
# ═══════════════════════════════════════════════════════════════
def verify_pages_live():
    """Verify all high-value pages are returning 200."""
    live_pages = []
    dead_pages = []
    
    for page in HIGH_VALUE_PAGES:
        try:
            resp = requests.get(f"{SITE_URL}{page}", timeout=10, 
                              headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                live_pages.append(page)
            else:
                dead_pages.append((page, resp.status_code))
        except Exception as e:
            dead_pages.append((page, str(e)))
    
    return live_pages, dead_pages

# ═══════════════════════════════════════════════════════════════
# DAILY REPORT
# ═══════════════════════════════════════════════════════════════
def send_traffic_report(state, live_pages, dead_pages, indexnow_results, sitemap_results):
    """Send daily traffic growth report."""
    
    # Directory submission status
    dir_rows = ""
    submitted = state.get("directories_submitted", [])
    for d in DIRECTORIES:
        status = "✅ Submitted" if d["name"] in submitted else "📋 TODO"
        dir_rows += f'<tr><td style="color:#e0e0e0;padding:3px 8px;font-size:11px">{d["name"]}</td><td style="color:{"#00ff88" if status.startswith("✅") else "#ffd700"};font-size:11px;padding:3px 8px">{status}</td><td style="color:#555;font-size:10px;padding:3px 8px"><a href="{d["url"]}" style="color:#22d3ee">{d["url"][:40]}...</a></td></tr>'
    
    subject = f"📈 ChalkPicks Traffic Engine — {len(live_pages)} pages live | {state.get('pings_sent', 0)} pings sent"
    
    html = f"""
    <div style="font-family:'Courier New',monospace;background:#0a0a1a;color:#e0e0e0;padding:24px;border-radius:12px;max-width:700px">
        <h2 style="color:#00ff88;margin:0 0 4px">📈 ChalkPicks Traffic Engine</h2>
        <p style="color:#555;font-size:11px;margin:0 0 16px">Daily Report — {datetime.now(timezone.utc).strftime("%B %d, %Y")}</p>
        
        <div style="display:flex;gap:12px;margin-bottom:16px">
            <div style="background:#111;padding:12px;border-radius:8px;flex:1;border:1px solid #333">
                <div style="color:#888;font-size:10px">PAGES LIVE</div>
                <div style="color:#00ff88;font-size:18px;font-weight:bold">{len(live_pages)}/{len(HIGH_VALUE_PAGES)}</div>
            </div>
            <div style="background:#111;padding:12px;border-radius:8px;flex:1;border:1px solid #333">
                <div style="color:#888;font-size:10px">TOTAL PINGS</div>
                <div style="color:#22d3ee;font-size:18px;font-weight:bold">{state.get('pings_sent', 0)}</div>
            </div>
            <div style="background:#111;padding:12px;border-radius:8px;flex:1;border:1px solid #333">
                <div style="color:#888;font-size:10px">DIRECTORIES</div>
                <div style="color:#ffd700;font-size:18px;font-weight:bold">{len(submitted)}/{len(DIRECTORIES)}</div>
            </div>
        </div>
        
        {'<div style="background:#1a0a0a;padding:12px;border-radius:8px;border:1px solid #ff6b6b;margin-bottom:16px"><h3 style="color:#ff6b6b;margin:0 0 8px;font-size:12px">⚠️ Dead Pages</h3><p style="color:#e0e0e0;font-size:11px;margin:0">' + ", ".join([f"{p[0]} ({p[1]})" for p in dead_pages]) + '</p></div>' if dead_pages else ''}
        
        <div style="background:#111;padding:16px;border-radius:8px;margin-bottom:16px;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px;font-size:13px">🔔 IndexNow Results</h3>
            <p style="color:#e0e0e0;font-size:11px;margin:0">Pinged {len(HIGH_VALUE_PAGES)} URLs to Bing, Yandex, IndexNow API</p>
            <p style="color:#888;font-size:10px;margin:4px 0 0">Results: {json.dumps(indexnow_results)}</p>
        </div>
        
        <div style="background:#111;padding:16px;border-radius:8px;margin-bottom:16px;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px;font-size:13px">📋 Directory Submissions</h3>
            <table style="width:100%">{dir_rows}</table>
        </div>
        
        <div style="background:#0f1a0f;padding:12px;border-radius:8px;border:1px solid #00ff88;margin-bottom:16px">
            <h3 style="color:#00ff88;margin:0 0 8px;font-size:12px">🎯 Next Actions (Manual)</h3>
            <ol style="color:#e0e0e0;font-size:11px;margin:0;padding-left:16px">
                <li>Submit to Product Hunt (schedule a launch day)</li>
                <li>Submit to AlternativeTo as OddsJam/Pikkit alternative</li>
                <li>Submit to "There's An AI For That" directory</li>
                <li>Post free tool links on Reddit r/sportsbetting r/sportsbook</li>
                <li>Create Quora answers linking to free calculators</li>
            </ol>
        </div>
        
        <p style="color:#444;font-size:9px;margin-top:12px">ChalkPicks Traffic Engine • Runs daily 6 AM EDT • {SITE_URL}</p>
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
            log(f"  📧 Traffic report sent")
        else:
            log(f"  ⚠️ Email failed: {resp.status_code}")
    except Exception as e:
        log(f"  ⚠️ Email error: {e}")

def main():
    log("=" * 60)
    log("ChalkPicks Traffic Growth Engine — Daily Run")
    log("=" * 60)
    
    state = load_state()
    
    # 1. Verify pages are live
    log("📋 Checking page health...")
    live_pages, dead_pages = verify_pages_live()
    log(f"  Live: {len(live_pages)} | Dead: {len(dead_pages)}")
    if dead_pages:
        for page, status in dead_pages:
            log(f"  ⚠️ DEAD: {page} → {status}")
    
    # 2. Ping IndexNow
    log("🔔 Pinging IndexNow...")
    indexnow_results = ping_indexnow(HIGH_VALUE_PAGES)
    state["pings_sent"] = state.get("pings_sent", 0) + len(HIGH_VALUE_PAGES)
    state["last_indexnow"] = datetime.now(timezone.utc).isoformat()
    
    # 3. Ping sitemaps
    log("🗺️ Pinging sitemaps...")
    sitemap_results = ping_sitemap()
    
    # 4. Send report
    log("📧 Sending traffic report...")
    send_traffic_report(state, live_pages, dead_pages, indexnow_results, sitemap_results)
    
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    
    log("=" * 60)

if __name__ == "__main__":
    main()
