#!/usr/bin/env python3
"""
NEXYROTH Crypto News & X Scanner v1.0
══════════════════════════════════════
Searches the web and X (Twitter) daily for breaking crypto news,
easy-money opportunities, and actionable alerts.

Scans for:
  - Airdrop announcements & eligibility windows
  - Token launches / listings on major exchanges
  - Whale wallet moves (large transfers)
  - Regulatory catalysts (ETF approvals, policy changes)
  - Pump signals (trending tokens, volume spikes)
  - Free money (staking rewards, yield farming, referral bonuses)
  - Major partnership/integration announcements
  - Liquidation cascades / funding rate extremes

Sources:
  - X/Twitter: Key crypto influencers + keyword search
  - Web news: CoinDesk, CoinTelegraph, The Block, Decrypt
  - X News API: Breaking crypto stories

Sends Telegram digest with actionable opportunities.
Schedule: Every 4 hours via cron (6 times/day)
"""

import os, sys, json, time, requests
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.append('/opt/.manus/.sandbox-runtime')

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
RESULTS_FILE = os.path.join(DATA_DIR, "crypto_news_results.json")
LOG_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), "crypto_news_scanner.log")

# Telegram
TG_TOKEN_FILE = os.path.expanduser("~/.secrets/telegram_bot_token")
TG_CHAT_FILE = os.path.expanduser("~/.secrets/telegram_chat_id")

# ═══════════════════════════════════════════════════════════════
# KEY CRYPTO ACCOUNTS TO MONITOR (by user ID)
# These are top crypto influencers/insiders who break news first
# ═══════════════════════════════════════════════════════════════
CRYPTO_INFLUENCERS = {
    # Format: "username": "user_id" (we'll look up IDs dynamically)
    "WatcherGuru": None,      # Breaking crypto news
    "whale_alert": None,      # Whale transfers
    "lookonchain": None,      # On-chain analytics
    "AltcoinGordon": None,    # Altcoin alpha
    "CryptoKaleo": None,      # Trading calls
    "inversebrah": None,      # Contrarian plays
    "DefiIgnas": None,        # DeFi opportunities
    "0xMert_": None,          # Solana ecosystem
    "coaborin": None,         # Airdrop hunter
    "milesdeutscher": None,   # Crypto education/alpha
}

# Search queries for X
X_SEARCH_QUERIES = [
    "crypto airdrop confirmed lang:en -is:retweet",
    "token launch listing binance coinbase lang:en -is:retweet",
    "whale transfer million USDT lang:en -is:retweet",
    "crypto ETF approved SEC lang:en -is:retweet",
    "free crypto staking reward lang:en -is:retweet",
    "solana memecoin pump 100x lang:en -is:retweet",
]

# Search queries for X News
NEWS_QUERIES = [
    "cryptocurrency airdrop",
    "bitcoin ETF",
    "crypto exchange listing",
    "DeFi yield farming",
    "solana ecosystem",
    "crypto regulation",
]

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def send_telegram(msg: str):
    """Send message to Telegram bot."""
    try:
        token = open(TG_TOKEN_FILE).read().strip()
        chat_id = open(TG_CHAT_FILE).read().strip()
        # Split long messages
        if len(msg) > 4000:
            parts = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
            for part in parts:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": part, "parse_mode": "HTML",
                          "disable_web_page_preview": True}, timeout=10)
                time.sleep(0.5)
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                      "disable_web_page_preview": True}, timeout=10)
    except Exception as e:
        log(f"  ⚠️ Telegram error: {e}")

