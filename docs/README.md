# NEXYROTH Trading System v1.0

High-velocity crypto trading automation for Bitunix zero-fee tokens.

## Systems

- **FR Arb Executor** (`scripts/bitunix_auto_executor.py`) — Funding rate arbitrage on 10 zero-fee tokens
- **Zero-Fee Scalper** (`scripts/bitunix_scalper.py`) — EMA9/21 crossover + RSI on 1-minute candles
- **Copy Trader** (`scripts/bitunix_copy_trader.py`) — Copy Bitpanetrain BTC trades
- **Kalshi Trader** (`scripts/kalshi_universal_trader.py`) — Prediction market edge scanner
- **Airdrop Farmer** (`scripts/airdrop_farming/airdrop_farmer_v2.py`) — Multi-chain airdrop farming

## Risk Configuration

- **Risk per trade:** 45% of balance
- **Leverage:** 10x
- **Max positions:** 5 concurrent
- **Take profit:** +5%
- **Stop loss:** -2.5%

## Setup

1. Set environment variables:
   ```bash
   export BITUNIX_API_KEY="your_key"
   export BITUNIX_SECRET_KEY="your_secret"
   export RESEND_API_KEY="your_resend_key"
   export ANTHROPIC_API_KEY="your_claude_key"
   ```

2. Install dependencies:
   ```bash
   pip3 install requests
   ```

3. Run the executor:
   ```bash
   python3 scripts/bitunix_auto_executor.py
   ```

## Cron Schedule

```
*/10 * * * * cd /home/ubuntu/trading_sniper && python3 scripts/bitunix_auto_executor.py
*/5  * * * * cd /home/ubuntu/trading_sniper && python3 scripts/bitunix_scalper.py
*/2  * * * * cd /home/ubuntu/trading_sniper && python3 scripts/bitunix_copy_trader.py
*/15 * * * * cd /home/ubuntu/trading_sniper && python3 scripts/kalshi_universal_trader.py
*/4  * * * * cd /home/ubuntu/trading_sniper && python3 scripts/airdrop_farming/airdrop_farmer_v2.py
```

## License

Proprietary — NEXYROTH Trading System
