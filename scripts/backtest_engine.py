#!/usr/bin/env python3
"""
NEXYROTH Backtesting Engine v1.0
=================================
Backtests all 5 strategies across the full 36-symbol watchlist
using 90 days of historical Bitunix kline data.

Strategies tested:
  1. RSI Divergence (bullish/bearish)
  2. VWAP Mean Reversion
  3. Funding Rate Arbitrage
  4. EMA Crossover + Volume
  5. Momentum Breakout

Output:
  - Per-symbol results (win rate, PnL, Sharpe, drawdown)
  - Per-strategy breakdown
  - Combined system performance
  - HTML report + JSON data
"""

import requests
import json
import time
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import numpy as np

try:
    import ta
except ImportError:
    os.system("pip3 install ta -q")
    import ta

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

WATCHLIST = [
    # Your TradingView watchlist
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "PEPEUSDT", "HYPEUSDT", "JUPUSDT", "AGLDUSDT", "FARTCOINUSDT",
    "SENTUSDT", "AIAUSDT", "PIPPINUSDT", "RIVERUSDT", "XAUTUSDT", "XAGUSDT",
    # High-value additions
    "SUIUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT",
    "LINKUSDT", "AAVEUSDT", "UNIUSDT", "BNBUSDT",
    "ADAUSDT", "DOTUSDT", "LTCUSDT", "ATOMUSDT",
    "NEARUSDT", "INJUSDT", "WIFUSDT", "BONKUSDT",
    "MEMEUSDT", "SHIBUSDT", "OPUSDT", "TIAUSDT",
]

BACKTEST_DAYS = 33          # Days of history (Bitunix returns max 200 candles)
KLINE_INTERVAL = "4h"       # 4-hour candles (200 candles = ~33 days)
STOP_LOSS_PCT = 0.03        # 3% stop loss
TAKE_PROFIT_PCT = 0.045     # 4.5% take profit
LEVERAGE = 2                # 2x leverage
INITIAL_BALANCE = 10.0      # Starting balance
RISK_PER_TRADE = 0.05       # 5% risk per trade
SIGNAL_THRESHOLD = 0.45     # Minimum combined score to enter

BASE_URL = "https://fapi.bitunix.com"
DATA_DIR = Path("/home/ubuntu/trading_sniper/data")
DATA_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# DATA FETCHER
# ═══════════════════════════════════════════════════════════════

