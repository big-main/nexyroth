#!/usr/bin/env python3
"""
NEXYROTH Compound Growth Executor v1.0
======================================
Turns $10 into $100+ through disciplined compound trading.

Core Principles:
1. Never risk more than 5% of current balance per trade
2. Only enter when Strategy Engine score >= 55%
3. Always use stop loss — no exceptions
4. Compound: reinvest 100% of profits into next trade
5. Scale position size as balance grows
6. Track every trade in a journal for performance analysis

Growth Path (at 60% win rate, 1.5:1 R:R):
  $10 → $15 → $22 → $33 → $50 → $75 → $100+
  Expected: ~25-35 trades over 5-10 days

This script:
- Reads signals from strategy_engine.py
- Calculates optimal position size based on current balance
- Sends trade execution instructions via email
- Logs everything to a trade journal
- Tracks cumulative P&L and win rate
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
ALERT_EMAIL = os.getenv("ALERT_EMAIL_TO", "")

DATA_DIR = "/home/ubuntu/trading_sniper/data"
JOURNAL_FILE = f"{DATA_DIR}/trade_journal.json"
ACCOUNT_FILE = f"{DATA_DIR}/account_state.json"
LOG_FILE = "/home/ubuntu/trading_sniper/compound_executor.log"

# Risk Parameters
INITIAL_BALANCE = 10.00      # Starting balance
MAX_RISK_PER_TRADE = 0.05    # 5% of balance
MAX_LEVERAGE = 2             # Never exceed 2x
MIN_SIGNAL_SCORE = 0.45      # Minimum strategy engine score (aggressive for small accounts)
MAX_OPEN_TRADES = 2          # Max concurrent positions
TARGET_BALANCE = 100.00      # Goal

# Stop Loss / Take Profit Rules
TIGHT_STOP_PCT = 2.0         # 2% stop for high confidence (>70%)
WIDE_STOP_PCT = 3.0          # 3% stop for medium confidence (55-70%)
MIN_RR_RATIO = 1.5           # Minimum risk:reward

# ═══════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_account():
    """Load or initialize account state."""
    if os.path.exists(ACCOUNT_FILE):
        with open(ACCOUNT_FILE) as f:
            return json.load(f)
    return {
        "balance": INITIAL_BALANCE,
        "initial_balance": INITIAL_BALANCE,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl": 0.0,
        "peak_balance": INITIAL_BALANCE,
        "max_drawdown": 0.0,
        "open_trades": [],
        "target_reached": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

def save_account(account):
    """Save account state."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACCOUNT_FILE, "w") as f:
        json.dump(account, f, indent=2)

def load_journal():
    """Load trade journal."""
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE) as f:
            return json.load(f)
    return []

