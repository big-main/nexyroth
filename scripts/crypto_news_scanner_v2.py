#!/usr/bin/env python3
"""
NEXYROTH Crypto News & X Scanner v2.0 — Cloud Computer Edition
═══════════════════════════════════════════════════════════════
Standalone version that runs on the cloud computer without Manus Data API.
Uses:
  - RSS feeds: CoinTelegraph, CoinDesk, Decrypt, The Block, CryptoSlate
  - Grok AI (xAI) with live X/web search for breaking opportunities
  - Direct keyword classification for airdrop/free money signals
  - Telegram digest with actionable opportunities

Schedule: Every 4 hours via cron
  0 */4 * * * cd ~/trading_sniper && python3 scripts/crypto_news_scanner_v2.py >> logs/crypto_news.log 2>&1
"""

import os, sys, json, time, re, requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import xml.etree.ElementTree as ET

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
SECRETS = os.path.expanduser("~/.secrets")
TELEGRAM_TOKEN = open(f"{SECRETS}/telegram_bot_token").read().strip()
TELEGRAM_CHAT  = open(f"{SECRETS}/telegram_chat_id").read().strip()
XAI_KEY        = open(f"{SECRETS}/xai_api_key").read().strip()

DATA_DIR = os.path.expanduser("~/trading_sniper/data")
LOG_FILE = os.path.expanduser("~/trading_sniper/logs/crypto_news.log")
STATE_FILE = f"{DATA_DIR}/news_scanner_v2_state.json"
RESULTS_FILE = f"{DATA_DIR}/crypto_news_results_v2.json"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.expanduser("~/trading_sniper/logs"), exist_ok=True)

# RSS feeds — all confirmed working
RSS_FEEDS = [
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",       "https://decrypt.co/feed"),
    ("The Block",     "https://www.theblock.co/rss.xml"),
    ("CryptoSlate",   "https://cryptoslate.com/feed/"),
    ("BeInCrypto",    "https://beincrypto.com/feed/"),
    ("NewsBTC",       "https://www.newsbtc.com/feed/"),
]

# Keyword categories for classification
KEYWORD_CATS = {
    "airdrop": ["airdrop", "air drop", "free tokens", "claim tokens", "token distribution",
                "retroactive", "snapshot", "eligibility", "TGE", "token generation event",
                "free claim", "community allocation"],
    "free_money": ["free crypto", "earn free", "referral bonus", "bug bounty", "quest reward",
                   "galxe", "zealy", "layer3", "crew3", "points program", "testnet reward",
                   "ambassador", "bounty", "earn rewards", "passive income", "staking reward",
                   "yield farming", "liquidity mining", "APY", "APR"],
    "listing": ["listed on", "now on binance", "now on coinbase", "exchange listing",
                "token launch", "TGE today", "launches today", "IDO", "IEO", "launchpad"],
    "whale": ["whale", "large transfer", "moved to exchange", "institutional", "fund bought",
              "million transferred", "billion transferred", "accumulation", "large buy"],
    "regulatory": ["SEC approved", "ETF approved", "CFTC", "regulatory", "legal", "ban lifted",
                   "approved by", "legislation", "compliance", "license granted"],
    "pump": ["surges", "pumps", "moon", "ATH", "all time high", "breakout", "rally",
             "skyrockets", "+100%", "+200%", "+500%", "massive gains"],
    "defi": ["DeFi", "yield", "protocol", "TVL", "liquidity", "DEX", "AMM", "lending",
             "borrowing", "collateral", "vault", "pool"],
}

PRIORITY_MAP = {
    "airdrop": 5, "free_money": 5, "listing": 4, "whale": 3,
    "regulatory": 4, "pump": 3, "defi": 2
}

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def load_state() -> dict:
    try:
        return json.loads(Path(STATE_FILE).read_text())
    except:
        return {"seen_titles": [], "last_grok_scan": ""}

def save_state(state: dict):
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))

