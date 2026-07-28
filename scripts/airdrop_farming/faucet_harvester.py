#!/usr/bin/env python3
"""
NEXYROTH Airdrop Farming — Faucet Harvester
Automatically collects free SOL/ETH from faucets, reward programs, and micro-tasks.
Runs on cron to continuously try funding sources until wallets have enough gas.
"""
import os
import sys
import json
import time
import requests
import hashlib
from datetime import datetime, timedelta

# Configuration
WALLET_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_wallets/farming_wallets.json")
LOG_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_logs/faucet_harvest.log")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL_TO", "")

# Minimum balances needed for farming (very small - just gas)
MIN_SOL_BALANCE = 0.01   # ~$0.002 worth, enough for ~10 transactions
MIN_ETH_BALANCE = 0.0005  # ~$1.50 worth on Base, enough for ~50 transactions

def log(msg):
    """Log with timestamp."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + "\n")

def load_wallets():
    """Load wallet addresses from config."""
    if not os.path.exists(WALLET_FILE):
        log("ERROR: No wallet file found. Run wallet_generator.py first.")
        sys.exit(1)
    with open(WALLET_FILE, 'r') as f:
        return json.load(f)

def check_solana_balance(address):
    """Check SOL balance via public RPC."""
    try:
        resp = requests.post(
            "https://api.mainnet-beta.solana.com",
            json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
            timeout=10
        )
        data = resp.json()
        if "result" in data and "value" in data["result"]:
            lamports = data["result"]["value"]
            return lamports / 1e9  # Convert lamports to SOL
    except Exception as e:
        log(f"  Error checking SOL balance: {e}")
    return 0.0

def check_base_balance(address):
    """Check ETH balance on Base via public RPC."""
    try:
        resp = requests.post(
            "https://mainnet.base.org",
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "eth_getBalance",
                "params": [address, "latest"]
            },
            timeout=10
        )
        data = resp.json()
        if "result" in data:
            wei = int(data["result"], 16)
            return wei / 1e18  # Convert wei to ETH
    except Exception as e:
        log(f"  Error checking Base ETH balance: {e}")
    return 0.0

# ============================================================
# FAUCET SOURCES — Free crypto collection methods
# ============================================================

def try_solana_faucets(address):
    """Try various Solana faucets and reward programs."""
    results = []
    
    # 1. QuickNode Solana Faucet (gives small amounts for verification)
    try:
        resp = requests.post(
            "https://faucet.quicknode.com/solana/mainnet",
            json={"wallet_address": address},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("QuickNode Faucet", "SUCCESS", resp.text[:100]))
        else:
            results.append(("QuickNode Faucet", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("QuickNode Faucet", "ERROR", str(e)[:80]))
    
    # 2. SolFaucet (community faucet)
    try:
        resp = requests.post(
            "https://www.solfaucet.com/api/faucet",
            json={"address": address, "network": "mainnet"},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("SolFaucet", "SUCCESS", resp.text[:100]))
        else:
            results.append(("SolFaucet", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("SolFaucet", "ERROR", str(e)[:80]))
    
    # 3. Stakely Solana Faucet
    try:
        resp = requests.post(
            "https://stakely.io/en/faucet/solana-sol",
            json={"address": address},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("Stakely Faucet", "SUCCESS", resp.text[:100]))
        else:
            results.append(("Stakely Faucet", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("Stakely Faucet", "ERROR", str(e)[:80]))
    
    # 4. FaucetSOL
    try:
        resp = requests.get(
            f"https://faucetsol.com/api/claim?address={address}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("FaucetSOL", "SUCCESS", resp.text[:100]))
        else:
            results.append(("FaucetSOL", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("FaucetSOL", "ERROR", str(e)[:80]))
    
    return results

def try_base_faucets(address):
    """Try various Base/ETH faucets."""
    results = []
    
    # 1. Coinbase Base Faucet (for verified Coinbase users)
    try:
        resp = requests.post(
            "https://faucet.base.org/api/claim",
            json={"address": address},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("Base Official Faucet", "SUCCESS", resp.text[:100]))
        else:
            results.append(("Base Official Faucet", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("Base Official Faucet", "ERROR", str(e)[:80]))
    
    # 2. Alchemy Base Faucet
    try:
        resp = requests.post(
            "https://www.alchemy.com/faucets/base-mainnet",
            json={"address": address},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("Alchemy Faucet", "SUCCESS", resp.text[:100]))
        else:
            results.append(("Alchemy Faucet", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("Alchemy Faucet", "ERROR", str(e)[:80]))
    
    # 3. Bware Labs Faucet
    try:
        resp = requests.post(
            "https://faucet.bwarelabs.com/api/faucet",
            json={"address": address, "chain": "base"},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("Bware Faucet", "SUCCESS", resp.text[:100]))
        else:
            results.append(("Bware Faucet", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("Bware Faucet", "ERROR", str(e)[:80]))
    
    # 4. Superchain Faucet (Optimism ecosystem, includes Base)
    try:
        resp = requests.post(
            "https://app.optimism.io/faucet",
            json={"address": address, "chain_id": 8453},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("Superchain Faucet", "SUCCESS", resp.text[:100]))
        else:
            results.append(("Superchain Faucet", "FAILED", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("Superchain Faucet", "ERROR", str(e)[:80]))
    
    return results

def try_layer3_quests(sol_address, evm_address):
    """Check Layer3 for zero-cost quests that reward crypto."""
    results = []
    try:
        # Layer3 API - check available quests with crypto rewards
        resp = requests.get(
            "https://api.layer3.xyz/v1/quests?status=active&reward_type=token",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            quest_count = len(data.get("quests", data.get("data", [])))
            results.append(("Layer3 Quests", "FOUND", f"{quest_count} active token-reward quests"))
        else:
            results.append(("Layer3 Quests", "UNAVAILABLE", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("Layer3 Quests", "ERROR", str(e)[:80]))
    return results

def try_galxe_campaigns(evm_address):
    """Check Galxe for campaigns with token rewards."""
    results = []
    try:
        resp = requests.get(
            "https://graphigo.prd.galaxy.eco/query",
            params={"query": "{ campaigns(input: {forAdmin: false, first: 10, status: Active}) { list { name rewardType } } }"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )
        if resp.status_code == 200:
            results.append(("Galxe Campaigns", "CHECKED", "Active campaigns found"))
        else:
            results.append(("Galxe Campaigns", "UNAVAILABLE", f"HTTP {resp.status_code}"))
    except Exception as e:
        results.append(("Galxe Campaigns", "ERROR", str(e)[:80]))
    return results

def send_funding_alert(sol_balance, eth_balance, sol_address, evm_address, faucet_results):
    """Send email alert with wallet status and funding instructions."""
    funded_sol = sol_balance >= MIN_SOL_BALANCE
    funded_eth = eth_balance >= MIN_ETH_BALANCE
    
    if funded_sol and funded_eth:
        subject = "🟢 NEXYROTH Airdrop Farm — Wallets FUNDED, Farming Active!"
        status_msg = "Both wallets are funded. Airdrop farming is now ACTIVE."
    elif funded_sol or funded_eth:
        subject = "🟡 NEXYROTH Airdrop Farm — Partially Funded"
        status_msg = f"{'Solana' if funded_sol else 'Base'} wallet funded. Still need {'Base ETH' if funded_sol else 'SOL'}."
    else:
        subject = "⚪ NEXYROTH Airdrop Farm — Awaiting Funds"
        status_msg = "Wallets generated. Attempting auto-funding via faucets."
    
    faucet_html = ""
    for source, status, detail in faucet_results:
        color = "#00ff88" if status == "SUCCESS" else "#ff6b6b" if status in ("FAILED", "ERROR") else "#ffd700"
        faucet_html += f'<tr><td style="color:#ccc">{source}</td><td style="color:{color}">{status}</td><td style="color:#888;font-size:11px">{detail}</td></tr>'
    
    html = f"""
    <div style="font-family:'Courier New',monospace;background:#0a0a1a;color:#e0e0e0;padding:24px;border-radius:12px;max-width:600px">
        <h2 style="color:#a855f7;margin:0 0 16px">🌀 NEXYROTH Airdrop Farm</h2>
        <p style="color:#22d3ee;font-size:14px">{status_msg}</p>
        
        <div style="background:#111;padding:16px;border-radius:8px;margin:16px 0;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px">Wallet Balances</h3>
            <table style="width:100%;font-size:13px">
                <tr><td style="color:#888">Solana</td><td style="color:{'#00ff88' if funded_sol else '#ff6b6b'}">{sol_balance:.6f} SOL {'✅' if funded_sol else '❌'}</td></tr>
                <tr><td style="color:#888">Base ETH</td><td style="color:{'#00ff88' if funded_eth else '#ff6b6b'}">{eth_balance:.8f} ETH {'✅' if funded_eth else '❌'}</td></tr>
            </table>
        </div>
        
        <div style="background:#111;padding:16px;border-radius:8px;margin:16px 0;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px">Wallet Addresses</h3>
            <p style="font-size:11px;color:#888;word-break:break-all">
                <strong style="color:#22d3ee">SOL:</strong> {sol_address}<br>
                <strong style="color:#22d3ee">EVM:</strong> {evm_address}
            </p>
        </div>
        
        <div style="background:#111;padding:16px;border-radius:8px;margin:16px 0;border:1px solid #333">
            <h3 style="color:#a855f7;margin:0 0 8px">Faucet Harvest Results</h3>
            <table style="width:100%;font-size:12px">
                {faucet_html}
            </table>
        </div>
        
        {'<div style="background:#1a0a2e;padding:12px;border-radius:8px;border:1px solid #a855f7"><p style="color:#ffd700;margin:0;font-size:12px">⚡ Manual funding (fastest): Send 0.02 SOL + 0.001 ETH on Base to addresses above. Total cost: ~$3-5</p></div>' if not (funded_sol and funded_eth) else '<div style="background:#0a2e1a;padding:12px;border-radius:8px;border:1px solid #00ff88"><p style="color:#00ff88;margin:0;font-size:12px">✅ Farming scripts are running! Check daily digest for activity reports.</p></div>'}
        
        <p style="color:#555;font-size:10px;margin-top:16px">NEXYROTH Airdrop Farm • Auto-runs every 6 hours • {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
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
            log(f"  📧 Alert email sent: {subject}")
        else:
            log(f"  ⚠️ Email failed: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        log(f"  ⚠️ Email error: {e}")

def main():
    log("=" * 60)
    log("NEXYROTH Faucet Harvester — Starting")
    log("=" * 60)
    
    wallets = load_wallets()
    sol_address = wallets["wallets"]["solana"]["address"]
    evm_address = wallets["wallets"]["evm"]["address"]
    
    log(f"  SOL wallet: {sol_address}")
    log(f"  EVM wallet: {evm_address}")
    
    # Check current balances
    sol_balance = check_solana_balance(sol_address)
    eth_balance = check_base_balance(evm_address)
    
    log(f"  SOL balance: {sol_balance:.6f} SOL (need {MIN_SOL_BALANCE})")
    log(f"  Base ETH balance: {eth_balance:.8f} ETH (need {MIN_ETH_BALANCE})")
    
    all_results = []
    
    # If SOL balance is insufficient, try faucets
    if sol_balance < MIN_SOL_BALANCE:
        log("  🔄 Attempting Solana faucets...")
        results = try_solana_faucets(sol_address)
        all_results.extend(results)
        for source, status, detail in results:
            log(f"    {source}: {status} — {detail}")
    else:
        log("  ✅ Solana wallet funded!")
        all_results.append(("Solana Balance", "FUNDED", f"{sol_balance:.6f} SOL"))
    
    # If ETH balance is insufficient, try faucets
    if eth_balance < MIN_ETH_BALANCE:
        log("  🔄 Attempting Base ETH faucets...")
        results = try_base_faucets(evm_address)
        all_results.extend(results)
        for source, status, detail in results:
            log(f"    {source}: {status} — {detail}")
    else:
        log("  ✅ Base wallet funded!")
        all_results.append(("Base ETH Balance", "FUNDED", f"{eth_balance:.8f} ETH"))
    
    # Try quest/campaign platforms for free rewards
    log("  🔄 Checking reward platforms...")
    quest_results = try_layer3_quests(sol_address, evm_address)
    galxe_results = try_galxe_campaigns(evm_address)
    all_results.extend(quest_results)
    all_results.extend(galxe_results)
    
    # Send status email
    send_funding_alert(sol_balance, eth_balance, sol_address, evm_address, all_results)
    
    # Re-check balances after faucet attempts
    time.sleep(5)
    new_sol = check_solana_balance(sol_address)
    new_eth = check_base_balance(evm_address)
    
    if new_sol > sol_balance or new_eth > eth_balance:
        log(f"  🎉 Balance increased! SOL: {sol_balance:.6f}→{new_sol:.6f}, ETH: {eth_balance:.8f}→{new_eth:.8f}")
    
    # Save harvest state
    state_file = os.path.expanduser("~/trading_sniper/data/airdrop_logs/harvest_state.json")
    state = {
        "last_run": datetime.utcnow().isoformat(),
        "sol_balance": new_sol,
        "eth_balance": new_eth,
        "sol_funded": new_sol >= MIN_SOL_BALANCE,
        "eth_funded": new_eth >= MIN_ETH_BALANCE,
        "farming_active": new_sol >= MIN_SOL_BALANCE or new_eth >= MIN_ETH_BALANCE,
        "total_faucet_attempts": len(all_results),
        "successful_claims": sum(1 for _, s, _ in all_results if s == "SUCCESS")
    }
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
    
    log(f"  State saved. Farming active: {state['farming_active']}")
    log("=" * 60)

if __name__ == "__main__":
    main()
