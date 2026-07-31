#!/usr/bin/env python3
"""
NEXYROTH AI Profit Analyzer
════════════════════════════
Analyzes crypto news articles for profit opportunities using:
  Primary:  Ollama (local, free) — qwen2.5:3b
  Fallback: Grok (xAI) — grok-3-mini
  Fallback2: OpenRouter free models

Outputs a ranked profit opportunity report and sends Telegram alert.
"""
import os, json, requests, time
from datetime import datetime, timezone
from pathlib import Path

SECRETS = os.path.expanduser("~/.secrets")
TELEGRAM_TOKEN = open(f"{SECRETS}/telegram_bot_token").read().strip()
TELEGRAM_CHAT  = open(f"{SECRETS}/telegram_chat_id").read().strip()
XAI_KEY        = open(f"{SECRETS}/xai_api_key").read().strip()
OPENROUTER_KEY = open(f"{SECRETS}/openrouter_api_key").read().strip()

OLLAMA_URL     = "http://localhost:11434/api/generate"
RESULTS_FILE   = os.path.expanduser("~/trading_sniper/data/crypto_news_results_v2.json")
REPORT_FILE    = os.path.expanduser("~/trading_sniper/data/profit_analysis_latest.json")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ── AI BACKENDS ──────────────────────────────────────────────────────────────

def ask_ollama(prompt: str, model: str = "qwen2.5:3b") -> str:
    """Query local Ollama model."""
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1200}
        }, timeout=120)
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception as e:
        log(f"  ⚠️ Ollama error: {e}")
    return ""

def ask_grok(prompt: str) -> str:
    """Query Grok via xAI API."""
    try:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-mini",
                "messages": [
                    {"role": "system", "content": "You are a professional crypto trader and analyst. Be concise, specific, and actionable."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 1200,
                "temperature": 0.2,
            },
            timeout=45
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        elif resp.status_code == 403:
            log("  ⚠️ Grok: No credits")
    except Exception as e:
        log(f"  ⚠️ Grok error: {e}")
    return ""

def ask_openrouter(prompt: str) -> str:
    """Query OpenRouter free models — tries best available in order."""
    free_models = [
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # 550B, best quality
        "google/gemma-4-31b-it:free",               # 31B, fast
        "nvidia/nemotron-3-super-120b-a12b:free",   # 120B fallback
        "openai/gpt-oss-20b:free",                  # OpenAI OSS
        "poolside/laguna-s-2.1:free",               # Poolside
    ]
    for model in free_models:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a professional crypto trader and analyst. Be specific, concise, and actionable. Focus on real profit opportunities."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 1200,
                },
                timeout=45
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                if content and len(content) > 50:
                    log(f"    ✅ OpenRouter [{model.split('/')[1]}] responded")
                    return content
            elif resp.status_code == 429:
                log(f"    ⚠️ {model.split('/')[1]} rate-limited, trying next...")
                continue
        except Exception as e:
            log(f"  ⚠️ OpenRouter [{model}] error: {e}")
    return ""

def ask_ai(prompt: str, label: str = "") -> tuple[str, str]:
    """Try OpenRouter (free) → Grok → Ollama as last resort."""
    log(f"  🤖 Asking OpenRouter [{label}]...")
    result = ask_openrouter(prompt)
    if result and len(result) > 50:
        return result, "openrouter:qwen3-8b:free"

    log(f"  🔄 OpenRouter failed, trying Grok [{label}]...")
    result = ask_grok(prompt)
    if result and len(result) > 50:
        return result, "grok-3-mini"

    log(f"  🔄 Grok failed, trying Ollama [{label}]...")
    result = ask_ollama(prompt)
    if result and len(result) > 50:
        return result, "ollama:qwen2.5:3b"

    return "No AI response available.", "none"

# ── ANALYSIS ─────────────────────────────────────────────────────────────────