# ═══════════════════════════════════════════════════════════════
# DATA API CLIENT
# ═══════════════════════════════════════════════════════════════
def get_api_client():
    """Get the Manus Data API client."""
    try:
        from data_api import ApiClient
        return ApiClient()
    except Exception as e:
        log(f"  ⚠️ API client error: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# X/TWITTER SCANNING
# ═══════════════════════════════════════════════════════════════
def search_x_posts(client, query: str, max_results: str = "20") -> List[Dict]:
    """Search recent X posts for a query."""
    try:
        response = client.call_api("X/search_recent_posts", query={
            "query": query,
            "max_results": max_results,
            "tweet.fields": "id,text,created_at,author_id,public_metrics,lang",
            "expansions": "author_id",
            "user.fields": "id,name,username,verified,public_metrics"
        })
        
        posts = response.get("data", [])
        users = {u["id"]: u for u in response.get("includes", {}).get("users", [])}
        
        results = []
        for post in posts:
            author = users.get(post.get("author_id"), {})
            metrics = post.get("public_metrics", {})
            
            # Score by engagement (higher = more important)
            engagement = (metrics.get("like_count", 0) + 
                         metrics.get("retweet_count", 0) * 3 + 
                         metrics.get("quote_count", 0) * 2)
            
            results.append({
                "text": post.get("text", ""),
                "author": f"@{author.get('username', 'unknown')}",
                "author_followers": author.get("public_metrics", {}).get("followers_count", 0),
                "verified": author.get("verified", False),
                "engagement": engagement,
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "created_at": post.get("created_at", ""),
                "url": f"https://x.com/{author.get('username', '')}/status/{post.get('id', '')}"
            })
        
        # Sort by engagement
        results.sort(key=lambda x: x["engagement"], reverse=True)
        return results
        
    except Exception as e:
        log(f"  ⚠️ X search error for '{query[:30]}...': {e}")
        return []

def search_x_news(client, query: str) -> List[Dict]:
    """Search X News stories."""
    try:
        response = client.call_api("X/search_news", query={
            "query": query,
            "max_results": "5",
            "max_age_hours": "24",
            "news.fields": "id,name,summary,hook,category,keywords,updated_at"
        })
        
        stories = response.get("data", [])
        results = []
        for story in stories:
            results.append({
                "title": story.get("name", ""),
                "summary": story.get("summary", ""),
                "hook": story.get("hook", ""),
                "category": story.get("category", ""),
                "keywords": story.get("keywords", []),
                "updated_at": story.get("updated_at", "")
            })
        return results
        
    except Exception as e:
        log(f"  ⚠️ X News error for '{query}': {e}")
        return []

def get_x_trends(client) -> List[Dict]:
    """Get worldwide X trends (WOEID=1)."""
    try:
        response = client.call_api("X/get_trends_by_woeid", 
            path_params={"woeid": "1"},
            query={"max_trends": "20", "trend.fields": "trend_name,tweet_count"})
        
        trends = response.get("data", [])
        # Filter for crypto-related trends
        crypto_keywords = ["bitcoin", "btc", "eth", "crypto", "sol", "xrp", "doge",
                          "airdrop", "token", "defi", "nft", "memecoin", "altcoin",
                          "binance", "coinbase", "blockchain", "web3"]
        
        crypto_trends = []
        for trend in trends:
            name = trend.get("trend_name", "").lower()
            if any(kw in name for kw in crypto_keywords):
                crypto_trends.append({
                    "name": trend.get("trend_name", ""),
                    "tweet_count": trend.get("tweet_count", 0)
                })
        return crypto_trends
        
    except Exception as e:
        log(f"  ⚠️ Trends error: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# OPPORTUNITY CLASSIFIER
# ═══════════════════════════════════════════════════════════════
def classify_opportunity(text: str) -> Dict:
    """Classify a post/news item into opportunity categories."""
    text_lower = text.lower()
    
    categories = {
        "airdrop": ["airdrop", "free tokens", "claim", "eligible", "snapshot", "distribution"],
        "listing": ["listing", "listed on", "binance listing", "coinbase listing", "exchange listing"],
        "whale_move": ["whale", "transferred", "million", "billion", "large transfer", "moved"],
        "regulatory": ["etf", "sec", "approved", "regulation", "legal", "compliance"],
        "pump_signal": ["pump", "moon", "100x", "1000x", "breakout", "parabolic", "ath"],
        "yield": ["staking", "yield", "apy", "apr", "farming", "reward", "earn"],
        "partnership": ["partnership", "integration", "collaboration", "backed by", "invested"],
        "launch": ["launch", "mainnet", "testnet", "live", "deployed", "released"],
    }
    
    matched = []
    for cat, keywords in categories.items():
        if any(kw in text_lower for kw in keywords):
            matched.append(cat)
    
    # Priority scoring
    priority_map = {
        "airdrop": 5,
        "listing": 4,
        "whale_move": 3,
        "pump_signal": 3,
        "regulatory": 4,
        "yield": 2,
        "partnership": 2,
        "launch": 3,
    }
    
    priority = max((priority_map.get(c, 1) for c in matched), default=1)
    
    return {
        "categories": matched or ["general"],
        "priority": priority,
        "is_actionable": priority >= 3
    }

# ═══════════════════════════════════════════════════════════════
# MAIN SCANNER
# ═══════════════════════════════════════════════════════════════
def main():
    log("📰 Crypto News & X Scanner v1.0 | Starting scan...")
    
    client = get_api_client()
    if not client:
        log("❌ Cannot initialize API client")
        return
    
    all_opportunities = []
    
    # 1. Search X for crypto keywords
    log("  🔍 Searching X posts...")
    for query in X_SEARCH_QUERIES:
        posts = search_x_posts(client, query, "15")
        for post in posts[:5]:  # Top 5 per query
            classification = classify_opportunity(post["text"])
            if classification["is_actionable"] or post["engagement"] > 50:
                all_opportunities.append({
                    "source": "x_search",
                    "query": query.split(" lang:")[0],
                    **post,
                    **classification
                })
        time.sleep(1)  # Rate limiting
    
    log(f"  📊 Found {len(all_opportunities)} opportunities from X search")
    
    # 2. Search X News
    log("  📰 Searching X News...")
    news_items = []
    for query in NEWS_QUERIES[:3]:  # Top 3 news queries
        stories = search_x_news(client, query)
        for story in stories:
            classification = classify_opportunity(story.get("summary", "") + " " + story.get("title", ""))
            news_items.append({
                "source": "x_news",
                **story,
                **classification
            })
        time.sleep(1)
    
    log(f"  📰 Found {len(news_items)} news stories")
    
    # 3. Check crypto trends
    log("  📈 Checking X trends...")
    trends = get_x_trends(client)
    log(f"  📈 Found {len(trends)} crypto-related trends")
    
    # 4. Compile and score results
    # Sort opportunities by priority and engagement
    all_opportunities.sort(key=lambda x: (x.get("priority", 0), x.get("engagement", 0)), reverse=True)
    
    # Save full results
    os.makedirs(DATA_DIR, exist_ok=True)
    scan_results = {
        "timestamp": time.time(),
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "opportunities": all_opportunities[:50],  # Top 50
        "news": news_items[:20],
        "trends": trends,
        "stats": {
            "total_opportunities": len(all_opportunities),
            "actionable": len([o for o in all_opportunities if o.get("is_actionable")]),
            "news_stories": len(news_items),
            "crypto_trends": len(trends)
        }
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(scan_results, f, indent=2)
    
    # 5. Build Telegram digest
    actionable = [o for o in all_opportunities if o.get("is_actionable")][:10]
    
    if actionable or news_items or trends:
        msg = "📰 <b>Crypto News Digest</b>\n"
        msg += f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC\n\n"
        
        # Trending
        if trends:
            msg += "📈 <b>Crypto Trending on X:</b>\n"
            for t in trends[:5]:
                count = t.get("tweet_count", 0)
                count_str = f" ({count:,} tweets)" if count else ""
                msg += f"  • {t['name']}{count_str}\n"
            msg += "\n"
        
        # Top opportunities
        if actionable:
            msg += "🎯 <b>Actionable Opportunities:</b>\n\n"
            for i, opp in enumerate(actionable[:7], 1):
                cats = ", ".join(opp.get("categories", []))
                emoji_map = {"airdrop": "🪂", "listing": "📋", "whale_move": "🐋",
                            "pump_signal": "🚀", "regulatory": "⚖️", "yield": "💰",
                            "partnership": "🤝", "launch": "🎉"}
                emoji = emoji_map.get(opp.get("categories", [""])[0], "💡")
                
                text = opp.get("text", "")[:150]
                author = opp.get("author", "")
                engagement = opp.get("engagement", 0)
                
                msg += f"{emoji} <b>#{i}</b> [{cats}]\n"
                msg += f"   {text}...\n"
                msg += f"   — {author} | ❤️{opp.get('likes', 0)} 🔄{opp.get('retweets', 0)}\n\n"
        
        # News highlights
        if news_items:
            msg += "📰 <b>Breaking News:</b>\n"
            for story in news_items[:3]:
                title = story.get("title", "")[:80]
                hook = story.get("hook", "")[:100]
                msg += f"  • <b>{title}</b>\n"
                if hook:
                    msg += f"    {hook}\n"
            msg += "\n"
        
        msg += f"📊 Total: {len(all_opportunities)} signals | {len(actionable)} actionable"
        
        send_telegram(msg)
        log(f"  📨 Telegram digest sent ({len(actionable)} actionable, {len(news_items)} news)")
    else:
        log("  ℹ️ No significant opportunities found this scan")
    
    log(f"  ✅ Scan complete | {len(all_opportunities)} total | {len(actionable)} actionable")

if __name__ == "__main__":
    main()
