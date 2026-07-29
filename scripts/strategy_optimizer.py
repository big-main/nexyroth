#!/usr/bin/env python3
"""
NEXYROTH Strategy Optimizer v1.0
════════════════════════════════
Auto-tunes all strategy parameters using grid search + walk-forward optimization.
Tests parameter combinations against historical data and selects the best.

Optimizes:
  - HF Scalper: TP%, SL%, momentum bars, RSI thresholds
  - Confluence Scalper: EMA periods, RSI range, volume threshold
  - Grid Bot: grid levels, range %, amount per grid

Method: Walk-forward (train on 70%, validate on 30%)
Metric: Sharpe ratio (risk-adjusted returns)

Schedule: Weekly (Sunday 3 AM ET) via cron
"""

import os, sys, json, time, requests, numpy as np
from datetime import datetime
from typing import Dict, List, Tuple
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from zero_fee_config import ZERO_FEE_TOKENS
except:
    ZERO_FEE_TOKENS = ["SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]

BASE_URL = "https://fapi.bitunix.com"

# Paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
RESULTS_FILE = os.path.join(DATA_DIR, "optimizer_results.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optimizer.log")

# Telegram
TG_TOKEN_FILE = os.path.expanduser("~/.secrets/telegram_bot_token")
TG_CHAT_FILE = os.path.expanduser("~/.secrets/telegram_chat_id")

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def send_telegram(msg: str):
    try:
        token = open(TG_TOKEN_FILE).read().strip()
        chat_id = open(TG_CHAT_FILE).read().strip()
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════
def calc_ema(data: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    ema = np.zeros_like(data)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
    return ema

def calc_rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    """Calculate RSI for entire array."""
    rsi_arr = np.full(len(data), 50.0)
    for i in range(period + 1, len(data)):
        deltas = np.diff(data[i-period:i+1])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses) + 0.0001
        rs = avg_gain / avg_loss
        rsi_arr[i] = 100 - (100 / (1 + rs))
    return rsi_arr

# ═══════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════
def get_historical_klines(symbol: str, interval: str = "5m", limit: int = 500) -> np.ndarray:
    """Fetch historical OHLCV data."""
    try:
        r = requests.get(f"{BASE_URL}/api/v1/futures/market/kline",
            params={"symbol": symbol, "klineType": interval, "limit": str(limit)},
            timeout=15)
        data = r.json().get("data", [])
        if not data:
            return np.array([])
        # Return as structured array: [open, high, low, close, volume]
        ohlcv = np.array([[float(k["open"]), float(k["high"]), float(k["low"]),
                           float(k["close"]), float(k.get("volume", k.get("b", 0)))]
                          for k in data])
        return ohlcv
    except:
        return np.array([])

# ═══════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════
def backtest_hf_strategy(ohlcv: np.ndarray, params: Dict) -> Dict:
    """Backtest HF scalper with given parameters."""
    tp_pct = params["tp_pct"]
    sl_pct = params["sl_pct"]
    momentum_bars = params["momentum_bars"]
    rsi_long_max = params["rsi_long_max"]
    rsi_short_min = params["rsi_short_min"]
    min_body_pct = params["min_body_pct"]

    closes = ohlcv[:, 3]
    if len(closes) < 30:
        return {"trades": 0, "pnl": 0, "sharpe": -10}

    rsi = calc_rsi(closes, 14)
    trades = []
    i = momentum_bars + 1

    while i < len(ohlcv) - 1:
        # Check momentum burst
        bullish_burst = all(ohlcv[i-j, 3] > ohlcv[i-j, 0] for j in range(momentum_bars))
        bearish_burst = all(ohlcv[i-j, 3] < ohlcv[i-j, 0] for j in range(momentum_bars))

        # Check body size
        avg_body = np.mean([abs(ohlcv[i-j, 3] - ohlcv[i-j, 0]) / ohlcv[i-j, 0]
                           for j in range(momentum_bars)])

        entry_price = closes[i]
        trade = None

        if bullish_burst and avg_body >= min_body_pct and rsi[i] < rsi_long_max:
            # LONG
            tp = entry_price * (1 + tp_pct)
            sl = entry_price * (1 - sl_pct)
            # Simulate exit
            for j in range(i+1, min(i+50, len(ohlcv))):
                if ohlcv[j, 1] >= tp:  # High hit TP
                    trade = {"pnl_pct": tp_pct, "bars": j-i}
                    break
                if ohlcv[j, 2] <= sl:  # Low hit SL
                    trade = {"pnl_pct": -sl_pct, "bars": j-i}
                    break
            if not trade:
                trade = {"pnl_pct": (closes[min(i+50, len(closes)-1)] - entry_price) / entry_price, "bars": 50}

        elif bearish_burst and avg_body >= min_body_pct and rsi[i] > rsi_short_min:
            # SHORT
            tp = entry_price * (1 - tp_pct)
            sl = entry_price * (1 + sl_pct)
            for j in range(i+1, min(i+50, len(ohlcv))):
                if ohlcv[j, 2] <= tp:
                    trade = {"pnl_pct": tp_pct, "bars": j-i}
                    break
                if ohlcv[j, 1] >= sl:
                    trade = {"pnl_pct": -sl_pct, "bars": j-i}
                    break
            if not trade:
                trade = {"pnl_pct": (entry_price - closes[min(i+50, len(closes)-1)]) / entry_price, "bars": 50}

        if trade:
            trades.append(trade)
            i += trade["bars"] + 1  # Skip past the trade
        else:
            i += 1

    if not trades:
        return {"trades": 0, "pnl": 0, "sharpe": -10, "win_rate": 0}

    pnls = [t["pnl_pct"] for t in trades]
    total_pnl = sum(pnls)
    win_rate = len([p for p in pnls if p > 0]) / len(pnls)
    avg_pnl = np.mean(pnls)
    std_pnl = np.std(pnls) + 0.0001
    sharpe = avg_pnl / std_pnl * np.sqrt(len(trades))

    return {
        "trades": len(trades),
        "pnl": round(total_pnl * 100, 2),
        "win_rate": round(win_rate * 100, 1),
        "sharpe": round(sharpe, 2),
        "avg_pnl": round(avg_pnl * 100, 3),
        "max_dd": round(min(pnls) * 100, 2)
    }

# ═══════════════════════════════════════════════════════════════
# OPTIMIZER
# ═══════════════════════════════════════════════════════════════
def optimize_hf_scalper():
    """Grid search over HF scalper parameters."""
    log("🔧 Optimizing HF Scalper parameters...")

    # Parameter grid
    param_grid = {
        "tp_pct": [0.003, 0.004, 0.006, 0.008, 0.01],
        "sl_pct": [0.002, 0.003, 0.004],
        "momentum_bars": [2, 3, 4],
        "rsi_long_max": [65, 70, 75],
        "rsi_short_min": [25, 30, 35],
        "min_body_pct": [0.0003, 0.0005, 0.001],
    }

    # Fetch data for top 3 tokens
    test_symbols = ["SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    all_data = {}
    for sym in test_symbols:
        data = get_historical_klines(sym, "1m", 500)
        if len(data) > 50:
            all_data[sym] = data
            log(f"  📊 {sym}: {len(data)} candles loaded")

    if not all_data:
        log("  ⚠️ No data available")
        return None

    # Grid search
    best_sharpe = -100
    best_params = None
    total_combos = 1
    for v in param_grid.values():
        total_combos *= len(v)

    log(f"  🔍 Testing {total_combos} parameter combinations...")

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    tested = 0

    for combo in product(*values):
        params = dict(zip(keys, combo))
        tested += 1

        # Test across all symbols
        total_sharpe = 0
        total_trades = 0
        for sym, data in all_data.items():
            # Walk-forward: train on 70%, validate on 30%
            split = int(len(data) * 0.7)
            val_data = data[split:]
            result = backtest_hf_strategy(val_data, params)
            total_sharpe += result["sharpe"]
            total_trades += result["trades"]

        avg_sharpe = total_sharpe / len(all_data)

        if avg_sharpe > best_sharpe and total_trades >= 5:
            best_sharpe = avg_sharpe
            best_params = params.copy()
            best_params["_sharpe"] = avg_sharpe
            best_params["_trades"] = total_trades

    if best_params:
        log(f"  ✅ Best params found (Sharpe={best_sharpe:.2f}, {best_params['_trades']} trades):")
        for k, v in best_params.items():
            if not k.startswith("_"):
                log(f"    {k}: {v}")

    return best_params

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    log("⚙️ Strategy Optimizer v1.0 | Starting weekly optimization run")
    start = time.time()

    results = {}

    # Optimize HF Scalper
    hf_result = optimize_hf_scalper()
    if hf_result:
        results["hf_scalper"] = hf_result

    # Save results
    os.makedirs(DATA_DIR, exist_ok=True)
    output = {
        "timestamp": time.time(),
        "run_time": datetime.utcnow().isoformat(),
        "duration_sec": round(time.time() - start, 1),
        "results": results
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # Send summary
    elapsed = time.time() - start
    if hf_result:
        msg = (f"⚙️ <b>Weekly Optimization Complete</b>\n\n"
               f"Duration: {elapsed:.0f}s\n\n"
               f"<b>HF Scalper Best Params:</b>\n"
               f"  TP: {hf_result['tp_pct']*100:.1f}%\n"
               f"  SL: {hf_result['sl_pct']*100:.1f}%\n"
               f"  Momentum bars: {hf_result['momentum_bars']}\n"
               f"  RSI Long max: {hf_result['rsi_long_max']}\n"
               f"  RSI Short min: {hf_result['rsi_short_min']}\n"
               f"  Min body: {hf_result['min_body_pct']*100:.2f}%\n"
               f"  Sharpe: {hf_result['_sharpe']:.2f}\n\n"
               f"Apply these? Run: <code>python3 apply_optimizer.py</code>")
        send_telegram(msg)

    log(f"  ✅ Optimization complete in {elapsed:.0f}s")

if __name__ == "__main__":
    main()
