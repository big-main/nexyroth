# Changelog

All notable changes to NEXYROTH are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.1.0] — 2026-07-29

### Added
- **HF Scalper v1.0** (`bitunix_hf_scalper.py`) — high-frequency momentum scalper running every 30 seconds for continuous small profits across all 10 zero-fee tokens
- **VWAP filter** (Filter 6) — price must be above/below 30-candle VWAP for LONG/SHORT
- **CVD filter** (Filter 7) — cumulative volume delta must confirm direction over 10-candle lookback
- **Telegram alerts** via @Cnzanderbot — instant push notifications on every trade open and close
- **WebSocket market data streamer** (`bitunix_ws_streamer.py`) — real-time tick data replacing REST polling, zero latency

### Changed
- Scalper RSI range widened to 25–75 (was 35–65) for earlier reversal entries
- Volume filter lowered to 0.5x (was 1.2x) — only blocks truly dead volume
- VWAP window reduced to 30 candles (was 60) for faster responsiveness
- CVD lookback reduced to 10 candles (was 20) for faster delta signals
- Scalper upgraded from v2.0 to v2.1 with 7-filter confluence

---

## [2.0.0] — 2026-07-28

### Added
- **AlgoPro Hybrid Scalper v2.0** (`bitunix_scalper.py`) — 5-filter confluence strategy
  - EMA 9/21 crossover, 200 EMA trend, MACD histogram, volume, RSI
  - Rolling Kelly Criterion position sizing
  - Chandelier trailing stop (ATR × 2.5)
  - ATR emergency hard stop (ATR × 1.5)
  - TP at 3:1 risk-reward ratio
- **TradingView Webhook Bridge** (`tradingview_webhook.py`) — live at port 8765
- **Bitunix Auto-Executor v1.0** — funding rate arbitrage on 10 zero-fee tokens

### Fixed
- Auto-executor threshold bug: FR values were compared in % format against decimal API values

---

## [1.2.0] — 2026-07-20

### Added
- **Kalshi Universal Trader v3.0** — scans 1000+ Kalshi markets across all categories
- **Airdrop Farmer v2.0** — multi-chain farming (Solana, Base, Arbitrum, Optimism, HyperEVM)
- **Bitunix Daily Digest** — AI-generated email digest with BEST ENTRY signals

---

## [1.0.0] — 2026-07-01

### Added
- Initial NEXYROTH trading system
- Background scanner (Bitunix + Kalshi every 15 minutes)
- Kalshi BTC/ETH market monitor and auto-trader
- Funding rate scanner and copy trader
- Email alert system
