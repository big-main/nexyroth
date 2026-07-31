#!/usr/bin/env python3
"""
ChalkPicks Social Poster v1.0
Automatically posts daily picks, steam alerts, and free pick teasers
to Discord and Telegram.

Schedule:
  - Daily picks post: 9 AM ET (13:00 UTC)
  - Steam alerts:     Every 30 min (checks for new moves)
  - Evening recap:    9 PM ET (01:00 UTC)

Cron:
  0 13 * * *          cd ~/trading_sniper && python3 scripts/chalkpicks_social_poster.py --mode daily
  */30 * * * *        cd ~/trading_sniper && python3 scripts/chalkpicks_social_poster.py --mode steam
  0 1 * * *           cd ~/trading_sniper && python3 scripts/chalkpicks_social_poster.py --mode recap
"""

import os
import sys
import json
import time
import requests
import argparse
from datetime import datetime, timezone, date
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
CHALKPICKS_API = "https://chalkpicks.live/api/trpc"
CHALKPICKS_URL = "https://chalkpicks.live"

# Telegram
TELEGRAM_TOKEN  = open(os.path.expanduser("~/.secrets/telegram_bot_token")).read().strip()
TELEGRAM_CHAT   = open(os.path.expanduser("~/.secrets/telegram_chat_id")).read().strip()

# Discord — read from secrets file (paste webhook URL there)
DISCORD_WEBHOOK_FILE = os.path.expanduser("~/.secrets/discord_chalkpicks_webhook")
DISCORD_WEBHOOK = ""
if os.path.exists(DISCORD_WEBHOOK_FILE):
    DISCORD_WEBHOOK = open(DISCORD_WEBHOOK_FILE).read().strip()

# State file to avoid duplicate posts
STATE_FILE = os.path.expanduser("~/trading_sniper/data/chalkpicks_poster_state.json")
LOG_FILE   = os.path.expanduser("~/trading_sniper/chalkpicks_poster.log")

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_state() -> dict:
    try:
        return json.loads(Path(STATE_FILE).read_text())
    except:
        return {"posted_picks": [], "posted_steam": [], "last_daily": "", "last_recap": ""}

def save_state(state: dict):
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))

def fetch_picks(limit: int = 10) -> list:
    """Fetch latest picks from ChalkPicks API."""
    try:
        import urllib.parse
        params = json.dumps({"limit": limit, "isActive": True})
        encoded = urllib.parse.quote(f'{{"0":{{"json":{params}}}}}')
        resp = requests.get(
            f"{CHALKPICKS_API}/picks.list?batch=1&input={encoded}",
            timeout=15
        )
        data = resp.json()
        if not isinstance(data, list) or not data:
            return []
        result = data[0].get("result", {}).get("data", {})
        # Navigate: result.data.json or result.data directly
        if isinstance(result, dict) and "json" in result:
            result = result["json"]
        # Now result should have picks/items/data key
        for key in ["picks", "items", "data"]:
            if key in result and isinstance(result[key], list):
                return result[key]
        # If result itself is a list
        if isinstance(result, list):
            return result
    except Exception as e:
        log(f"  ⚠️ Fetch picks error: {e}")
    return []

def fetch_steam_moves(limit: int = 5) -> list:
    """Fetch latest steam moves from ChalkPicks API."""
    try:
        import urllib.parse
        params = json.dumps({"limit": limit})
        encoded = urllib.parse.quote(f'{{"0":{{"json":{params}}}}}')
        # Try multiple possible endpoint names
        for endpoint in ["steamMoves.getRecent", "steam.list", "steamMoves.list", "picks.getSteam"]:
            resp = requests.get(
                f"{CHALKPICKS_API}/{endpoint}?batch=1&input={encoded}",
                timeout=10
            )
            data = resp.json()
            if isinstance(data, list) and data[0].get("result"):
                d = data[0]["result"]["data"]
                if isinstance(d, dict):
                    for key in ["moves", "items", "data", "json"]:
                        if key in d and isinstance(d[key], list):
                            return d[key]
    except Exception as e:
        log(f"  ⚠️ Fetch steam error: {e}")
    return []

def format_odds(odds: int) -> str:
    """Format odds as American odds string."""
    if odds > 0:
        return f"+{odds}"
    return str(odds)