# ═══════════════════════════════════════════════════════════════
# RSS SCANNER
# ═══════════════════════════════════════════════════════════════
def parse_rss(source: str, url: str) -> List[Dict]:
    """Fetch and parse an RSS feed, return list of articles."""
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 CryptoScanner/2.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = []
        # Handle both RSS and Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for item in root.iter("item"):
            title_el = item.find("title")
            desc_el  = item.find("description")
            link_el  = item.find("link")
            date_el  = item.find("pubDate")
            title = title_el.text if title_el is not None else ""
            desc  = desc_el.text  if desc_el  is not None else ""
            link  = link_el.text  if link_el  is not None else ""
            date  = date_el.text  if date_el  is not None else ""
            # Strip HTML from description
            desc = re.sub(r"<[^>]+>", " ", desc or "").strip()[:300]
            if title:
                items.append({
                    "source": source,
                    "title": title.strip(),
                    "description": desc,
                    "link": link.strip() if link else "",
                    "date": date.strip() if date else "",
                })
        return items[:20]
    except Exception as e:
        log(f"  ⚠️ RSS error [{source}]: {e}")
        return []

def classify_article(article: Dict) -> Optional[str]:
    """Classify article into a category based on keywords."""
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for cat, keywords in KEYWORD_CATS.items():
        for kw in keywords:
            if kw.lower() in text:
                return cat
    return None

def score_article(article: Dict, category: str) -> int:
    """Score article by relevance."""
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    score = PRIORITY_MAP.get(category, 1)
    # Boost for high-value keywords
    boosts = ["free", "claim", "airdrop", "confirmed", "approved", "launch", "today", "now"]
    for b in boosts:
        if b in text:
            score += 1
    return min(score, 10)

