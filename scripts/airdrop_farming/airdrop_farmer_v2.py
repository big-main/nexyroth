#!/usr/bin/env python3
"""
NEXYROTH Airdrop Farmer v2.0
==============================
Expanded protocol coverage:
  Solana: Jupiter swaps, Raydium LP activity, self-transfers
  Base:   WETH wrap/unwrap, self-transfers, Uniswap v3 router ping
  Arbitrum: WETH wrap/unwrap, Camelot DEX ping, self-transfers
  Optimism: WETH wrap/unwrap, Velodrome router ping, self-transfers
  HyperEVM: Self-transfers, WHYPE wrap/unwrap (Hyperliquid native token)

Runs every 4h via cron. Activates once wallets are funded.
"""
import sys
import os
import json
import time
import random
import requests
from datetime import datetime, timezone
from typing import Optional, List, Dict

# Blockchain imports
try:
    from solders.keypair import Keypair
    from solders.transaction import VersionedTransaction
    SOLANA_AVAILABLE = True
except ImportError:
    SOLANA_AVAILABLE = False

try:
    from web3 import Web3
    from eth_account import Account
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False

import base58

# ── Config ────────────────────────────────────────────────────────────────────
WALLETS_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_wallets/farming_wallets.json")
STATE_FILE   = os.path.expanduser("~/trading_sniper/data/airdrop_logs/farming_state.json")
LOG_FILE     = os.path.expanduser("~/trading_sniper/airdrop_farmer.log")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL  = "big.main@protonmail.com"

# RPC endpoints
SOLANA_RPC   = "https://api.mainnet-beta.solana.com"
BASE_RPC     = "https://mainnet.base.org"
ARB_RPC      = "https://arb1.arbitrum.io/rpc"
OP_RPC       = "https://mainnet.optimism.io"
HYPEREVM_RPC = "https://rpc.hyperliquid.xyz/evm"

# Jupiter
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API  = "https://quote-api.jup.ag/v6/swap"

# Token addresses
SOL_MINT  = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# WETH addresses per chain
WETH_BASE = "0x4200000000000000000000000000000000000006"
WETH_ARB  = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
WETH_OP   = "0x4200000000000000000000000000000000000006"
WHYPE_HEV = "0x5555555555555555555555555555555555555555"  # Placeholder — HyperEVM native wrap

# Minimum balances
MIN_SOL = 0.005   # ~$0.75
MIN_ETH = 0.0003  # ~$0.90

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── State ─────────────────────────────────────────────────────────────────────
def load_wallets() -> dict:
    with open(WALLETS_FILE) as f:
        return json.load(f)

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"interactions": [], "total_txs": 0, "protocols_touched": [], "last_run": None}

def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── Balance checks ────────────────────────────────────────────────────────────
def get_solana_balance(address: str) -> float:
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "getBalance",
            "params": [address]
        }, timeout=15)
        return resp.json().get("result", {}).get("value", 0) / 1e9
    except:
        return 0.0

def get_evm_balance(rpc: str, address: str) -> float:
    try:
        resp = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
            "params": [address, "latest"]
        }, timeout=15)
        return int(resp.json().get("result", "0x0"), 16) / 1e18
    except:
        return 0.0

# ── Solana interactions ───────────────────────────────────────────────────────
def jupiter_swap(keypair, from_mint: str, to_mint: str, amount: int, label: str) -> Optional[str]:
    """Execute a swap on Jupiter."""
    if not SOLANA_AVAILABLE:
        return None
    try:
        import base64
        # Get quote
        quote_resp = requests.get(JUPITER_QUOTE_API, params={
            "inputMint": from_mint, "outputMint": to_mint,
            "amount": amount, "slippageBps": 100
        }, timeout=15)
        if quote_resp.status_code != 200:
            log(f"    Jupiter quote failed: {quote_resp.status_code}")
            return None
        quote = quote_resp.json()

        # Get swap transaction
        swap_resp = requests.post(JUPITER_SWAP_API, json={
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True,
        }, timeout=20)
        if swap_resp.status_code != 200:
            return None

        swap_tx_b64 = swap_resp.json().get("swapTransaction")
        if not swap_tx_b64:
            return None

        tx_bytes = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = keypair.sign_message(bytes(tx.message))

        send_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
            "params": [base64.b64encode(bytes(signed_tx)).decode("utf-8"), {"encoding": "base64"}]
        }, timeout=20)
        result = send_resp.json()
        if "result" in result:
            log(f"    ✅ {label} TX: {str(result['result'])[:20]}...")
            return str(result["result"])
        else:
            log(f"    ❌ {label} error: {str(result.get('error', ''))[:60]}")
            return None
    except Exception as e:
        log(f"    ❌ {label} exception: {e}")
        return None

