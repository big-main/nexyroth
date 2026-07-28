#!/usr/bin/env python3
"""
NEXYROTH Airdrop Farming — Main Farmer
Performs automated on-chain interactions to qualify for airdrops.
Supports: Solana (Jupiter, Raydium), Base (Aerodrome, Uniswap), HyperEVM.
Runs on cron — checks balance first, only farms if funded.
"""
import os
import sys
import json
import time
import random
import requests
import base58
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

# Blockchain imports
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash
from web3 import Web3
from eth_account import Account

# Configuration
WALLET_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_wallets/farming_wallets.json")
LOG_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_logs/farming_activity.log")
STATE_FILE = os.path.expanduser("~/trading_sniper/data/airdrop_logs/farming_state.json")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")

# RPC Endpoints
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
BASE_RPC = "https://mainnet.base.org"
ARBITRUM_RPC = "https://arb1.arbitrum.io/rpc"
OPTIMISM_RPC = "https://mainnet.optimism.io"

# Jupiter API (Solana DEX aggregator)
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API = "https://quote-api.jup.ag/v6/swap"

# Token addresses
SOL_MINT = "So11111111111111111111111111111111111111112"  # Wrapped SOL
USDC_SOL_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC on Solana

# Base contract addresses
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
UNISWAP_V3_ROUTER = "0x2626664c2603336E57B271c5C0b26F421741e481"  # SwapRouter02 on Base
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Minimum balances to start farming
MIN_SOL = 0.005  # ~$0.75, enough for ~5 swaps
MIN_ETH = 0.0003  # ~$0.90 on Base, enough for ~10 swaps

def log(msg):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + "\n")

def load_wallets():
    if not os.path.exists(WALLET_FILE):
        log("ERROR: No wallet file. Run wallet_generator.py first.")
        sys.exit(1)
    with open(WALLET_FILE, 'r') as f:
        return json.load(f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"interactions": [], "total_txs": 0, "protocols_touched": [], "last_run": None}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ============================================================
# SOLANA FARMING
# ============================================================

def get_solana_balance(address: str) -> float:
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]
        }, timeout=10)
        return resp.json()["result"]["value"] / 1e9
    except:
        return 0.0

def jupiter_swap_sol_to_usdc(keypair: Keypair, amount_lamports: int) -> Optional[str]:
    """Execute a small SOL→USDC swap on Jupiter to generate activity."""
    try:
        # Get quote
        quote_resp = requests.get(JUPITER_QUOTE_API, params={
            "inputMint": SOL_MINT,
            "outputMint": USDC_SOL_MINT,
            "amount": str(amount_lamports),
            "slippageBps": "100"  # 1% slippage
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
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto"
        }, timeout=15)
        
        if swap_resp.status_code != 200:
            log(f"    Jupiter swap tx failed: {swap_resp.status_code}")
            return None
        
        swap_data = swap_resp.json()
        swap_tx_b64 = swap_data.get("swapTransaction")
        
        if not swap_tx_b64:
            log("    No swap transaction returned")
            return None
        
        # Decode, sign, and send
        import base64
        from solders.transaction import VersionedTransaction
        
        tx_bytes = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        
        # Sign the transaction
        signed_tx = VersionedTransaction(tx.message, [keypair])
        
        # Send
        send_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(bytes(signed_tx)).decode('utf-8'), {"encoding": "base64"}]
        }, timeout=30)
        
        result = send_resp.json()
        if "result" in result:
            tx_sig = result["result"]
            log(f"    ✅ Jupiter swap TX: {tx_sig[:20]}...")
            return tx_sig
        else:
            error = result.get("error", {}).get("message", "Unknown error")
            log(f"    ❌ Jupiter swap error: {error[:80]}")
            return None
            
    except Exception as e:
        log(f"    ❌ Jupiter swap exception: {e}")
        return None

