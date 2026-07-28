#!/usr/bin/env python3
"""
NEXYROTH Airdrop Farming — Wallet Generator
Generates fresh Solana + EVM wallets and stores keys securely.
"""
import os
import json
import secrets
from datetime import datetime

# Solana wallet generation
from solders.keypair import Keypair
import base58

# EVM wallet generation
from eth_account import Account

WALLET_DIR = os.path.expanduser("~/trading_sniper/data/airdrop_wallets")
os.makedirs(WALLET_DIR, exist_ok=True)

def generate_solana_wallet():
    """Generate a new Solana keypair."""
    kp = Keypair()
    public_key = str(kp.pubkey())
    private_key = base58.b58encode(bytes(kp)).decode('utf-8')
    return {
        "chain": "solana",
        "address": public_key,
        "private_key": private_key,
        "created_at": datetime.utcnow().isoformat()
    }

def generate_evm_wallet():
    """Generate a new EVM wallet (works on Base, Arbitrum, Optimism, ETH mainnet)."""
    Account.enable_unaudited_hdwallet_features()
    # Generate from random entropy
    private_key = "0x" + secrets.token_hex(32)
    account = Account.from_key(private_key)
    return {
        "chain": "evm",
        "address": account.address,
        "private_key": private_key,
        "supported_networks": ["base", "arbitrum", "optimism", "ethereum", "hyperevm"],
        "created_at": datetime.utcnow().isoformat()
    }

def main():
    print("=" * 60)
    print("  NEXYROTH — Airdrop Farming Wallet Generator")
    print("=" * 60)
    
    # Generate Solana wallet
    sol_wallet = generate_solana_wallet()
    print(f"\n✅ Solana Wallet Generated")
    print(f"   Address: {sol_wallet['address']}")
    print(f"   Use for: Jupiter, Raydium, Bulk Trade, Hylo, Solana DeFi")
    
    # Generate EVM wallet
    evm_wallet = generate_evm_wallet()
    print(f"\n✅ EVM Wallet Generated")
    print(f"   Address: {evm_wallet['address']}")
    print(f"   Use for: Base, Arbitrum, Optimism, HyperEVM, Aerodrome, Uniswap")
    
    # Save to secure file (chmod 600)
    wallet_file = os.path.join(WALLET_DIR, "farming_wallets.json")
    wallet_data = {
        "generated_at": datetime.utcnow().isoformat(),
        "purpose": "Airdrop farming - automated protocol interactions",
        "wallets": {
            "solana": sol_wallet,
            "evm": evm_wallet
        },
        "target_protocols": {
            "solana": ["Jupiter", "Raydium", "Bulk Trade", "Hylo", "Axiom"],
            "base": ["Aerodrome", "Uniswap V3", "Avantis", "Base Bridge"],
            "hyperevm": ["Valantis", "Felix", "Liminal", "Hyperbeat"],
            "general": ["Paradex", "Lighter", "Ethereal"]
        }
    }
    
    with open(wallet_file, 'w') as f:
        json.dump(wallet_data, f, indent=2)
    
    # Secure the file
    os.chmod(wallet_file, 0o600)
    
    print(f"\n🔐 Wallets saved to: {wallet_file}")
    print(f"   File permissions: 600 (owner read/write only)")
    
    # Also save a public-only version for reference
    public_file = os.path.join(WALLET_DIR, "wallet_addresses.txt")
    with open(public_file, 'w') as f:
        f.write("NEXYROTH Airdrop Farming Wallet Addresses\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Solana: {sol_wallet['address']}\n")
        f.write(f"EVM:    {evm_wallet['address']}\n")
        f.write(f"\nGenerated: {datetime.utcnow().isoformat()}\n")
        f.write(f"\nFunding needed:\n")
        f.write(f"  - Send ~0.02 SOL to Solana address (for gas)\n")
        f.write(f"  - Send ~0.001 ETH on Base to EVM address (for gas)\n")
        f.write(f"\nOR use the auto-faucet system (faucet_harvester.py)\n")
    
    print(f"\n📋 Public addresses saved to: {public_file}")
    print(f"\n{'=' * 60}")
    print(f"  NEXT: Run faucet_harvester.py to auto-fund these wallets")
    print(f"{'=' * 60}")
    
    return wallet_data

if __name__ == "__main__":
    main()