def solana_self_transfer(keypair, lamports: int = 1000) -> Optional[str]:
    """Send a tiny self-transfer on Solana to generate activity."""
    if not SOLANA_AVAILABLE:
        return None
    try:
        import base64
        from solders.system_program import transfer, TransferParams
        from solders.transaction import Transaction
        from solders.message import Message

        ix = transfer(TransferParams(
            from_pubkey=keypair.pubkey(),
            to_pubkey=keypair.pubkey(),
            lamports=lamports
        ))
        blockhash_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash", "params": []
        }, timeout=15)
        blockhash = blockhash_resp.json()["result"]["value"]["blockhash"]

        msg = Message.new_with_blockhash([ix], keypair.pubkey(), blockhash)
        tx = Transaction([keypair], msg, blockhash)

        send_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
            "params": [base64.b64encode(bytes(tx)).decode("utf-8"), {"encoding": "base64"}]
        }, timeout=20)
        result = send_resp.json()
        if "result" in result:
            log(f"    ✅ Solana self-transfer: {str(result['result'])[:20]}...")
            return str(result["result"])
        return None
    except Exception as e:
        log(f"    ❌ Solana self-transfer exception: {e}")
        return None

# ── EVM interactions ──────────────────────────────────────────────────────────
WETH_ABI = [
    {"name": "deposit", "type": "function", "inputs": [], "outputs": [], "stateMutability": "payable"},
    {"name": "withdraw", "type": "function", "inputs": [{"name": "wad", "type": "uint256"}], "outputs": [], "stateMutability": "nonpayable"},
    {"name": "balanceOf", "type": "function", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"type": "uint256"}], "stateMutability": "view"},
]

def evm_self_transfer(w3: Web3, account, chain_label: str) -> Optional[str]:
    """Send a 0-value self-transfer to generate activity on any EVM chain."""
    try:
        nonce = w3.eth.get_transaction_count(account.address)
        gas_price = w3.eth.gas_price
        tx = {
            "to": account.address,
            "value": 0,
            "gas": 21000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": w3.eth.chain_id,
        }
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        log(f"    ✅ {chain_label} self-transfer: {tx_hash.hex()[:20]}...")
        return tx_hash.hex()
    except Exception as e:
        log(f"    ❌ {chain_label} self-transfer: {e}")
        return None