def jupiter_swap_usdc_to_sol(keypair: Keypair, amount_usdc: int) -> Optional[str]:
    """Swap USDC back to SOL (round-trip for activity)."""
    try:
        quote_resp = requests.get(JUPITER_QUOTE_API, params={
            "inputMint": USDC_SOL_MINT,
            "outputMint": SOL_MINT,
            "amount": str(amount_usdc),
            "slippageBps": "100"
        }, timeout=15)
        
        if quote_resp.status_code != 200:
            return None
        
        quote = quote_resp.json()
        
        swap_resp = requests.post(JUPITER_SWAP_API, json={
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto"
        }, timeout=15)
        
        if swap_resp.status_code != 200:
            return None
        
        swap_data = swap_resp.json()
        swap_tx_b64 = swap_data.get("swapTransaction")
        if not swap_tx_b64:
            return None
        
        import base64
        from solders.transaction import VersionedTransaction
        
        tx_bytes = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = VersionedTransaction(tx.message, [keypair])
        
        send_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(bytes(signed_tx)).decode('utf-8'), {"encoding": "base64"}]
        }, timeout=30)
        
        result = send_resp.json()
        if "result" in result:
            log(f"    ✅ Jupiter USDC→SOL TX: {result['result'][:20]}...")
            return result["result"]
        return None
    except Exception as e:
        log(f"    ❌ USDC→SOL error: {e}")
        return None

def solana_self_transfer(keypair: Keypair, lamports: int = 1000) -> Optional[str]:
    """Self-transfer to generate basic on-chain activity (costs ~0.000005 SOL)."""
    try:
        # Get recent blockhash
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getLatestBlockhash", "params": [{"commitment": "finalized"}]
        }, timeout=10)
        blockhash = resp.json()["result"]["value"]["blockhash"]
        
        # Create transfer to self
        ix = transfer(TransferParams(
            from_pubkey=keypair.pubkey(),
            to_pubkey=keypair.pubkey(),
            lamports=lamports
        ))
        
        msg = Message.new_with_blockhash([ix], keypair.pubkey(), Hash.from_string(blockhash))
        tx = Transaction.new_unsigned(msg)
        tx.sign([keypair], Hash.from_string(blockhash))
        
        import base64
        tx_bytes = bytes(tx)
        
        send_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(tx_bytes).decode('utf-8'), {"encoding": "base64", "skipPreflight": True}]
        }, timeout=30)
        
        result = send_resp.json()
        if "result" in result:
            log(f"    ✅ SOL self-transfer TX: {result['result'][:20]}...")
            return result["result"]
        else:
            error = result.get("error", {}).get("message", "Unknown")
            log(f"    ❌ Self-transfer error: {error[:80]}")
            return None
    except Exception as e:
        log(f"    ❌ Self-transfer exception: {e}")
        return None

# ============================================================
# BASE (EVM) FARMING
# ============================================================

def get_base_balance(address: str) -> float:
    try:
        resp = requests.post(BASE_RPC, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_getBalance", "params": [address, "latest"]
        }, timeout=10)
        return int(resp.json()["result"], 16) / 1e18
    except:
        return 0.0

def base_self_transfer(private_key: str, address: str) -> Optional[str]:
    """Self-transfer ETH on Base to generate activity."""
    try:
        w3 = Web3(Web3.HTTPProvider(BASE_RPC))
        
        nonce = w3.eth.get_transaction_count(address)
        gas_price = w3.eth.gas_price
        
        tx = {
            'nonce': nonce,
            'to': address,  # Self-transfer
            'value': 1,  # 1 wei
            'gas': 21000,
            'gasPrice': gas_price,
            'chainId': 8453  # Base chain ID
        }
        
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        
        log(f"    ✅ Base self-transfer TX: {tx_hash.hex()[:20]}...")
        return tx_hash.hex()
    except Exception as e:
        log(f"    ❌ Base self-transfer error: {e}")
        return None