def get_sport_emoji(sport: str) -> str:
    emojis = {
        "nfl": "🏈", "nba": "🏀", "mlb": "⚾", "nhl": "🏒",
        "ncaaf": "🏈", "ncaab": "🏀", "soccer": "⚽", "mma": "🥊",
        "boxing": "🥊", "tennis": "🎾", "golf": "⛳"
    }
    return emojis.get((sport or "").lower(), "🎯")

def get_tier_label(tier: str) -> str:
    labels = {"free": "🆓 FREE", "premium": "⭐ PREMIUM", "vip": "💎 VIP"}
    return labels.get((tier or "").lower(), "🎯")

def get_result_emoji(result: str) -> str:
    results = {"win": "✅ WIN", "loss": "❌ LOSS", "push": "🔄 PUSH", "pending": "⏳ PENDING"}
    return results.get((result or "").lower(), "⏳ PENDING")

# ═══════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════
def send_telegram(msg: str, parse_mode: str = "HTML") -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT,
                "text": msg,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            },
            timeout=10
        )
        if resp.status_code == 200:
            return True
        log(f"  ⚠️ Telegram error: {resp.text[:100]}")
    except Exception as e:
        log(f"  ⚠️ Telegram send error: {e}")
    return False

# ═══════════════════════════════════════════════════════════════
# DISCORD
# ═══════════════════════════════════════════════════════════════
def send_discord(content: str = None, embeds: list = None) -> bool:
    if not DISCORD_WEBHOOK:
        log("  ⚠️ No Discord webhook configured — skipping Discord post")
        return False
    try:
        payload = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds
        resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            return True
        log(f"  ⚠️ Discord error: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        log(f"  ⚠️ Discord send error: {e}")
    return False

# ═══════════════════════════════════════════════════════════════
# DAILY PICKS POST
# ═══════════════════════════════════════════════════════════════
def post_daily_picks():
    log("📋 Posting daily picks...")
    state = load_state()
    today = date.today().isoformat()

    if state.get("last_daily") == today:
        log("  ℹ️ Daily picks already posted today — skipping")
        return

    picks = fetch_picks(limit=10)
    if not picks:
        log("  ⚠️ No picks found")
        return

    # Filter to today's picks
    today_picks = [p for p in picks if p.get("pickDate", "")[:10] == today]
    if not today_picks:
        # Fall back to most recent picks
        today_picks = picks[:5]

    # Separate free vs premium
    free_picks = [p for p in today_picks if p.get("tier", "").lower() == "free"]
    premium_picks = [p for p in today_picks if p.get("tier", "").lower() != "free"]

    # ── TELEGRAM ──────────────────────────────────────────────
    tg_lines = [
        f"🎯 <b>ChalkPicks Daily Picks — {today}</b>",
        f"📊 {len(today_picks)} picks today | {len(free_picks)} free | {len(premium_picks)} premium",
        ""
    ]

    for pick in today_picks[:6]:
        sport_emoji = get_sport_emoji(pick.get("sportKey", ""))
        tier_label  = get_tier_label(pick.get("tier", "free"))
        odds_str    = format_odds(int(pick.get("odds", 0) or 0))
        confidence  = pick.get("confidenceScore", 0)
        edge        = pick.get("edgeScore", "N/A")
        rec         = pick.get("recommendation", "N/A")
        home        = pick.get("homeTeam", "")
        away        = pick.get("awayTeam", "")
        matchup     = f"{away} @ {home}" if home and away else ""

        tg_lines.append(f"{sport_emoji} <b>{rec}</b>")
        if matchup:
            tg_lines.append(f"   {matchup}")
        tg_lines.append(f"   Odds: <b>{odds_str}</b> | Confidence: <b>{confidence}%</b> | Edge: <b>{edge}%</b>")
        tg_lines.append(f"   {tier_label}")
        tg_lines.append("")

    if premium_picks:
        tg_lines.append(f"🔒 <b>{len(premium_picks)} more premium picks available</b>")
        tg_lines.append(f"👉 <a href='{CHALKPICKS_URL}/picks'>View all picks at chalkpicks.live</a>")
    else:
        tg_lines.append(f"👉 <a href='{CHALKPICKS_URL}/picks'>View all picks at chalkpicks.live</a>")

    tg_msg = "\n".join(tg_lines)
    tg_ok = send_telegram(tg_msg)
    log(f"  {'✅' if tg_ok else '❌'} Telegram daily picks posted")

    # ── DISCORD ───────────────────────────────────────────────
    if DISCORD_WEBHOOK:
        embeds = []
        for pick in today_picks[:5]:
            sport_emoji = get_sport_emoji(pick.get("sportKey", ""))
            odds_str    = format_odds(int(pick.get("odds", 0) or 0))
            confidence  = pick.get("confidenceScore", 0)
            edge        = pick.get("edgeScore", "N/A")
            rec         = pick.get("recommendation", "N/A")
            home        = pick.get("homeTeam", "")
            away        = pick.get("awayTeam", "")
            matchup     = f"{away} @ {home}" if home and away else "—"
            tier        = pick.get("tier", "free").lower()
            color       = 0x22c55e if tier == "free" else 0xf59e0b  # green for free, gold for premium

            embed = {
                "title": f"{sport_emoji} {rec}",
                "description": f"**Matchup:** {matchup}\n**Odds:** {odds_str} | **Confidence:** {confidence}% | **Edge:** {edge}%",
                "color": color,
                "footer": {"text": f"ChalkPicks • {today} • chalkpicks.live"},
                "url": f"{CHALKPICKS_URL}/picks"
            }
            if pick.get("aiAnalysis"):
                embed["fields"] = [{"name": "AI Analysis", "value": pick["aiAnalysis"][:200] + "...", "inline": False}]
            embeds.append(embed)

        header_content = f"🎯 **ChalkPicks Daily Picks — {today}**\n{len(today_picks)} picks today | {len(free_picks)} free | {len(premium_picks)} premium\n👉 {CHALKPICKS_URL}/picks"
        dc_ok = send_discord(content=header_content, embeds=embeds[:10])
        log(f"  {'✅' if dc_ok else '❌'} Discord daily picks posted")

    state["last_daily"] = today
    save_state(state)
    log("✅ Daily picks post complete")

# ═══════════════════════════════════════════════════════════════
# STEAM ALERTS
# ═══════════════════════════════════════════════════════════════
def post_steam_alerts():
    log("🔥 Checking steam moves...")
    state = load_state()
    moves = fetch_steam_moves(limit=5)

    if not moves:
        # Fallback: check picks with high edge as "steam" signals
        picks = fetch_picks(limit=10)
        today = date.today().isoformat()
        moves = [p for p in picks
                 if float(p.get("edgeScore", 0) or 0) >= 8.0
                 and p.get("pickDate", "")[:10] == today
                 and str(p.get("id")) not in state.get("posted_steam", [])]

    if not moves:
        log("  ℹ️ No new steam moves found")
        return

    new_moves = [m for m in moves if str(m.get("id")) not in state.get("posted_steam", [])]
    if not new_moves:
        log("  ℹ️ No new steam moves to post")
        return

    for move in new_moves[:3]:
        pick_id  = str(move.get("id", ""))
        sport    = get_sport_emoji(move.get("sportKey", ""))
        rec      = move.get("recommendation", "N/A")
        odds_str = format_odds(int(move.get("odds", 0) or 0))
        edge     = move.get("edgeScore", "N/A")
        home     = move.get("homeTeam", "")
        away     = move.get("awayTeam", "")
        matchup  = f"{away} @ {home}" if home and away else ""

        # Telegram
        tg_msg = (
            f"🔥 <b>STEAM MOVE ALERT</b>\n"
            f"{sport} <b>{rec}</b>\n"
        )
        if matchup:
            tg_msg += f"📍 {matchup}\n"
        tg_msg += (
            f"💰 Odds: <b>{odds_str}</b> | Edge: <b>{edge}%</b>\n"
            f"⚡ Sharp money detected — act fast!\n"
            f"👉 <a href='{CHALKPICKS_URL}/picks'>chalkpicks.live/picks</a>"
        )
        tg_ok = send_telegram(tg_msg)

        # Discord
        if DISCORD_WEBHOOK:
            embed = {
                "title": f"🔥 STEAM MOVE: {sport} {rec}",
                "description": (
                    f"{'**Matchup:** ' + matchup + chr(10) if matchup else ''}"
                    f"**Odds:** {odds_str} | **Edge:** {edge}%\n"
                    f"⚡ Sharp money detected — act fast!"
                ),
                "color": 0xff6b35,
                "footer": {"text": f"ChalkPicks Steam Alert • chalkpicks.live"},
                "url": f"{CHALKPICKS_URL}/picks"
            }
            dc_ok = send_discord(content="@here 🔥 **STEAM MOVE ALERT**", embeds=[embed])
            log(f"  {'✅' if dc_ok else '❌'} Discord steam alert posted")

        log(f"  {'✅' if tg_ok else '❌'} Telegram steam alert: {rec}")
        state.setdefault("posted_steam", []).append(pick_id)

    # Keep state list bounded
    state["posted_steam"] = state["posted_steam"][-100:]
    save_state(state)
    log("✅ Steam alerts check complete")

# ═══════════════════════════════════════════════════════════════
# EVENING RECAP
# ═══════════════════════════════════════════════════════════════
def post_evening_recap():
    log("🌙 Posting evening recap...")
    state = load_state()
    today = date.today().isoformat()

    if state.get("last_recap") == today:
        log("  ℹ️ Recap already posted today — skipping")
        return

    picks = fetch_picks(limit=20)
    today_picks = [p for p in picks if p.get("pickDate", "")[:10] == today]

    wins   = [p for p in today_picks if p.get("result") == "win"]
    losses = [p for p in today_picks if p.get("result") == "loss"]
    pushes = [p for p in today_picks if p.get("result") == "push"]
    pending = [p for p in today_picks if p.get("result") in ("pending", None, "")]

    total = len(today_picks)
    settled = len(wins) + len(losses) + len(pushes)
    win_rate = round(len(wins) / settled * 100) if settled > 0 else 0

    # Telegram recap
    tg_lines = [
        f"🌙 <b>ChalkPicks Daily Recap — {today}</b>",
        "",
        f"📊 <b>Record: {len(wins)}-{len(losses)}{'-' + str(len(pushes)) if pushes else ''}</b>",
        f"🎯 Win Rate: <b>{win_rate}%</b> ({settled} settled)",
    ]
    if pending:
        tg_lines.append(f"⏳ {len(pending)} picks still pending")
    tg_lines.append("")

    for pick in wins[:3]:
        sport = get_sport_emoji(pick.get("sportKey", ""))
        rec = pick.get("recommendation", "N/A")
        odds_str = format_odds(int(pick.get("odds", 0) or 0))
        tg_lines.append(f"✅ {sport} {rec} ({odds_str})")

    tg_lines += [
        "",
        f"🔜 Tomorrow's picks drop at 9 AM ET",
        f"👉 <a href='{CHALKPICKS_URL}/picks'>chalkpicks.live/picks</a>"
    ]

    tg_msg = "\n".join(tg_lines)
    tg_ok = send_telegram(tg_msg)
    log(f"  {'✅' if tg_ok else '❌'} Telegram recap posted")

    # Discord recap
    if DISCORD_WEBHOOK:
        color = 0x22c55e if win_rate >= 50 else 0xef4444
        embed = {
            "title": f"🌙 Daily Recap — {today}",
            "description": (
                f"**Record: {len(wins)}-{len(losses)}{'-' + str(len(pushes)) if pushes else ''}** | Win Rate: {win_rate}%\n"
                f"{settled} picks settled | {len(pending)} pending\n\n"
                + "\n".join([f"✅ {get_sport_emoji(p.get('sportKey',''))} {p.get('recommendation','N/A')} ({format_odds(int(p.get('odds',0) or 0))})" for p in wins[:3]])
            ),
            "color": color,
            "footer": {"text": f"ChalkPicks • Tomorrow's picks at 9 AM ET • chalkpicks.live"},
            "url": f"{CHALKPICKS_URL}/picks"
        }
        dc_ok = send_discord(embeds=[embed])
        log(f"  {'✅' if dc_ok else '❌'} Discord recap posted")

    state["last_recap"] = today
    save_state(state)
    log("✅ Evening recap complete")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "steam", "recap", "all"], default="all")
    args = parser.parse_args()

    log(f"🚀 ChalkPicks Social Poster — mode={args.mode}")

    if args.mode in ("daily", "all"):
        post_daily_picks()
    if args.mode in ("steam", "all"):
        post_steam_alerts()
    if args.mode in ("recap", "all"):
        post_evening_recap()

    log("✅ Done")