def fetch_klines(symbol, interval="4h", days=33):
    """Fetch historical klines from Bitunix.
    Note: Bitunix returns max 200 candles per request regardless of limit param.
    200 x 4h = ~33 days of history.
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v1/futures/market/kline",
            params={"symbol": symbol, "interval": interval, "limit": 200},
            timeout=15
        )
        data = resp.json()
        candles = data.get("data", [])
        if not candles or not isinstance(candles, list):
            return None

        df = pd.DataFrame(candles)
        rename_map = {"quoteVol": "volume", "baseVol": "base_volume", "time": "timestamp"}
        df = df.rename(columns=rename_map)
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" not in df.columns:
            df["volume"] = 1.0
        else:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(1.0)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
            df = df.sort_values("timestamp").reset_index(drop=True)
            df = df.drop_duplicates(subset="timestamp")
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df if len(df) >= 50 else None
    except Exception:
        return None

# ═══════════════════════════════════════════════════════════════
# STRATEGY SIGNAL GENERATORS (vectorized for backtesting)
# ═══════════════════════════════════════════════════════════════

def compute_rsi_divergence_signals(df):
    """
    RSI Bullish Divergence: price makes lower low but RSI makes higher low.
    RSI Bearish Divergence: price makes higher high but RSI makes lower high.
    Returns series of 'LONG', 'SHORT', or 'NEUTRAL' per bar.
    """
    rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    signals = pd.Series("NEUTRAL", index=df.index)
    scores = pd.Series(0.0, index=df.index)

    lookback = 5
    for i in range(lookback * 2, len(df)):
        curr_rsi = rsi.iloc[i]
        curr_close = df["close"].iloc[i]

        # Look back for a swing low
        prev_low_idx = df["close"].iloc[i - lookback * 2:i - lookback].idxmin()
        prev_rsi_at_low = rsi.iloc[prev_low_idx]
        prev_close_low = df["close"].iloc[prev_low_idx]

        # Bullish divergence: price lower low, RSI higher low
        if curr_close < prev_close_low and curr_rsi > prev_rsi_at_low and curr_rsi < 50:
            confidence = min(1.0, (prev_rsi_at_low - curr_rsi + 5) / 20 + 0.5)
            signals.iloc[i] = "LONG"
            scores.iloc[i] = confidence

        # Bearish divergence: price higher high, RSI lower high
        prev_high_idx = df["close"].iloc[i - lookback * 2:i - lookback].idxmax()
        prev_rsi_at_high = rsi.iloc[prev_high_idx]
        prev_close_high = df["close"].iloc[prev_high_idx]

        if curr_close > prev_close_high and curr_rsi < prev_rsi_at_high and curr_rsi > 50:
            confidence = min(1.0, (curr_rsi - prev_rsi_at_high + 5) / 20 + 0.5)
            signals.iloc[i] = "SHORT"
            scores.iloc[i] = confidence

    return signals, scores


def compute_vwap_signals(df):
    """VWAP mean reversion: buy below VWAP, sell above VWAP."""
    # Compute rolling VWAP (24-bar rolling)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    vwap = (typical_price * df["volume"]).rolling(24).sum() / df["volume"].rolling(24).sum()

    dist_pct = ((df["close"] - vwap) / vwap) * 100
    signals = pd.Series("NEUTRAL", index=df.index)
    scores = pd.Series(0.0, index=df.index)

    signals[dist_pct < -2.0] = "LONG"
    scores[dist_pct < -2.0] = (dist_pct[dist_pct < -2.0].abs() / 5).clip(0, 1)
    signals[dist_pct > 2.0] = "SHORT"
    scores[dist_pct > 2.0] = (dist_pct[dist_pct > 2.0] / 5).clip(0, 1)

    return signals, scores


def compute_ema_signals(df):
    """EMA 9/21 crossover with volume confirmation."""
    ema9 = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
    ema21 = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
    avg_vol = df["volume"].rolling(20).mean()

    signals = pd.Series("NEUTRAL", index=df.index)
    scores = pd.Series(0.0, index=df.index)

    # Bullish cross: ema9 crosses above ema21
    bullish_cross = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1))
    vol_spike = df["volume"] > avg_vol * 1.5

    signals[bullish_cross & vol_spike] = "LONG"
    scores[bullish_cross & vol_spike] = 0.8
    signals[bullish_cross & ~vol_spike] = "LONG"
    scores[bullish_cross & ~vol_spike] = 0.5

    # Bearish cross: ema9 crosses below ema21
    bearish_cross = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
    signals[bearish_cross & vol_spike] = "SHORT"
    scores[bearish_cross & vol_spike] = 0.8
    signals[bearish_cross & ~vol_spike] = "SHORT"
    scores[bearish_cross & ~vol_spike] = 0.5

    return signals, scores


def compute_momentum_signals(df):
    """Momentum breakout: strong 24h move near high."""
    pct_change = df["close"].pct_change(24) * 100
    rolling_high = df["high"].rolling(24).max()
    dist_from_high = ((rolling_high - df["close"]) / rolling_high) * 100

    signals = pd.Series("NEUTRAL", index=df.index)
    scores = pd.Series(0.0, index=df.index)

    # Strong upward momentum near 24h high
    strong_up = (pct_change > 8) & (dist_from_high < 1)
    signals[strong_up] = "LONG"
    scores[strong_up] = (pct_change[strong_up] / 15).clip(0, 1)

    # Strong downward momentum
    strong_down = pct_change < -8
    signals[strong_down] = "SHORT"
    scores[strong_down] = (pct_change[strong_down].abs() / 15).clip(0, 1)

    return signals, scores


def compute_combined_signals(df):
    """Combine all strategies into a single signal per bar."""
    weights = {
        "rsi": 0.25,
        "vwap": 0.20,
        "ema": 0.15,
        "momentum": 0.10,
    }

    rsi_sig, rsi_score = compute_rsi_divergence_signals(df)
    vwap_sig, vwap_score = compute_vwap_signals(df)
    ema_sig, ema_score = compute_ema_signals(df)
    mom_sig, mom_score = compute_momentum_signals(df)

    long_score = pd.Series(0.0, index=df.index)
    short_score = pd.Series(0.0, index=df.index)
    long_count = pd.Series(0, index=df.index)
    short_count = pd.Series(0, index=df.index)

    for sig, score, weight in [
        (rsi_sig, rsi_score, weights["rsi"]),
        (vwap_sig, vwap_score, weights["vwap"]),
        (ema_sig, ema_score, weights["ema"]),
        (mom_sig, mom_score, weights["momentum"]),
    ]:
        long_mask = sig == "LONG"
        short_mask = sig == "SHORT"
        long_score += long_mask * score * weight
        short_score += short_mask * score * weight
        long_count += long_mask.astype(int)
        short_count += short_mask.astype(int)

    # RSI divergence boost
    rsi_boost = (rsi_sig == "LONG") & (rsi_score >= 0.70)
    long_score += rsi_boost * 0.15
    rsi_boost_short = (rsi_sig == "SHORT") & (rsi_score >= 0.70)
    short_score += rsi_boost_short * 0.15

    # Majority agreement bonus
    long_score += (long_count >= 3) * 0.10
    short_score += (short_count >= 3) * 0.10

    # Final signal
    final_sig = pd.Series("NEUTRAL", index=df.index)
    final_score = pd.Series(0.0, index=df.index)

    long_wins = (long_score > short_score) & (long_score >= SIGNAL_THRESHOLD)
    short_wins = (short_score > long_score) & (short_score >= SIGNAL_THRESHOLD)

    final_sig[long_wins] = "LONG"
    final_score[long_wins] = long_score[long_wins]
    final_sig[short_wins] = "SHORT"
    final_score[short_wins] = short_score[short_wins]

    return final_sig, final_score, {
        "rsi": (rsi_sig, rsi_score),
        "vwap": (vwap_sig, vwap_score),
        "ema": (ema_sig, ema_score),
        "momentum": (mom_sig, mom_score),
    }

# ═══════════════════════════════════════════════════════════════
# TRADE SIMULATOR
# ═══════════════════════════════════════════════════════════════

def simulate_trades(df, signals, scores, stop_pct=STOP_LOSS_PCT, tp_pct=TAKE_PROFIT_PCT, leverage=LEVERAGE):
    """
    Simulate trades: enter on signal, exit on stop/TP/end.
    Returns list of trade results.
    """
    trades = []
    in_trade = False
    entry_price = 0.0
    entry_idx = 0
    direction = "NEUTRAL"
    entry_score = 0.0

    for i in range(len(df)):
        close = df["close"].iloc[i]
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        sig = signals.iloc[i]
        score = scores.iloc[i]

        if in_trade:
            # Check stop loss and take profit
            if direction == "LONG":
                stop_price = entry_price * (1 - stop_pct)
                tp_price = entry_price * (1 + tp_pct)

                if low <= stop_price:
                    # Stop hit
                    pnl_pct = -stop_pct * leverage
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "direction": "LONG",
                        "entry_price": entry_price,
                        "exit_price": stop_price,
                        "pnl_pct": pnl_pct,
                        "result": "LOSS",
                        "score": entry_score,
                        "bars_held": i - entry_idx,
                    })
                    in_trade = False
                elif high >= tp_price:
                    # TP hit
                    pnl_pct = tp_pct * leverage
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "direction": "LONG",
                        "entry_price": entry_price,
                        "exit_price": tp_price,
                        "pnl_pct": pnl_pct,
                        "result": "WIN",
                        "score": entry_score,
                        "bars_held": i - entry_idx,
                    })
                    in_trade = False

            elif direction == "SHORT":
                stop_price = entry_price * (1 + stop_pct)
                tp_price = entry_price * (1 - tp_pct)

                if high >= stop_price:
                    pnl_pct = -stop_pct * leverage
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "direction": "SHORT",
                        "entry_price": entry_price,
                        "exit_price": stop_price,
                        "pnl_pct": pnl_pct,
                        "result": "LOSS",
                        "score": entry_score,
                        "bars_held": i - entry_idx,
                    })
                    in_trade = False
                elif low <= tp_price:
                    pnl_pct = tp_pct * leverage
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "direction": "SHORT",
                        "entry_price": entry_price,
                        "exit_price": tp_price,
                        "pnl_pct": pnl_pct,
                        "result": "WIN",
                        "score": entry_score,
                        "bars_held": i - entry_idx,
                    })
                    in_trade = False

        # Enter new trade if not in one
        if not in_trade and sig in ("LONG", "SHORT"):
            in_trade = True
            entry_price = close
            entry_idx = i
            direction = sig
            entry_score = score

    # Close any open trade at end
    if in_trade and entry_price > 0:
        close = df["close"].iloc[-1]
        if direction == "LONG":
            pnl_pct = ((close - entry_price) / entry_price) * leverage
        else:
            pnl_pct = ((entry_price - close) / entry_price) * leverage
        trades.append({
            "entry_idx": entry_idx,
            "exit_idx": len(df) - 1,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": close,
            "pnl_pct": pnl_pct,
            "result": "WIN" if pnl_pct > 0 else "LOSS",
            "score": entry_score,
            "bars_held": len(df) - 1 - entry_idx,
        })

    return trades


def compute_metrics(trades, initial_balance=INITIAL_BALANCE):
    """Compute performance metrics from trade list."""
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "total_pnl_pct": 0,
            "profit_factor": 0, "max_drawdown": 0,
            "sharpe": 0, "avg_win": 0, "avg_loss": 0,
            "expected_value": 0, "final_balance": initial_balance,
        }

    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]

    win_rate = len(wins) / len(trades)
    total_pnl_pct = sum(t["pnl_pct"] for t in trades)

    gross_profit = sum(t["pnl_pct"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl_pct"] for t in losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    expected_value = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Simulate equity curve
    balance = initial_balance
    peak = initial_balance
    max_dd = 0
    pnl_series = []

    for t in trades:
        risk_amount = balance * RISK_PER_TRADE
        trade_pnl = risk_amount * t["pnl_pct"]
        balance += trade_pnl
        pnl_series.append(trade_pnl)
        if balance > peak:
            peak = balance
        dd = (peak - balance) / peak
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio (annualized, assuming 1h bars, ~8760 bars/year)
    if len(pnl_series) > 1:
        pnl_arr = np.array(pnl_series)
        sharpe = (np.mean(pnl_arr) / np.std(pnl_arr)) * np.sqrt(8760 / max(1, sum(t["bars_held"] for t in trades) / len(trades)))
    else:
        sharpe = 0

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100, 1),
        "total_pnl_pct": round(total_pnl_pct * 100, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown": round(max_dd * 100, 1),
        "sharpe": round(sharpe, 2),
        "avg_win": round(avg_win * 100, 2),
        "avg_loss": round(avg_loss * 100, 2),
        "expected_value": round(expected_value * 100, 4),
        "final_balance": round(balance, 2),
    }

# ═══════════════════════════════════════════════════════════════
# MAIN BACKTEST RUNNER
# ═══════════════════════════════════════════════════════════════

def run_backtest():
    print("═" * 60)
    print("NEXYROTH Backtesting Engine v1.0")
    print(f"Symbols: {len(WATCHLIST)} | Days: {BACKTEST_DAYS} | Interval: {KLINE_INTERVAL}")
    print(f"Stop: {STOP_LOSS_PCT*100}% | TP: {TAKE_PROFIT_PCT*100}% | Leverage: {LEVERAGE}x")
    print("═" * 60)

    all_results = []
    failed_symbols = []

    for i, symbol in enumerate(WATCHLIST):
        print(f"[{i+1}/{len(WATCHLIST)}] Backtesting {symbol}...", end=" ", flush=True)

        df = fetch_klines(symbol, KLINE_INTERVAL, BACKTEST_DAYS)
        if df is None or len(df) < 100:
            print(f"SKIP (insufficient data: {len(df) if df is not None else 0} bars)")
            failed_symbols.append(symbol)
            continue

        try:
            signals, scores, strategy_signals = compute_combined_signals(df)
            trades = simulate_trades(df, signals, scores)
            metrics = compute_metrics(trades)
            metrics["symbol"] = symbol
            metrics["bars"] = len(df)
            all_results.append(metrics)

            status = f"✓ {metrics['total_trades']} trades | WR: {metrics['win_rate']}% | PF: {metrics['profit_factor']} | Sharpe: {metrics['sharpe']}"
            print(status)

        except Exception as e:
            print(f"ERROR: {e}")
            failed_symbols.append(symbol)

        time.sleep(0.2)

    return all_results, failed_symbols


def generate_report(all_results, failed_symbols):
    """Generate a comprehensive backtest report."""
    if not all_results:
        print("No results to report.")
        return

    df_results = pd.DataFrame(all_results)

    print("\n" + "═" * 60)
    print("BACKTEST RESULTS SUMMARY")
    print("═" * 60)

    # Overall stats
    total_trades = df_results["total_trades"].sum()
    avg_win_rate = df_results["win_rate"].mean()
    avg_pf = df_results[df_results["profit_factor"] != float("inf")]["profit_factor"].mean()
    avg_sharpe = df_results["sharpe"].mean()
    avg_dd = df_results["max_drawdown"].mean()
    avg_ev = df_results["expected_value"].mean()

    print(f"\nSymbols tested:     {len(all_results)}/{len(WATCHLIST)}")
    print(f"Total trades:       {total_trades}")
    print(f"Avg win rate:       {avg_win_rate:.1f}%")
    print(f"Avg profit factor:  {avg_pf:.2f}")
    print(f"Avg Sharpe ratio:   {avg_sharpe:.2f}")
    print(f"Avg max drawdown:   {avg_dd:.1f}%")
    print(f"Avg expected value: {avg_ev:.4f}% per trade")

    # Top performers
    print("\n── TOP 10 SYMBOLS BY WIN RATE ──")
    top_wr = df_results[df_results["total_trades"] >= 5].nlargest(10, "win_rate")
    for _, row in top_wr.iterrows():
        print(f"  {row['symbol']:<15} WR: {row['win_rate']:>5.1f}% | Trades: {int(row['total_trades']):>3} | PF: {row['profit_factor']:>5.2f} | Sharpe: {row['sharpe']:>5.2f}")

    print("\n── TOP 10 SYMBOLS BY PROFIT FACTOR ──")
    top_pf = df_results[(df_results["total_trades"] >= 5) & (df_results["profit_factor"] != float("inf"))].nlargest(10, "profit_factor")
    for _, row in top_pf.iterrows():
        print(f"  {row['symbol']:<15} PF: {row['profit_factor']:>5.2f} | WR: {row['win_rate']:>5.1f}% | Sharpe: {row['sharpe']:>5.2f} | MaxDD: {row['max_drawdown']:>4.1f}%")

    print("\n── TOP 10 SYMBOLS BY SHARPE RATIO ──")
    top_sharpe = df_results[df_results["total_trades"] >= 5].nlargest(10, "sharpe")
    for _, row in top_sharpe.iterrows():
        print(f"  {row['symbol']:<15} Sharpe: {row['sharpe']:>5.2f} | WR: {row['win_rate']:>5.1f}% | PF: {row['profit_factor']:>5.2f}")

    print("\n── WORST PERFORMERS (avoid) ──")
    worst = df_results[df_results["total_trades"] >= 5].nsmallest(5, "win_rate")
    for _, row in worst.iterrows():
        print(f"  {row['symbol']:<15} WR: {row['win_rate']:>5.1f}% | PF: {row['profit_factor']:>5.2f} | MaxDD: {row['max_drawdown']:>4.1f}%")

    # $10 → $100 projection
    print("\n── $10 → $100 PROJECTION ──")
    best_symbols = df_results[df_results["total_trades"] >= 5].nlargest(5, "expected_value")
    for _, row in best_symbols.iterrows():
        ev = row["expected_value"] / 100  # Convert to decimal
        if ev > 0:
            # Compound: $10 * (1 + ev * risk_per_trade)^n = $100
            # n = log(10) / log(1 + ev * risk_per_trade)
            growth_per_trade = ev * RISK_PER_TRADE
            if growth_per_trade > 0:
                n_trades = np.log(10) / np.log(1 + growth_per_trade)
                trades_per_day = row["total_trades"] / BACKTEST_DAYS
                days_to_100 = n_trades / trades_per_day if trades_per_day > 0 else 999
                print(f"  {row['symbol']:<15} EV: {row['expected_value']:>+.3f}%/trade | ~{n_trades:.0f} trades to 10x | ~{days_to_100:.0f} days")

    # Save JSON
    output_file = DATA_DIR / f"backtest_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "config": {
                "days": BACKTEST_DAYS,
                "interval": KLINE_INTERVAL,
                "stop_pct": STOP_LOSS_PCT,
                "tp_pct": TAKE_PROFIT_PCT,
                "leverage": LEVERAGE,
                "signal_threshold": SIGNAL_THRESHOLD,
            },
            "summary": {
                "symbols_tested": len(all_results),
                "total_trades": int(total_trades),
                "avg_win_rate": round(avg_win_rate, 1),
                "avg_profit_factor": round(avg_pf, 2),
                "avg_sharpe": round(avg_sharpe, 2),
                "avg_max_drawdown": round(avg_dd, 1),
                "avg_expected_value": round(avg_ev, 4),
            },
            "results": df_results.to_dict(orient="records"),
            "failed_symbols": failed_symbols,
        }, f, indent=2)

    print(f"\n✅ Full results saved to: {output_file}")
    print("═" * 60)

    return df_results


if __name__ == "__main__":
    all_results, failed_symbols = run_backtest()
    df_results = generate_report(all_results, failed_symbols)