def analyze_articles(articles: list) -> dict:
    """Run AI analysis on all articles and produce profit report."""

    # Build article summary for AI
    article_text = ""
    for i, a in enumerate(articles, 1):
        article_text += f"{i}. [{a.get('category','?')}] {a.get('title','')}\n   {a.get('description','')[:200]}\n\n"

    current_prices = {
        "BTC": 64507, "ETH": 1909, "SOL": 74.4,
        "BNB": 590, "HYPE": 55.6, "WIF": 0.14, "SUI": 0.69, "AVAX": 6.48
    }

    # ── ANALYSIS 1: Top Immediate Profit Opportunities ──
    prompt1 = f"""You are a professional crypto trader analyzing {len(articles)} news articles for IMMEDIATE profit opportunities.

Current prices: BTC=${current_prices['BTC']:,} | ETH=${current_prices['ETH']:,} | SOL=${current_prices['SOL']} | BNB=${current_prices['BNB']} | HYPE=${current_prices['HYPE']} | WIF=${current_prices['WIF']} | SUI=${current_prices['SUI']}

ARTICLES:
{article_text}

Identify the TOP 5 IMMEDIATE profit opportunities from these articles. For each:
1. What is the opportunity (specific action to take)
2. Which asset/token to trade or claim
3. Entry price or action trigger
4. Expected profit % or $ amount
5. Risk level (Low/Medium/High)
6. Time window (hours/days)
7. Why this is actionable NOW

Focus on: airdrops to claim, tokens to buy before pumps, regulatory catalysts, whale accumulation signals.
Be SPECIFIC and ACTIONABLE. No vague advice."""

    log("  📊 Running profit opportunity analysis...")
    analysis1, model1 = ask_ai(prompt1, "profit_opps")

    # ── ANALYSIS 2: Trade Signals ──
    prompt2 = f"""Based on these {len(articles)} crypto news articles, identify SPECIFIC TRADE SIGNALS for perpetual futures on Bitunix (zero fees).

Current prices: BTC=${current_prices['BTC']:,} | ETH=${current_prices['ETH']:,} | SOL=${current_prices['SOL']} | BNB=${current_prices['BNB']} | HYPE=${current_prices['HYPE']} | WIF=${current_prices['WIF']}

KEY NEWS CONTEXT:
- BTC holding $64,500 | Nasdaq +2% on AI trade comeback
- Institutional crypto trading at record 72% of volume
- JPMorgan warns Clarity Act (crypto bill) failing = headwind
- Coinbase missed Q2 earnings (bearish for COIN, neutral for BTC)
- South Korea KOSPI rebounding 15% (risk-on signal)
- Ark Invest buying Coinbase/Circle, selling Bitmine

ARTICLES:
{article_text[:2000]}

Give me 3 specific trade setups:
Format each as:
TRADE: [LONG/SHORT] [SYMBOL] 
ENTRY: $X
TARGET: $X (+X%)
STOP: $X (-X%)
LEVERAGE: Xx
REASON: [1-2 sentences based on news]
CONFIDENCE: [1-10]"""

    log("  📈 Running trade signal analysis...")
    analysis2, model2 = ask_ai(prompt2, "trade_signals")

    # ── ANALYSIS 3: Free Money / Airdrop Opportunities ──
    airdrop_articles = [a for a in articles if a.get('category') in ('airdrop', 'free_money')]
    if airdrop_articles:
        airdrop_text = "\n".join([f"- {a.get('title','')} | {a.get('description','')[:200]}" for a in airdrop_articles])
        prompt3 = f"""Analyze these crypto airdrop and free money opportunities. For each, tell me:
1. What exactly is the opportunity
2. How to claim/participate (specific steps)
3. Estimated value
4. Deadline or urgency
5. Risk of scam (Low/Medium/High)

OPPORTUNITIES:
{airdrop_text}

Be specific. If there's a claim link or action, state it clearly."""

        log("  🪂 Running airdrop/free money analysis...")
        analysis3, model3 = ask_ai(prompt3, "airdrops")
    else:
        analysis3 = "No specific airdrop articles in this scan."
        model3 = "none"

    return {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "article_count": len(articles),
        "models_used": {"profit": model1, "trades": model2, "airdrops": model3},
        "profit_opportunities": analysis1,
        "trade_signals": analysis2,
        "airdrop_analysis": analysis3,
        "current_prices": current_prices,
    }

# ── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram(msg: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        return resp.status_code == 200
    except:
        return False

# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log("🧠 NEXYROTH AI Profit Analyzer | Starting...")

    # Load latest scan results
    try:
        data = json.loads(Path(RESULTS_FILE).read_text())
        articles = data.get("rss_articles", [])
        log(f"  📰 Loaded {len(articles)} articles from latest scan")
    except Exception as e:
        log(f"  ❌ Cannot load scan results: {e}")
        return

    if not articles:
        log("  ❌ No articles to analyze")
        return

    # Run AI analysis
    report = analyze_articles(articles)

    # Save report
    Path(REPORT_FILE).write_text(json.dumps(report, indent=2))
    log(f"  💾 Report saved to {REPORT_FILE}")

    # Send Telegram digest
    ts = datetime.now().strftime("%b %d %H:%M UTC")
    models = report.get("models_used", {})
    model_str = f"Ollama({models.get('profit','?')})" if "ollama" in models.get('profit','') else models.get('profit','?')

    msg1 = f"""🧠 <b>NEXYROTH AI Profit Analysis</b>
🕐 {ts} | {report['article_count']} articles | AI: {model_str}

💰 <b>TOP PROFIT OPPORTUNITIES</b>
{report['profit_opportunities'][:1800]}"""

    msg2 = f"""📈 <b>TRADE SIGNALS</b>
{report['trade_signals'][:1800]}"""

    msg3 = f"""🪂 <b>AIRDROP / FREE MONEY</b>
{report['airdrop_analysis'][:1200]}

👉 <a href='https://chalkpicks.live'>chalkpicks.live</a>"""

    log("  📨 Sending Telegram reports...")
    ok1 = send_telegram(msg1[:4000])
    time.sleep(1)
    ok2 = send_telegram(msg2[:4000])
    time.sleep(1)
    ok3 = send_telegram(msg3[:4000])

    log(f"  {'✅' if all([ok1,ok2,ok3]) else '⚠️'} Telegram: {sum([ok1,ok2,ok3])}/3 messages sent")

    # Print summary to console
    print("\n" + "="*60)
    print("PROFIT OPPORTUNITIES:")
    print(report['profit_opportunities'][:2000])
    print("\nTRADE SIGNALS:")
    print(report['trade_signals'][:2000])
    print("\nAIRDROP/FREE MONEY:")
    print(report['airdrop_analysis'][:1000])
    print("="*60)

    log("✅ Analysis complete")

if __name__ == "__main__":
    main()