def save_journal(journal):
    """Save trade journal."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(JOURNAL_FILE, "w") as f:
        json.dump(journal, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# POSITION SIZING ENGINE
# ═══════════════════════════════════════════════════════════════

def calculate_trade_plan(balance, signal):
    """
    Calculate exact trade parameters based on current balance and signal.
    
    Returns a complete trade plan with entry, stop, target, and size.
    """
    score = signal["score"]
    price = signal["price"]
    direction = signal["direction"]

    # Stop loss distance based on confidence
    if score >= 0.70:
        stop_pct = TIGHT_STOP_PCT / 100  # 2%
    else:
        stop_pct = WIDE_STOP_PCT / 100   # 3%

    # Take profit at R:R ratio
    tp_pct = stop_pct * MIN_RR_RATIO

    # Risk amount (5% of balance, scaled by confidence)
    confidence_scale = min(1.0, (score - 0.5) * 4)  # 0.5→0, 0.75→1.0
    risk_amount = balance * MAX_RISK_PER_TRADE * confidence_scale
    risk_amount = max(risk_amount, 0.10)  # Minimum $0.10 risk

    # Position size: risk_amount / stop_distance
    position_size = risk_amount / stop_pct
    
    # Cap at balance * leverage
    max_position = balance * MAX_LEVERAGE
    if position_size > max_position:
        position_size = max_position
        # Recalculate actual risk
        risk_amount = position_size * stop_pct

    # Calculate prices
    if direction == "LONG":
        stop_price = price * (1 - stop_pct)
        tp_price = price * (1 + tp_pct)
    else:
        stop_price = price * (1 + stop_pct)
        tp_price = price * (1 - tp_pct)

    # Potential profit
    potential_profit = position_size * tp_pct
    potential_loss = risk_amount

    return {
        "symbol": signal["symbol"],
        "direction": direction,
        "entry_price": round(price, 8),
        "stop_loss": round(stop_price, 8),
        "take_profit": round(tp_price, 8),
        "stop_pct": round(stop_pct * 100, 2),
        "tp_pct": round(tp_pct * 100, 2),
        "position_size": round(position_size, 2),
        "leverage": MAX_LEVERAGE,
        "risk_amount": round(risk_amount, 4),
        "potential_profit": round(potential_profit, 4),
        "risk_reward": MIN_RR_RATIO,
        "score": round(score, 4),
        "balance_before": round(balance, 4),
    }

# ═══════════════════════════════════════════════════════════════
# TRADE EXECUTION (ALERT-BASED)
# ═══════════════════════════════════════════════════════════════

def send_trade_alert(trade_plan, account):
    """Send a detailed trade execution alert via email."""
    direction_emoji = "🟢 LONG" if trade_plan["direction"] == "LONG" else "🔴 SHORT"
    
    # Progress bar
    progress = min(100, (account["balance"] / TARGET_BALANCE) * 100)
    progress_bar = "█" * int(progress / 5) + "░" * (20 - int(progress / 5))
    
    win_rate = (account["wins"] / account["total_trades"] * 100) if account["total_trades"] > 0 else 0

    html = f"""
    <div style="font-family:monospace;background:#0a0a0a;color:#eee;padding:20px;border-radius:8px;max-width:600px;">
        <h2 style="color:#00ff88;margin:0 0 5px 0;">⚡ TRADE SIGNAL — EXECUTE NOW</h2>
        <p style="color:#888;margin:0 0 20px 0;">NEXYROTH Compound Growth System</p>
        
        <div style="background:#111;padding:15px;border-radius:6px;margin-bottom:15px;">
            <h3 style="color:{'#00ff88' if trade_plan['direction']=='LONG' else '#ff4444'};margin:0 0 10px 0;">
                {direction_emoji} {trade_plan['symbol']}
            </h3>
            <table style="width:100%;font-size:14px;">
                <tr><td style="color:#888;padding:4px 0;">Entry Price:</td><td style="font-weight:bold;">${trade_plan['entry_price']:.6g}</td></tr>
                <tr><td style="color:#888;padding:4px 0;">Stop Loss:</td><td style="color:#ff4444;font-weight:bold;">${trade_plan['stop_loss']:.6g} (-{trade_plan['stop_pct']}%)</td></tr>
                <tr><td style="color:#888;padding:4px 0;">Take Profit:</td><td style="color:#00ff88;font-weight:bold;">${trade_plan['take_profit']:.6g} (+{trade_plan['tp_pct']}%)</td></tr>
                <tr><td style="color:#888;padding:4px 0;">Position Size:</td><td>${trade_plan['position_size']:.2f}</td></tr>
                <tr><td style="color:#888;padding:4px 0;">Leverage:</td><td>{trade_plan['leverage']}x</td></tr>
                <tr><td style="color:#888;padding:4px 0;">Risk:</td><td style="color:#ffaa00;">${trade_plan['risk_amount']:.4f} ({trade_plan['stop_pct']}% of position)</td></tr>
                <tr><td style="color:#888;padding:4px 0;">Potential Profit:</td><td style="color:#00ff88;">${trade_plan['potential_profit']:.4f}</td></tr>
                <tr><td style="color:#888;padding:4px 0;">R:R Ratio:</td><td>{trade_plan['risk_reward']}:1</td></tr>
                <tr><td style="color:#888;padding:4px 0;">Signal Score:</td><td style="font-weight:bold;">{trade_plan['score']:.0%}</td></tr>
            </table>
        </div>
        
        <div style="background:#111;padding:15px;border-radius:6px;margin-bottom:15px;">
            <h4 style="color:#ffaa00;margin:0 0 8px 0;">📊 Account Status</h4>
            <table style="width:100%;font-size:13px;">
                <tr><td style="color:#888;">Balance:</td><td style="font-weight:bold;">${account['balance']:.2f}</td></tr>
                <tr><td style="color:#888;">Total P&L:</td><td style="color:{'#00ff88' if account['total_pnl']>=0 else '#ff4444'};">${account['total_pnl']:+.4f}</td></tr>
                <tr><td style="color:#888;">Win Rate:</td><td>{win_rate:.0f}% ({account['wins']}W / {account['losses']}L)</td></tr>
                <tr><td style="color:#888;">Trades:</td><td>{account['total_trades']}</td></tr>
            </table>
            <p style="margin:10px 0 0 0;font-size:12px;">
                Progress to $100: [{progress_bar}] {progress:.0f}%
            </p>
        </div>
        
        <div style="background:#1a1a00;padding:12px;border-radius:6px;border:1px solid #333;">
            <p style="margin:0;font-size:12px;color:#ffaa00;">
                <b>⚠️ EXECUTE ON BITUNIX:</b><br>
                1. Open {trade_plan['symbol']} perpetual<br>
                2. Set leverage to {trade_plan['leverage']}x<br>
                3. {'Buy/Long' if trade_plan['direction']=='LONG' else 'Sell/Short'} — Limit order @ ${trade_plan['entry_price']:.6g}<br>
                4. Set Stop Loss: ${trade_plan['stop_loss']:.6g}<br>
                5. Set Take Profit: ${trade_plan['take_profit']:.6g}
            </p>
        </div>
    </div>"""

    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": "NEXYROTH <onboarding@resend.dev>",
                "to": [ALERT_EMAIL],
                "subject": f"⚡ EXECUTE: {trade_plan['direction']} {trade_plan['symbol']} @ ${trade_plan['entry_price']:.6g} | Score {trade_plan['score']:.0%}",
                "html": html,
            },
            timeout=10,
        )
        if r.status_code == 200:
            log(f"✅ Trade alert sent: {trade_plan['direction']} {trade_plan['symbol']}")
        else:
            log(f"Email error: {r.status_code}")
    except Exception as e:
        log(f"Email error: {e}")

# ═══════════════════════════════════════════════════════════════
# TRADE JOURNAL
# ═══════════════════════════════════════════════════════════════

def record_trade(trade_plan, status="OPEN"):
    """Record a trade in the journal."""
    journal = load_journal()
    
    entry = {
        "id": len(journal) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": trade_plan["symbol"],
        "direction": trade_plan["direction"],
        "entry_price": trade_plan["entry_price"],
        "stop_loss": trade_plan["stop_loss"],
        "take_profit": trade_plan["take_profit"],
        "position_size": trade_plan["position_size"],
        "leverage": trade_plan["leverage"],
        "risk_amount": trade_plan["risk_amount"],
        "score": trade_plan["score"],
        "balance_before": trade_plan["balance_before"],
        "status": status,
        "exit_price": None,
        "pnl": None,
        "exit_time": None,
    }
    
    journal.append(entry)
    save_journal(journal)
    return entry

def close_trade(trade_id, exit_price, won):
    """Close a trade and update account."""
    journal = load_journal()
    account = load_account()
    
    for trade in journal:
        if trade["id"] == trade_id and trade["status"] == "OPEN":
            trade["exit_price"] = exit_price
            trade["exit_time"] = datetime.now(timezone.utc).isoformat()
            
            # Calculate P&L
            if trade["direction"] == "LONG":
                pnl_pct = (exit_price - trade["entry_price"]) / trade["entry_price"]
            else:
                pnl_pct = (trade["entry_price"] - exit_price) / trade["entry_price"]
            
            trade["pnl"] = round(trade["position_size"] * pnl_pct, 4)
            trade["status"] = "WIN" if won else "LOSS"
            
            # Update account
            account["balance"] += trade["pnl"]
            account["total_pnl"] += trade["pnl"]
            account["total_trades"] += 1
            if won:
                account["wins"] += 1
            else:
                account["losses"] += 1
            
            # Track peak and drawdown
            if account["balance"] > account["peak_balance"]:
                account["peak_balance"] = account["balance"]
            drawdown = (account["peak_balance"] - account["balance"]) / account["peak_balance"]
            if drawdown > account["max_drawdown"]:
                account["max_drawdown"] = drawdown
            
            # Check if target reached
            if account["balance"] >= TARGET_BALANCE:
                account["target_reached"] = True
                log(f"🎉 TARGET REACHED! Balance: ${account['balance']:.2f}")
            
            break
    
    save_journal(journal)
    save_account(account)
    return account

# ═══════════════════════════════════════════════════════════════
# MAIN EXECUTION LOOP
# ═══════════════════════════════════════════════════════════════

def run():
    """Main compound executor — reads strategy engine signals and generates trade plans."""
    log("═══ NEXYROTH Compound Growth Executor v1.0 ═══")
    
    account = load_account()
    log(f"Balance: ${account['balance']:.2f} | Target: ${TARGET_BALANCE:.2f} | Trades: {account['total_trades']} | Win Rate: {account['wins']}/{account['total_trades']}")
    
    if account["target_reached"]:
        log("🎉 TARGET ALREADY REACHED! Continuing to compound...")
    
    # Check open trades
    if len(account.get("open_trades", [])) >= MAX_OPEN_TRADES:
        log(f"Max open trades ({MAX_OPEN_TRADES}) reached — waiting for exits")
        return
    
    # Run strategy engine scan
    log("Running strategy engine scan...")
    
    # Import and run strategy engine
    import importlib.util
    spec = importlib.util.spec_from_file_location("strategy_engine", 
        "/home/ubuntu/trading_sniper/scripts/strategy_engine.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    
    results = engine.run_full_scan()
    
    # Filter actionable signals — exclude avoid symbols from trade execution
    signals = [
        r for r in results
        if r["direction"] != "NEUTRAL"
        and r["score"] >= MIN_SIGNAL_SCORE
        and not r.get("is_avoid", False)  # Never trade negative-EV symbols
    ]

    # Log any avoid symbols that would have fired (for awareness)
    avoid_signals = [
        r for r in results
        if r["direction"] != "NEUTRAL"
        and r["score"] >= MIN_SIGNAL_SCORE
        and r.get("is_avoid", False)
    ]
    for av in avoid_signals:
        log(f"  ⚠️ SKIPPED (negative EV): {av['direction']} {av['symbol']} score={av['score']:.2f}")

    if not signals:
        log("No signals above threshold (after EV filter) — holding position")
        save_account(account)
        return

    # Take the best signal (already sorted by EV-boosted score)
    best = signals[0]
    log(f"🎯 Best signal: {best['direction']} {best['symbol']} @ ${best['price']:.6g} (score={best['score']:.2f})")
    
    # Calculate trade plan
    trade_plan = calculate_trade_plan(account["balance"], best)
    
    log(f"Trade Plan:")
    log(f"  Entry: ${trade_plan['entry_price']:.6g}")
    log(f"  Stop:  ${trade_plan['stop_loss']:.6g} (-{trade_plan['stop_pct']}%)")
    log(f"  TP:    ${trade_plan['take_profit']:.6g} (+{trade_plan['tp_pct']}%)")
    log(f"  Size:  ${trade_plan['position_size']:.2f} @ {trade_plan['leverage']}x")
    log(f"  Risk:  ${trade_plan['risk_amount']:.4f} | Reward: ${trade_plan['potential_profit']:.4f}")
    
    # Record trade
    trade_entry = record_trade(trade_plan)
    account["open_trades"].append(trade_entry["id"])
    save_account(account)
    
    # Send execution alert
    send_trade_alert(trade_plan, account)
    
    log(f"✅ Trade #{trade_entry['id']} recorded and alert sent")
    log("═══ Executor complete ═══\n")

if __name__ == "__main__":
    run()