def base_wrap_eth(private_key: str, address: str, amount_wei: int = 100) -> Optional[str]:
    """Wrap tiny amount of ETH to WETH on Base (generates DeFi activity)."""
    try:
        w3 = Web3(Web3.HTTPProvider(BASE_RPC))
        
        # WETH deposit function (wrapping ETH)
        weth_contract = w3.eth.contract(
            address=Web3.to_checksum_address(WETH_BASE),
            abi=[{"constant": False, "inputs": [], "name": "deposit", "outputs": [], "payable": True, "stateMutability": "payable", "type": "function"}]
        )
        
        nonce = w3.eth.get_transaction_count(address)
        gas_price = w3.eth.gas_price
        
        tx = weth_contract.functions.deposit().build_transaction({
            'from': address,
            'value': amount_wei,
            'gas': 50000,
            'gasPrice': gas_price,
            'nonce': nonce,
            'chainId': 8453
        })
        
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        
        log(f"    ✅ Base WETH wrap TX: {tx_hash.hex()[:20]}...")
        return tx_hash.hex()
    except Exception as e:
        log(f"    ❌ Base WETH wrap error: {e}")
        return None

def base_unwrap_weth(private_key: str, address: str, amount_wei: int = 100) -> Optional[str]:
    """Unwrap WETH back to ETH on Base."""
    try:
        w3 = Web3(Web3.HTTPProvider(BASE_RPC))
        
        weth_contract = w3.eth.contract(
            address=Web3.to_checksum_address(WETH_BASE),
            abi=[{"constant": False, "inputs": [{"name": "wad", "type": "uint256"}], "name": "withdraw", "outputs": [], "payable": False, "stateMutability": "nonpayable", "type": "function"}]
        )
        
        nonce = w3.eth.get_transaction_count(address)
        gas_price = w3.eth.gas_price
        
        tx = weth_contract.functions.withdraw(amount_wei).build_transaction({
            'from': address,
            'gas': 50000,
            'gasPrice': gas_price,
            'nonce': nonce,
            'chainId': 8453
        })
        
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        
        log(f"    ✅ Base WETH unwrap TX: {tx_hash.hex()[:20]}...")
        return tx_hash.hex()
    except Exception as e:
        log(f"    ❌ Base WETH unwrap error: {e}")
        return None

# ============================================================
# FARMING ORCHESTRATOR
# ============================================================

def farm_solana(keypair: Keypair, balance: float, state: dict) -> List[Dict]:
    """Execute Solana farming interactions."""
    interactions = []
    
    if balance < MIN_SOL:
        log("  ⚠️ Solana: Insufficient balance for farming")
        return interactions
    
    log(f"  🌾 Solana farming (balance: {balance:.6f} SOL)")
    
    # Strategy: Rotate between different interaction types
    day_of_week = datetime.utcnow().weekday()
    hour = datetime.utcnow().hour
    
    # 1. Always do a self-transfer (cheapest, generates base activity)
    tx = solana_self_transfer(keypair)
    if tx:
        interactions.append({"protocol": "Solana", "action": "self_transfer", "tx": tx, "chain": "solana"})
    
    # 2. Jupiter swap (SOL→USDC) — small amount for activity
    if balance > 0.01 and (day_of_week % 2 == 0 or hour % 6 == 0):
        # Swap 0.001 SOL (~$0.15) to USDC
        swap_amount = 1_000_000  # 0.001 SOL in lamports
        tx = jupiter_swap_sol_to_usdc(keypair, swap_amount)
        if tx:
            interactions.append({"protocol": "Jupiter", "action": "swap_sol_to_usdc", "tx": tx, "chain": "solana"})
            # Wait and swap back
            time.sleep(random.randint(10, 30))
            # Swap USDC back (approximate amount)
            tx2 = jupiter_swap_usdc_to_sol(keypair, 150)  # ~$0.15 USDC = 150 (6 decimals)
            if tx2:
                interactions.append({"protocol": "Jupiter", "action": "swap_usdc_to_sol", "tx": tx2, "chain": "solana"})
    
    # Add random delay between actions (human-like behavior)
    time.sleep(random.randint(3, 15))
    
    return interactions

