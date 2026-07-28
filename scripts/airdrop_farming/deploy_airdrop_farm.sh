#!/bin/bash
# NEXYROTH Airdrop Farming — Deploy to Cloud Computer
# Copies scripts, generates wallets, sets up cron jobs

set -e

DEPLOY_DIR="$HOME/trading_sniper/scripts/airdrop_farming"
DATA_DIR="$HOME/trading_sniper/data/airdrop_wallets"
LOG_DIR="$HOME/trading_sniper/data/airdrop_logs"

echo "=================================================="
echo "  NEXYROTH Airdrop Farm — Deployment"
echo "=================================================="

# Create directories
mkdir -p "$DEPLOY_DIR" "$DATA_DIR" "$LOG_DIR"

echo "✅ Directories created"

# Generate wallets if not exists
if [ ! -f "$DATA_DIR/farming_wallets.json" ]; then
    echo "🔑 Generating fresh wallets..."
    cd "$DEPLOY_DIR"
    python3 wallet_generator.py
    echo "✅ Wallets generated"
else
    echo "ℹ️  Wallets already exist, skipping generation"
fi

# Run initial faucet harvest
echo "💧 Running initial faucet harvest..."
python3 "$DEPLOY_DIR/faucet_harvester.py" || true

# Set up cron jobs
echo "⏰ Setting up cron jobs..."

# Remove old airdrop cron entries
crontab -l 2>/dev/null | grep -v "airdrop_farming" | grep -v "AIRDROP" > /tmp/crontab_clean || true

# Add new airdrop cron jobs
cat >> /tmp/crontab_clean << 'CRON'
# === NEXYROTH AIRDROP FARMING ===
# Faucet harvester - every 6 hours (try to auto-fund wallets)
0 */6 * * * cd ~/trading_sniper/scripts/airdrop_farming && python3 faucet_harvester.py >> ~/trading_sniper/data/airdrop_logs/faucet_cron.log 2>&1
# Main farmer - every 4 hours (perform on-chain interactions)
30 */4 * * * cd ~/trading_sniper/scripts/airdrop_farming && python3 airdrop_farmer.py >> ~/trading_sniper/data/airdrop_logs/farmer_cron.log 2>&1
# Daily digest - 11:55 PM EDT (3:55 AM UTC)
55 3 * * * cd ~/trading_sniper/scripts/airdrop_farming && python3 airdrop_daily_digest.py >> ~/trading_sniper/data/airdrop_logs/digest_cron.log 2>&1
# === END AIRDROP FARMING ===
CRON

crontab /tmp/crontab_clean
rm /tmp/crontab_clean

echo "✅ Cron jobs installed:"
echo "   • Faucet harvester: every 6 hours"
echo "   • Airdrop farmer: every 4 hours"  
echo "   • Daily digest: 11:55 PM EDT"

# Show wallet addresses
echo ""
echo "=================================================="
echo "  WALLET ADDRESSES"
echo "=================================================="
if [ -f "$DATA_DIR/wallet_addresses.txt" ]; then
    cat "$DATA_DIR/wallet_addresses.txt"
fi

echo ""
echo "=================================================="
echo "  DEPLOYMENT COMPLETE"
echo "=================================================="
echo ""
echo "System will:"
echo "  1. Try auto-funding via faucets every 6 hours"
echo "  2. Farm airdrops every 4 hours (when funded)"
echo "  3. Send daily digest at 11:55 PM EDT"
echo ""
echo "Target airdrops: Base, Hyperliquid S2, Bulk Trade,"
echo "  Hylo, Jupiter, Avantis S3, Paradex, Ethereal"
echo ""