# ═══════════════════════════════════════════════════════════════
# GROK AI SCAN
# ═══════════════════════════════════════════════════════════════
def grok_scan_opportunities() -> List[Dict]:
    """Use Grok AI to search X and web for breaking crypto opportunities."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    prompts = [
        f"Search X/Twitter and the web right now for the top 5 crypto AIRDROP announcements trending today {today}. For each: token name, what the airdrop is, how to qualify/claim, any deadline. Be specific with real data you find.",
        f"Search X/Twitter and the web right now for the top 5 FREE MONEY opportunities in crypto today {today}. Include: bug bounties, referral bonuses, quest rewards (Galxe/Zealy/Layer3), testnet incentives, staking rewards with high APY. Token names, amounts, how to get them.",
        f"Search X/Twitter and the web right now for the top 3 BREAKING CRYPTO NEWS stories today {today} that could move prices. Include: ETF approvals, exchange listings, whale moves, regulatory news, major protocol launches.",
    ]

    results = []
    for i, prompt in enumerate(prompts):
        try:
            resp = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {XAI_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "grok-3-mini",
                    "messages": [
                        {"role": "system", "content": "You are a crypto intelligence analyst. Search X/Twitter and the web for real, current information. Be specific with token names, amounts, links, and deadlines. Only report things you actually find in your search results."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.3,
                },
                timeout=45
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                results.append({
                    "source": "grok_ai",
                    "query_type": ["airdrop", "free_money", "breaking_news"][i],
                    "content": content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                log(f"  ✅ Grok scan [{['airdrop', 'free_money', 'breaking'][i]}]: {len(content)} chars")
            elif resp.status_code == 403:
                log(f"  ⚠️ Grok API: No credits — using RSS only")
                break
            else:
                log(f"  ⚠️ Grok API error: {resp.status_code}")
            time.sleep(2)
        except Exception as e:
            log(f"  ⚠️ Grok scan error: {e}")

    return results

# ═══════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════
def send_telegram(msg: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        return resp.status_code == 200
    except Exception as e:
        log(f"  ⚠️ Telegram error: {e}")
        return False

def cat_emoji(cat: str) -> str:
    return {"airdrop": "🪂", "free_money": "💵", "listing": "📋", "whale": "🐋",
            "regulatory": "⚖️", "pump": "🚀", "defi": "🌊"}.get(cat, "📰")

# ═══════════════════════════════════════════════════════════════
# MAIN SCAN
# ═══════════════════════════════════════════════════════════════
def run_scan():
    log("📰 Crypto News Scanner v2.0 | Starting scan...")
    state = load_state()
    seen = set(state.get("seen_titles", []))
    scan_time = datetime.now(timezone.utc).isoformat()

    # ── 1. RSS SCAN ──────────────────────────────────────────
    log("  📡 Scanning RSS feeds...")
    all_articles = []
    for source, url in RSS_FEEDS:
        articles = parse_rss(source, url)
        all_articles.extend(articles)
        log(f"    {source}: {len(articles)} articles")

    # Classify and filter
    actionable = []
    for art in all_articles:
        title = art.get("title", "")
        if title in seen:
            continue
        cat = classify_article(art)
        if cat:
            art["category"] = cat
            art["priority"] = score_article(art, cat)
            actionable.append(art)
            seen.add(title)

    # Sort by priority
    actionable.sort(key=lambda x: x.get("priority", 0), reverse=True)
    log(f"  📊 RSS: {len(all_articles)} total | {len(actionable)} actionable")

    # ── 2. GROK AI SCAN ──────────────────────────────────────
    log("  🤖 Running Grok AI scan...")
    grok_results = grok_scan_opportunities()

    # ── 3. SAVE RESULTS ──────────────────────────────────────
    results = {
        "scan_time": scan_time,
        "rss_articles": actionable[:30],
        "grok_insights": grok_results,
        "total_rss": len(all_articles),
        "total_actionable": len(actionable),
    }
    Path(RESULTS_FILE).write_text(json.dumps(results, indent=2))

    # ── 4. TELEGRAM DIGEST ───────────────────────────────────
    today = datetime.now().strftime("%b %d, %Y %H:%M UTC")
    lines = [
        f"📰 <b>NEXYROTH Crypto Scanner v2.0</b>",
        f"🕐 {today}",
        f"📊 {len(all_articles)} articles scanned | {len(actionable)} actionable",
        "",
    ]

    # Top RSS opportunities
    if actionable:
        lines.append("🔥 <b>TOP OPPORTUNITIES (RSS)</b>")
        for art in actionable[:8]:
            emoji = cat_emoji(art.get("category", ""))
            title = art.get("title", "")[:80]
            source = art.get("source", "")
            link = art.get("link", "")
            prio = art.get("priority", 0)
            if link:
                lines.append(f"{emoji} <a href='{link}'>{title}</a> [{source}]")
            else:
                lines.append(f"{emoji} {title} [{source}]")
        lines.append("")

    # Grok AI insights
    if grok_results:
        lines.append("🤖 <b>GROK AI LIVE SCAN</b>")
        for gr in grok_results:
            qtype = gr.get("query_type", "")
            content = gr.get("content", "")
            # Truncate to fit Telegram
            content_short = content[:600] + ("..." if len(content) > 600 else "")
            emoji = {"airdrop": "🪂", "free_money": "💵", "breaking_news": "⚡"}.get(qtype, "📰")
            lines.append(f"{emoji} <b>{qtype.replace('_', ' ').title()}</b>")
            lines.append(content_short)
            lines.append("")

    if not actionable and not grok_results:
        lines.append("ℹ️ No new actionable opportunities found this scan.")

    lines.append(f"👉 <a href='https://chalkpicks.live'>chalkpicks.live</a> | Next scan in 4h")

    # Split into chunks if too long (Telegram 4096 char limit)
    full_msg = "\n".join(lines)
    if len(full_msg) > 4000:
        # Send in parts
        part1 = "\n".join(lines[:lines.index("") + 1 if "" in lines else len(lines)//2])
        part2 = "\n".join(lines[len(lines)//2:])
        ok1 = send_telegram(full_msg[:4000])
        if grok_results:
            time.sleep(1)
            grok_msg = f"🤖 <b>GROK AI SCAN CONTINUED</b>\n\n"
            for gr in grok_results:
                qtype = gr.get("query_type", "")
                content = gr.get("content", "")[:1200]
                emoji = {"airdrop": "🪂", "free_money": "💵", "breaking_news": "⚡"}.get(qtype, "📰")
                grok_msg += f"{emoji} <b>{qtype.replace('_',' ').title()}</b>\n{content}\n\n"
            send_telegram(grok_msg[:4000])
        tg_ok = ok1
    else:
        tg_ok = send_telegram(full_msg)

    log(f"  {'✅' if tg_ok else '❌'} Telegram digest sent")

    # Update state
    state["seen_titles"] = list(seen)[-500:]  # Keep last 500
    state["last_scan"] = scan_time
    save_state(state)

    log(f"✅ Scan complete | {len(actionable)} RSS actionable | {len(grok_results)} Grok insights")
    return results

# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    run_scan()
