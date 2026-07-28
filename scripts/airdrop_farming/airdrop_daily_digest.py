#!/usr/bin/env python3
"""
NEXYROTH Airdrop Farming — Daily Digest
Sends a comprehensive daily email summarizing farming activity,
wallet balances, protocols interacted with, and estimated airdrop eligibility.
Runs at 11:55 PM EDT via cron.
"""
import os
import sys
import json
import requests
from datetime import datetime, timedelta

# Configuration
WALLET_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_wallets/farming_wallets.json")
STATE_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_logs/farming_state.json")
LOG_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_logs/farming_activity.log")
HARVEST_STATE = os.path.expanduser("~/trading_sniper/data/airdrop_logs/harvest_state.json")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL_TO", "")

# Solana RPC
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
BASE_RPC = "https://mainnet.base.org"

# Airdrop target info
AIRDROP_TARGETS = {
    "Base": {"est_value": "$500-5,000", "status": "Token exploration phase", "chain": "base", "criteria": "Bridge, swap, LP, use Base App"},
    "Hyperliquid S2": {"est_value": "$1,000-20,000", "status": "38.8% supply in community wallet", "chain": "hyperevm", "criteria": "Trade volume, HyperEVM DeFi"},
    "Bulk Trade": {"est_value": "$200-2,000", "status": "CONFIRMED 30% supply", "chain": "solana", "criteria": "Deposit/trade on Solana perps"},
    "Hylo": {"est_value": "$100-1,000", "status": "CONFIRMED airdrop", "chain": "solana", "criteria": "Farm XP, use hyUSD"},
    "Jupiter": {"est_value": "$50-500", "status": "Ongoing rewards", "chain": "solana", "criteria": "Trade volume on Jupiter"},
    "Avantis S3": {"est_value": "$100-1,000", "status": "Season 3 active", "chain": "base", "criteria": "Trade with leverage on Base"},
    "Paradex": {"est_value": "$200-3,000", "status": "Points program live", "chain": "ethereum", "criteria": "Zero-fee perps trading"},
    "Ethereal": {"est_value": "$100-2,000", "status": "Season Zero active", "chain": "ethereum", "criteria": "DEX usage, USDe interactions"},
}

def get_solana_balance(address):
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]
        }, timeout=10)
        return resp.json()["result"]["value"] / 1e9
    except:
        return 0.0

def get_base_balance(address):
    try:
        resp = requests.post(BASE_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]
        }, timeout=10)
        return int(resp.json()["result"], 16) / 1e18
    except:
        return 0.0

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def get_today_interactions(state):
    """Get interactions from the last 24 hours."""
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    interactions = state.get("interactions", [])
    return [ix for ix in interactions if ix.get("timestamp", "") > cutoff]

def estimate_eligibility(state):
    """Estimate airdrop eligibility based on activity."""
    total_txs = state.get("total_txs", 0)
    protocols = state.get("protocols_touched", [])
    
    eligibility = {}
    for name, info in AIRDROP_TARGETS.items():
        chain = info["chain"]
        score = 0
        
        # Base scoring
        if chain == "solana":
            if "Jupiter" in protocols or "Solana" in protocols:
                score += 30
            if total_txs > 10:
                score += 20
            if total_txs > 50:
                score += 20
            if total_txs > 100:
                score += 30
        elif chain == "base":
            if "Base" in protocols or "WETH" in protocols:
                score += 30
            if total_txs > 10:
                score += 20
            if total_txs > 50:
                score += 20
            if total_txs > 100:
                score += 30
        elif chain in ("hyperevm", "ethereum"):
            score = 10  # Minimal until we add HyperEVM interactions
        
        eligibility[name] = min(score, 100)
    
    return eligibility