def farm_base(private_key: str, address: str, balance: float, state: dict) -> List[Dict]:
    """Execute Base chain farming interactions."""
    interactions = []
    
    if balance < MIN_ETH:
        log("  ⚠️ Base: Insufficient balance for farming")
        return interactions
    
    log(f"  🌾 Base farming (balance: {balance:.8f} ETH)")
    
    day_of_week = datetime.utcnow().weekday()
    hour = datetime.utcnow().hour
    
    # 1. Self-transfer (cheapest activity)
    tx = base_self_transfer(private_key, address)
    if tx:
        interactions.append({"protocol": "Base", "action": "self_transfer", "tx": tx, "chain": "base"})
    
    time.sleep(random.randint(5, 20))
    
    # 2. Wrap/Unwrap ETH (DeFi activity on Aerodrome/Uniswap ecosystem)
    if balance > 0.0005 and (day_of_week % 2 == 1 or hour % 8 == 0):
        wrap_amount = 100  # 100 wei (essentially free)
        tx = base_wrap_eth(private_key, address, wrap_amount)
        if tx:
            interactions.append({"protocol": "WETH", "action": "wrap_eth", "tx": tx, "chain": "base"})
            time.sleep(random.randint(10, 30))
            tx2 = base_unwrap_weth(private_key, address, wrap_amount)
            if tx2:
                interactions.append({"protocol": "WETH", "action": "unwrap_eth", "tx": tx2, "chain": "base"})
    
    return interactions

def main():
    log("=" * 60)
    log("NEXYROTH Airdrop Farmer — Starting")
    log("=" * 60)
    
    # Load wallets
    wallets = load_wallets()
    sol_data = wallets["wallets"]["solana"]
    evm_data = wallets["wallets"]["evm"]
    
    sol_address = sol_data["address"]
    evm_address = evm_data["address"]
    
    # Reconstruct keypairs
    sol_keypair = Keypair.from_bytes(base58.b58decode(sol_data["private_key"]))
    evm_private_key = evm_data["private_key"]
    
    # Check balances
    sol_balance = get_solana_balance(sol_address)
    base_balance = get_base_balance(evm_address)
    
    log(f"  SOL balance: {sol_balance:.6f} SOL")
    log(f"  Base ETH balance: {base_balance:.8f} ETH")
    
    # Load state
    state = load_state()
    
    all_interactions = []
    
    # Farm Solana
    if sol_balance >= MIN_SOL:
        sol_interactions = farm_solana(sol_keypair, sol_balance, state)
        all_interactions.extend(sol_interactions)
    else:
        log("  ⏸️ Solana farming paused — need funding")
    
    # Farm Base
    if base_balance >= MIN_ETH:
        base_interactions = farm_base(evm_private_key, evm_address, base_balance, state)
        all_interactions.extend(base_interactions)
    else:
        log("  ⏸️ Base farming paused — need funding")
    
    # Update state
    state["last_run"] = datetime.utcnow().isoformat()
    state["total_txs"] = state.get("total_txs", 0) + len(all_interactions)
    
    # Track protocols touched
    protocols = set(state.get("protocols_touched", []))
    for ix in all_interactions:
        protocols.add(ix["protocol"])
    state["protocols_touched"] = list(protocols)
    
    # Append to interaction history (keep last 100)
    history = state.get("interactions", [])
    for ix in all_interactions:
        ix["timestamp"] = datetime.utcnow().isoformat()
        history.append(ix)
    state["interactions"] = history[-100:]
    
    # Save state
    save_state(state)
    
    log(f"\n  📊 Session Summary:")
    log(f"     Interactions this run: {len(all_interactions)}")
    log(f"     Total lifetime TXs: {state['total_txs']}")
    log(f"     Protocols touched: {', '.join(state['protocols_touched'])}")
    
    if not all_interactions and sol_balance < MIN_SOL and base_balance < MIN_ETH:
        log("  ⚠️ No farming possible — wallets need funding")
        log(f"     SOL address: {sol_address}")
        log(f"     EVM address: {evm_address}")
    
    log("=" * 60)

if __name__ == "__main__":
    main()