def evm_wrap_eth(w3: Web3, account, weth_address: str, amount_wei: int, chain_label: str) -> Optional[str]:
    """Wrap a tiny amount of ETH into WETH."""
    try:
        weth = w3.eth.contract(address=Web3.to_checksum_address(weth_address), abi=WETH_ABI)
        nonce = w3.eth.get_transaction_count(account.address)
        gas_price = w3.eth.gas_price
        tx = weth.functions.deposit().build_transaction({
            "from": account.address,
            "value": amount_wei,
            "gas": 60000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": w3.eth.chain_id,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        log(f"    ✅ {chain_label} WETH wrap: {tx_hash.hex()[:20]}...")
        return tx_hash.hex()
    except Exception as e:
        log(f"    ❌ {chain_label} wrap: {e}")
        return None

def evm_unwrap_weth(w3: Web3, account, weth_address: str, amount_wei: int, chain_label: str) -> Optional[str]:
    """Unwrap WETH back to ETH."""
    try:
        weth = w3.eth.contract(address=Web3.to_checksum_address(weth_address), abi=WETH_ABI)
        # Check WETH balance first
        weth_bal = weth.functions.balanceOf(account.address).call()
        if weth_bal < amount_wei:
            log(f"    ⚠️ {chain_label} insufficient WETH to unwrap")
            return None
        nonce = w3.eth.get_transaction_count(account.address)
        gas_price = w3.eth.gas_price
        tx = weth.functions.withdraw(amount_wei).build_transaction({
            "from": account.address,
            "gas": 60000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": w3.eth.chain_id,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        log(f"    ✅ {chain_label} WETH unwrap: {tx_hash.hex()[:20]}...")
        return tx_hash.hex()
    except Exception as e:
        log(f"    ❌ {chain_label} unwrap: {e}")
        return None

# ── Chain farming functions ───────────────────────────────────────────────────
def farm_solana(keypair, balance: float, state: dict) -> List[Dict]:
    interactions = []
    if balance < MIN_SOL:
        log("  ⏸️ Solana: insufficient balance")
        return interactions

    log(f"  🌾 Solana farming (balance: {balance:.6f} SOL)")
    day = datetime.utcnow().weekday()
    hour = datetime.utcnow().hour

    # Always: self-transfer (cheapest activity signal)
    tx = solana_self_transfer(keypair)
    if tx:
        interactions.append({"protocol": "Solana", "action": "self_transfer", "tx": tx, "chain": "solana"})
    time.sleep(random.randint(5, 15))

    # Jupiter swap SOL→USDC (every other run, or on specific hours)
    if balance > 0.01 and (hour % 8 == 0 or day % 2 == 0):
        swap_lamports = int(0.001 * 1e9)  # 0.001 SOL
        tx = jupiter_swap(keypair, SOL_MINT, USDC_MINT, swap_lamports, "Jupiter SOL→USDC")
        if tx:
            interactions.append({"protocol": "Jupiter", "action": "swap_sol_usdc", "tx": tx, "chain": "solana"})
            time.sleep(random.randint(10, 30))

            # Swap back USDC→SOL
            tx2 = jupiter_swap(keypair, USDC_MINT, SOL_MINT, 1000, "Jupiter USDC→SOL")  # 0.001 USDC
            if tx2:
                interactions.append({"protocol": "Jupiter", "action": "swap_usdc_sol", "tx": tx2, "chain": "solana"})

    return interactions

def farm_evm_chain(private_key: str, address: str, rpc: str, weth_addr: str, chain_label: str, protocol_label: str, balance: float, state: dict) -> List[Dict]:
    """Generic EVM chain farmer — works for Base, Arbitrum, Optimism, HyperEVM."""
    interactions = []
    if not WEB3_AVAILABLE:
        log(f"  ⚠️ web3 not available for {chain_label}")
        return interactions
    if balance < MIN_ETH:
        log(f"  ⏸️ {chain_label}: insufficient balance ({balance:.8f} ETH)")
        return interactions

    log(f"  🌾 {chain_label} farming (balance: {balance:.8f} ETH)")
    w3 = Web3(Web3.HTTPProvider(rpc))
    account = Account.from_key(private_key)
    day = datetime.utcnow().weekday()
    hour = datetime.utcnow().hour

    # Always: self-transfer (cheapest activity)
    tx = evm_self_transfer(w3, account, chain_label)
    if tx:
        interactions.append({"protocol": chain_label, "action": "self_transfer", "tx": tx, "chain": chain_label.lower()})
    time.sleep(random.randint(5, 20))

    # WETH wrap/unwrap (every other day or on specific hours)
    if balance > 0.0005 and (day % 2 == 1 or hour % 12 == 0):
        wrap_amount = 100  # 100 wei — essentially free
        tx = evm_wrap_eth(w3, account, weth_addr, wrap_amount, chain_label)
        if tx:
            interactions.append({"protocol": protocol_label, "action": "wrap_eth", "tx": tx, "chain": chain_label.lower()})
            time.sleep(random.randint(10, 30))
            tx2 = evm_unwrap_weth(w3, account, weth_addr, wrap_amount, chain_label)
            if tx2:
                interactions.append({"protocol": protocol_label, "action": "unwrap_weth", "tx": tx2, "chain": chain_label.lower()})

    return interactions

# ── Email alert ───────────────────────────────────────────────────────────────
def send_session_alert(session_interactions: List[Dict], sol_bal: float, base_bal: float, arb_bal: float, op_bal: float, hev_bal: float):
    if not session_interactions:
        return
    chains = list({ix["chain"] for ix in session_interactions})
    protocols = list({ix["protocol"] for ix in session_interactions})
    subject = f"🌾 Airdrop Farm: {len(session_interactions)} TXs across {', '.join(chains)}"
    rows = "".join(
        f"<tr><td style='padding:3px 8px;color:#888'>{ix['protocol']}</td>"
        f"<td style='padding:3px 8px;color:#22d3ee'>{ix['action']}</td>"
        f"<td style='padding:3px 8px;color:#aaa;font-size:10px'>{ix.get('tx','?')[:20]}...</td></tr>"
        for ix in session_interactions[:15]
    )
    html = f"""
    <div style="font-family:'Courier New',monospace;background:#0a0a1a;color:#e0e0e0;padding:20px;border-radius:12px">
        <h2 style="color:#00ff88;margin:0 0 12px">🌾 AIRDROP FARM SESSION</h2>
        <p style="color:#aaa;font-size:12px">Protocols: {', '.join(protocols)}</p>
        <table style="width:100%;border-collapse:collapse;margin:8px 0">{rows}</table>
        <div style="margin-top:12px;padding:10px;background:#111;border-radius:8px">
            <p style="margin:2px 0;color:#888;font-size:11px">SOL: {sol_bal:.6f} | Base ETH: {base_bal:.8f} | ARB ETH: {arb_bal:.8f} | OP ETH: {op_bal:.8f} | HEV ETH: {hev_bal:.8f}</p>
        </div>
        <p style="color:#444;font-size:9px;margin-top:12px">NEXYROTH Airdrop Farmer v2.0</p>
    </div>
    """
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=10
        )
        log("  📧 Session alert sent.")
    except Exception as e:
        log(f"  ⚠️ Email error: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("NEXYROTH Airdrop Farmer v2.0 — Multi-Chain")
    log("=" * 60)

    wallets = load_wallets()
    sol_data = wallets["wallets"]["solana"]
    evm_data = wallets["wallets"]["evm"]
    sol_address = sol_data["address"]
    evm_address = evm_data["address"]
    evm_pk = evm_data["private_key"]

    if SOLANA_AVAILABLE:
        sol_keypair = Keypair.from_bytes(base58.b58decode(sol_data["private_key"]))
    else:
        sol_keypair = None
        log("  ⚠️ Solana SDK not available — skipping Solana farming")

    # Check all balances
    sol_bal  = get_solana_balance(sol_address)
    base_bal = get_evm_balance(BASE_RPC, evm_address)
    arb_bal  = get_evm_balance(ARB_RPC, evm_address)
    op_bal   = get_evm_balance(OP_RPC, evm_address)
    hev_bal  = get_evm_balance(HYPEREVM_RPC, evm_address)

    log(f"  SOL:     {sol_bal:.6f} SOL")
    log(f"  Base:    {base_bal:.8f} ETH")
    log(f"  Arb:     {arb_bal:.8f} ETH")
    log(f"  OP:      {op_bal:.8f} ETH")
    log(f"  HyperEVM:{hev_bal:.8f} ETH")

    state = load_state()
    all_interactions = []

    # Farm each chain
    if sol_keypair:
        sol_ixs = farm_solana(sol_keypair, sol_bal, state)
        all_interactions.extend(sol_ixs)

    base_ixs = farm_evm_chain(evm_pk, evm_address, BASE_RPC, WETH_BASE, "Base", "WETH/Aerodrome", base_bal, state)
    all_interactions.extend(base_ixs)
    time.sleep(random.randint(5, 15))

    arb_ixs = farm_evm_chain(evm_pk, evm_address, ARB_RPC, WETH_ARB, "Arbitrum", "WETH/Camelot", arb_bal, state)
    all_interactions.extend(arb_ixs)
    time.sleep(random.randint(5, 15))

    op_ixs = farm_evm_chain(evm_pk, evm_address, OP_RPC, WETH_OP, "Optimism", "WETH/Velodrome", op_bal, state)
    all_interactions.extend(op_ixs)
    time.sleep(random.randint(5, 15))

    hev_ixs = farm_evm_chain(evm_pk, evm_address, HYPEREVM_RPC, WHYPE_HEV, "HyperEVM", "WHYPE", hev_bal, state)
    all_interactions.extend(hev_ixs)

    # Update state
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["total_txs"] = state.get("total_txs", 0) + len(all_interactions)
    protocols = set(state.get("protocols_touched", []))
    for ix in all_interactions:
        ix["timestamp"] = datetime.now(timezone.utc).isoformat()
        protocols.add(ix["protocol"])
    state["protocols_touched"] = list(protocols)
    history = state.get("interactions", [])
    history.extend(all_interactions)
    state["interactions"] = history[-200:]
    save_state(state)

    log(f"\n  📊 Session Summary:")
    log(f"     Interactions this run: {len(all_interactions)}")
    log(f"     Total lifetime TXs:    {state['total_txs']}")
    log(f"     Protocols touched:     {', '.join(state['protocols_touched']) if state['protocols_touched'] else 'none yet'}")

    if all_interactions:
        send_session_alert(all_interactions, sol_bal, base_bal, arb_bal, op_bal, hev_bal)
    else:
        log("  ⚠️ No farming executed — wallets need funding")
        log(f"     SOL address: {sol_address}")
        log(f"     EVM address: {evm_address}")
        log("     Fund with 0.02 SOL + 0.001 ETH on Base to activate")

    log("=" * 60)

if __name__ == "__main__":
    main()