def send_digest():
    """Compile and send the daily digest email."""
    # Load data
    wallets = load_json(WALLET_FILE)
    state = load_json(STATE_FILE)
    harvest = load_json(HARVEST_STATE)
    
    if not wallets:
        print("No wallets found. Skipping digest.")
        return
    
    sol_address = wallets.get("wallets", {}).get("solana", {}).get("address", "N/A")
    evm_address = wallets.get("wallets", {}).get("evm", {}).get("address", "N/A")
    
    # Get balances
    sol_balance = get_solana_balance(sol_address) if sol_address != "N/A" else 0
    base_balance = get_base_balance(evm_address) if evm_address != "N/A" else 0
    
    # Get today's activity
    today_interactions = get_today_interactions(state)
    total_txs = state.get("total_txs", 0)
    protocols = state.get("protocols_touched", [])
    
    # Estimate eligibility
    eligibility = estimate_eligibility(state)
    
    # Calculate total estimated value
    farming_active = sol_balance >= 0.005 or base_balance >= 0.0003
    
    # Build email HTML
    # Protocol eligibility rows
    eligibility_rows = ""
    total_min_value = 0
    total_max_value = 0
    for name, info in AIRDROP_TARGETS.items():
        score = eligibility.get(name, 0)
        est = info["est_value"]
        status = info["status"]
        
        # Parse value range
        try:
            parts = est.replace("$", "").replace(",", "").split("-")
            min_val = int(parts[0])
            max_val = int(parts[1]) if len(parts) > 1 else min_val
            weighted_min = int(min_val * score / 100)
            weighted_max = int(max_val * score / 100)
            total_min_value += weighted_min
            total_max_value += weighted_max
        except:
            weighted_min = 0
            weighted_max = 0
        
        bar_width = score
        bar_color = "#00ff88" if score >= 60 else "#ffd700" if score >= 30 else "#ff6b6b"
        
        eligibility_rows += f"""
        <tr>
            <td style="color:#e0e0e0;padding:4px 8px;font-size:12px">{name}</td>
            <td style="padding:4px 8px">
                <div style="background:#222;border-radius:4px;height:14px;width:100px;display:inline-block;vertical-align:middle">
                    <div style="background:{bar_color};height:14px;border-radius:4px;width:{bar_width}px"></div>
                </div>
                <span style="color:{bar_color};font-size:11px;margin-left:4px">{score}%</span>
            </td>
            <td style="color:#888;padding:4px 8px;font-size:11px">{est}</td>
            <td style="color:#666;padding:4px 8px;font-size:10px">{status}</td>
        </tr>"""
    
    # Today's interaction log
    interaction_rows = ""
    for ix in today_interactions[-10:]:  # Last 10
        ts = ix.get("timestamp", "")[:16]
        protocol = ix.get("protocol", "?")
        action = ix.get("action", "?")
        chain = ix.get("chain", "?")
        tx = ix.get("tx", "")[:12] + "..."
        interaction_rows += f"""
        <tr>
            <td style="color:#888;font-size:10px;padding:2px 6px">{ts}</td>
            <td style="color:#22d3ee;font-size:11px;padding:2px 6px">{protocol}</td>
            <td style="color:#ccc;font-size:11px;padding:2px 6px">{action}</td>
            <td style="color:#555;font-size:10px;padding:2px 6px">{tx}</td>
        </tr>"""
    
    if not interaction_rows:
        interaction_rows = '<tr><td colspan="4" style="color:#666;font-size:11px;padding:8px;text-align:center">No interactions today — wallets need funding</td></tr>'
    
    subject = f"🌀 NEXYROTH Airdrop Farm — Day {total_txs} TXs | {'ACTIVE' if farming_active else 'PAUSED'}"
    
    html = f"""
    <div style="font-family:'Courier New',monospace;background:#0a0a1a;color:#e0e0e0;padding:24px;border-radius:12px;max-width:700px">
        <h2 style="color:#a855f7;margin:0 0 4px">🌀 NEXYROTH Airdrop Farm</h2>
        <p style="color:#555;font-size:11px;margin:0 0 16px">Daily Digest — {datetime.utcnow().strftime("%B %d, %Y")}</p>
        
        <div style="display:flex;gap:12px;margin-bottom:16px">
            <div style="background:#111;padding:12px;border-radius:8px;flex:1;border:1px solid #333">
                <div style="color:#888;font-size:10px">STATUS</div>
                <div style="color:{'#00ff88' if farming_active else '#ff6b6b'};font-size:16px;font-weight:bold">{'🟢 ACTIVE' if farming_active else '🔴 PAUSED'}</div>
            </div>
            <div style="background:#111;padding:12px;border-radius:8px;flex:1;border:1px solid #333">
                <div style="color:#888;font-size:10px">TOTAL TXs</div>
                <div style="color:#22d3ee;font-size:16px;font-weight:bold">{total_txs}</div>
            </div>
            <div style="background:#111;padding:12px;border-radius:8px;flex:1;border:1px solid #333">
                <div style="color:#888;font-size:10px">TODAY</div>
                <div style="color:#ffd700;font-size:16px;font-weight:bold">{len(today_interactions)} TXs</div>
            </div>
            <div style="background:#111;padding:12px;border-radius:8px;flex:1;border:1px solid #333">
                <div style="color:#888;font-size:10px">EST. VALUE</div>
                <div style="color:#00ff88;font-size:16px;font-weight:bold">${total_min_value:,}-${total_max_value:,}</div>
            </div>
        </div>
        
        <div style="background:#111;padding:16px;border-radius:8px;margin-bottom:16px;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px;font-size:13px">💰 Wallet Balances</h3>
            <table style="width:100%;font-size:12px">
                <tr>
                    <td style="color:#888">Solana</td>
                    <td style="color:{'#00ff88' if sol_balance >= 0.005 else '#ff6b6b'}">{sol_balance:.6f} SOL</td>
                    <td style="color:#555;font-size:10px;word-break:break-all">{sol_address[:20]}...</td>
                </tr>
                <tr>
                    <td style="color:#888">Base ETH</td>
                    <td style="color:{'#00ff88' if base_balance >= 0.0003 else '#ff6b6b'}">{base_balance:.8f} ETH</td>
                    <td style="color:#555;font-size:10px;word-break:break-all">{evm_address[:20]}...</td>
                </tr>
            </table>
        </div>
        
        <div style="background:#111;padding:16px;border-radius:8px;margin-bottom:16px;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px;font-size:13px">🎯 Airdrop Eligibility Tracker</h3>
            <table style="width:100%">
                <tr style="border-bottom:1px solid #333">
                    <th style="color:#555;font-size:10px;text-align:left;padding:4px 8px">Protocol</th>
                    <th style="color:#555;font-size:10px;text-align:left;padding:4px 8px">Progress</th>
                    <th style="color:#555;font-size:10px;text-align:left;padding:4px 8px">Est. Value</th>
                    <th style="color:#555;font-size:10px;text-align:left;padding:4px 8px">Status</th>
                </tr>
                {eligibility_rows}
            </table>
        </div>
        
        <div style="background:#111;padding:16px;border-radius:8px;margin-bottom:16px;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px;font-size:13px">📋 Today's Activity</h3>
            <table style="width:100%">
                {interaction_rows}
            </table>
        </div>
        
        <div style="background:#111;padding:12px;border-radius:8px;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px;font-size:13px">🔧 Protocols Touched</h3>
            <p style="color:#22d3ee;font-size:12px;margin:0">{', '.join(protocols) if protocols else 'None yet — waiting for funding'}</p>
        </div>
        
        {'<div style="background:#1a0a2e;padding:12px;border-radius:8px;margin-top:16px;border:1px solid #a855f7"><p style="color:#ffd700;margin:0;font-size:11px">⚡ Fund wallets to activate farming: Send 0.02 SOL + 0.001 ETH (Base) to addresses above. Faucet harvester running every 6h.</p></div>' if not farming_active else ''}
        
        <p style="color:#444;font-size:9px;margin-top:16px">NEXYROTH Airdrop Farm • Cron: every 4h farming + daily digest • {datetime.utcnow().strftime("%H:%M UTC")}</p>
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
            print(f"✅ Daily digest sent: {subject}")
        else:
            print(f"❌ Email failed: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        print(f"❌ Email error: {e}")

if __name__ == "__main__":
    send_digest()
