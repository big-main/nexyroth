#!/usr/bin/env python3
"""
NEXYROTH × Alpaca Strategy Backtester v1.0
===========================================
Backtests all 5 Alpaca strategies using historical data from Alpaca.
Fetches up to 1 year of 5-minute bars and simulates each strategy.

Strategies tested:
  1. Momentum Scalper (EMA cross + RSI + Volume)
  2. Mean Reversion (Bollinger Band lower touch + RSI oversold)
  3. Gap-and-Go (Pre-market gap + first candle breakout)
  4. VWAP Pullback (Price near VWAP + RSI pullback zone)
  5. Opening Range Breakout (30-min ORB + volume breakout)

Output:
  - Console summary table
  - JSON results: data/alpaca_backtest_results.json
  - Markdown report: data/alpaca_backtest_report.md
"""

import os, json, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

def _s(p): return open(os.path.expanduser(p)).read().strip() if os.path.exists(os.path.expanduser(p)) else ""
API_KEY    = _s("~/.secrets/alpaca_api_key")
SECRET_KEY = _s("~/.secrets/alpaca_secret_key")
DATA_URL   = "https://data.alpaca.markets"
RESULTS_FILE = "/home/ubuntu/trading_sniper/data/alpaca_backtest_results.json"
REPORT_FILE  = "/home/ubuntu/trading_sniper/data/alpaca_backtest_report.md"

HEADERS = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
ET = ZoneInfo("America/New_York")

# ── Data Fetching ────────────────────────────────────────────────
def fetch_bars(symbol: str, days: int = 60, timeframe: str = "5Min") -> List[Dict]:
    """Fetch historical bars for backtesting."""
    end   = datetime.now(ET).replace(hour=16, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    params = {
        "timeframe": timeframe,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 10000,
        "feed":  "iex",
    }
    all_bars = []
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    while url:
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code != 200: break
            d = r.json()
            bars = d.get("bars", [])
            all_bars.extend(bars)
            next_token = d.get("next_page_token")
            if next_token:
                params = {"page_token": next_token}
            else:
                break
        except: break
    return [{"t": b["t"], "o": float(b["o"]), "h": float(b["h"]),
             "l": float(b["l"]), "c": float(b["c"]), "v": float(b["v"])} for b in all_bars]

# ── Indicators ───────────────────────────────────────────────────
def ema(values: List[float], period: int) -> List[float]:
    if len(values) < period: return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result

def rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1: return 50.0
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[:period])/period; al = sum(losses[:period])/period
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period; al = (al*(period-1)+losses[i])/period
    return 100.0 if al == 0 else 100.0 - (100.0/(1+ag/al))

def bb(closes: List[float], period: int = 20, std_mult: float = 2.0):
    if len(closes) < period: return None, None, None
    sma = sum(closes[-period:]) / period
    var = sum((c - sma)**2 for c in closes[-period:]) / period
    s = var ** 0.5
    return sma, sma + std_mult * s, sma - std_mult * s

def vwap(bars: List[Dict]) -> float:
    cv = 0; ctpv = 0
    for b in bars:
        tp = (b["h"] + b["l"] + b["c"]) / 3
        cv += b["v"]; ctpv += tp * b["v"]
    return ctpv / cv if cv > 0 else 0

def atr(bars: List[Dict], period: int = 14) -> float:
    if len(bars) < period+1: return 0.0
    trs = [max(b["h"]-b["l"], abs(b["h"]-bars[i-1]["c"]), abs(b["l"]-bars[i-1]["c"]))
           for i, b in enumerate(bars[1:], 1)]
    return sum(trs[-period:]) / period

def vol_ratio(vols: List[float], lookback: int = 20) -> float:
    if len(vols) < lookback+1: return 1.0
    avg = sum(vols[-lookback-1:-1]) / lookback
    return vols[-1] / avg if avg > 0 else 1.0

# ── Backtesting Engine ───────────────────────────────────────────
class BacktestResult:
    def __init__(self, strategy: str, symbol: str):
        self.strategy = strategy; self.symbol = symbol
        self.trades: List[Dict] = []

    def add_trade(self, entry, exit_price, direction, tp, sl, entry_idx, exit_idx):
        if direction == "LONG":
            pnl_pct = (exit_price - entry) / entry * 100
        else:
            pnl_pct = (entry - exit_price) / entry * 100
        self.trades.append({
            "entry": entry, "exit": exit_price, "direction": direction,
            "tp": tp, "sl": sl, "pnl_pct": round(pnl_pct, 3),
            "win": pnl_pct > 0, "entry_idx": entry_idx, "exit_idx": exit_idx
        })

    def summary(self) -> Dict:
        if not self.trades:
            return {"strategy": self.strategy, "symbol": self.symbol, "trades": 0,
                    "win_rate": 0, "avg_pnl": 0, "total_pnl": 0, "max_dd": 0, "sharpe": 0}
        wins = [t for t in self.trades if t["win"]]
        pnls = [t["pnl_pct"] for t in self.trades]
        total_pnl = sum(pnls)
        # Max drawdown
        equity = 100.0
        peak = 100.0; max_dd = 0.0
        for p in pnls:
            equity *= (1 + p/100)
            if equity > peak: peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd: max_dd = dd
        # Sharpe (simplified, daily risk-free = 0)
        import statistics
        sharpe = (sum(pnls)/len(pnls)) / statistics.stdev(pnls) if len(pnls) > 1 else 0
        return {
            "strategy": self.strategy, "symbol": self.symbol,
            "trades": len(self.trades), "wins": len(wins),
            "win_rate": round(len(wins)/len(self.trades)*100, 1),
            "avg_pnl": round(total_pnl/len(self.trades), 3),
            "total_pnl": round(total_pnl, 2),
            "max_dd": round(max_dd, 2),
            "sharpe": round(sharpe, 3),
        }

def simulate_exit(bars: List[Dict], entry_idx: int, entry: float,
                  tp: float, sl: float, direction: str, max_bars: int = 48) -> tuple:
    """Simulate trade exit: TP, SL, or timeout."""
    for i in range(entry_idx + 1, min(entry_idx + max_bars, len(bars))):
        b = bars[i]
        if direction == "LONG":
            if b["h"] >= tp: return tp, i, "TP"
            if b["l"] <= sl: return sl, i, "SL"
        else:
            if b["l"] <= tp: return tp, i, "TP"
            if b["h"] >= sl: return sl, i, "SL"
    # Timeout: exit at last bar close
    last = min(entry_idx + max_bars, len(bars) - 1)
    return bars[last]["c"], last, "TIMEOUT"

# ── Strategy 1: Momentum Scalper ────────────────────────────────
def backtest_momentum(bars: List[Dict]) -> BacktestResult:
    result = BacktestResult("Momentum Scalper", "")
    closes = [b["c"] for b in bars]; vols = [b["v"] for b in bars]
    in_trade = False
    for i in range(30, len(bars)):
        if in_trade: continue
        c_slice = closes[:i+1]; v_slice = vols[:i+1]
        ef = ema(c_slice, 9); es = ema(c_slice, 21)
        if len(ef) < 2 or len(es) < 2: continue
        if ef[-1] > es[-1] and ef[-2] <= es[-2]:  # Bullish cross
            r = rsi(c_slice)
            vr = vol_ratio(v_slice)
            if 25 <= r <= 75 and vr >= 0.8:
                entry = closes[i]
                tp = round(entry * 1.004, 4)
                sl = round(entry * 0.998, 4)
                exit_price, exit_idx, reason = simulate_exit(bars, i, entry, tp, sl, "LONG")
                result.add_trade(entry, exit_price, "LONG", tp, sl, i, exit_idx)
                in_trade = True
        else:
            in_trade = False
    return result

# ── Strategy 2: Mean Reversion ───────────────────────────────────
def backtest_mean_reversion(bars: List[Dict]) -> BacktestResult:
    result = BacktestResult("Mean Reversion", "")
    closes = [b["c"] for b in bars]; vols = [b["v"] for b in bars]
    in_trade = False
    for i in range(25, len(bars)):
        if in_trade: continue
        c_slice = closes[:i+1]; v_slice = vols[:i+1]
        mid, upper, lower = bb(c_slice)
        if lower is None: continue
        r = rsi(c_slice)
        vr = vol_ratio(v_slice)
        price = closes[i]
        if price <= lower and r < 35 and vr >= 1.2:
            entry = price
            tp = round(mid, 4)
            at = atr(bars[:i+1])
            sl = round(entry - 1.5 * at, 4)
            exit_price, exit_idx, reason = simulate_exit(bars, i, entry, tp, sl, "LONG")
            result.add_trade(entry, exit_price, "LONG", tp, sl, i, exit_idx)
            in_trade = True
        else:
            in_trade = False
    return result

# ── Strategy 3: VWAP Pullback ────────────────────────────────────
def backtest_vwap_pullback(bars: List[Dict]) -> BacktestResult:
    result = BacktestResult("VWAP Pullback", "")
    closes = [b["c"] for b in bars]
    in_trade = False
    for i in range(20, len(bars)):
        if in_trade: continue
        c_slice = closes[:i+1]
        v = vwap(bars[:i+1])
        r = rsi(c_slice)
        price = closes[i]
        if v == 0: continue
        dist = abs(price - v) / v
        recent_above = sum(1 for c in closes[max(0,i-5):i] if c > v)
        if dist <= 0.0015 and 40 <= r <= 55 and recent_above >= 3:
            entry = price
            tp = round(v * 1.01, 4)
            sl = round(v * 0.995, 4)
            exit_price, exit_idx, reason = simulate_exit(bars, i, entry, tp, sl, "LONG")
            result.add_trade(entry, exit_price, "LONG", tp, sl, i, exit_idx)
            in_trade = True
        else:
            in_trade = False
    return result

# ── Strategy 4: Opening Range Breakout ──────────────────────────
def backtest_orb(bars: List[Dict]) -> BacktestResult:
    result = BacktestResult("ORB", "")
    closes = [b["c"] for b in bars]; vols = [b["v"] for b in bars]
    in_trade = False
    for i in range(8, len(bars)):
        if in_trade: continue
        orb_bars = bars[max(0,i-12):max(0,i-6)]  # Approximate 30-min window
        if len(orb_bars) < 6: continue
        orb_high = max(b["h"] for b in orb_bars)
        orb_low  = min(b["l"] for b in orb_bars)
        orb_range = orb_high - orb_low
        if orb_range <= 0: continue
        vr = vol_ratio(vols[:i+1])
        price = closes[i]
        if vr >= 2.0:
            if price > orb_high:
                entry = price; tp = round(orb_high + 2*orb_range, 4); sl = round(orb_low, 4)
                exit_price, exit_idx, reason = simulate_exit(bars, i, entry, tp, sl, "LONG")
                result.add_trade(entry, exit_price, "LONG", tp, sl, i, exit_idx)
                in_trade = True
            elif price < orb_low:
                entry = price; tp = round(orb_low - 2*orb_range, 4); sl = round(orb_high, 4)
                exit_price, exit_idx, reason = simulate_exit(bars, i, entry, tp, sl, "SHORT")
                result.add_trade(entry, exit_price, "SHORT", tp, sl, i, exit_idx)
                in_trade = True
        else:
            in_trade = False
    return result

# ── Main ─────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("NEXYROTH × Alpaca Strategy Backtester v1.0")
    print(f"Running on 60 days of 5-min bars | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    # Test symbols — representative across market caps
    test_symbols = ["NVDA", "TSLA", "AAPL", "MSFT", "AMD", "SPY", "QQQ", "TQQQ", "PLTR", "COIN"]
    strategies = [
        ("Momentum Scalper", backtest_momentum),
        ("Mean Reversion",   backtest_mean_reversion),
        ("VWAP Pullback",    backtest_vwap_pullback),
        ("ORB",              backtest_orb),
    ]

    all_results = []
    strategy_totals = {s[0]: {"trades": 0, "wins": 0, "total_pnl": 0.0, "max_dd": 0.0} for s in strategies}

    for symbol in test_symbols:
        print(f"\n📊 Fetching {symbol} (60d × 5min)...")
        bars = fetch_bars(symbol, days=60)
        if len(bars) < 50:
            print(f"  ⚠️ Insufficient data ({len(bars)} bars) — skipping")
            continue
        print(f"  ✅ {len(bars)} bars loaded")

        for strat_name, strat_fn in strategies:
            result = strat_fn(bars)
            result.symbol = symbol
            s = result.summary()
            all_results.append(s)
            t = strategy_totals[strat_name]
            t["trades"] += s["trades"]; t["wins"] += s.get("wins", 0)
            t["total_pnl"] += s["total_pnl"]
            t["max_dd"] = max(t["max_dd"], s["max_dd"])
            if s["trades"] > 0:
                print(f"  {strat_name:22s} | {s['trades']:3d} trades | WR={s['win_rate']:5.1f}% | "
                      f"Avg={s['avg_pnl']:+.3f}% | Total={s['total_pnl']:+.2f}% | DD={s['max_dd']:.2f}%")

    # Aggregate by strategy
    print("\n" + "=" * 65)
    print("STRATEGY AGGREGATE SUMMARY (across all symbols)")
    print("=" * 65)
    print(f"{'Strategy':<24} {'Trades':>7} {'Win%':>7} {'Avg%':>8} {'Total%':>9} {'MaxDD%':>8}")
    print("-" * 65)
    for strat_name, totals in strategy_totals.items():
        if totals["trades"] == 0:
            print(f"{strat_name:<24} {'0':>7} {'—':>7} {'—':>8} {'—':>9} {'—':>8}")
            continue
        wr = totals["wins"] / totals["trades"] * 100
        avg = totals["total_pnl"] / totals["trades"]
        print(f"{strat_name:<24} {totals['trades']:>7} {wr:>6.1f}% {avg:>+7.3f}% "
              f"{totals['total_pnl']:>+8.2f}% {totals['max_dd']:>7.2f}%")

    # Save results
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "results": all_results,
                   "totals": strategy_totals}, f, indent=2)
    print(f"\n✅ Results saved: {RESULTS_FILE}")

    # Generate markdown report
    with open(REPORT_FILE, "w") as f:
        f.write(f"# NEXYROTH Alpaca Strategy Backtest Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M ET')}\n")
        f.write(f"**Period:** 60 days of 5-minute bars\n")
        f.write(f"**Symbols:** {', '.join(test_symbols)}\n\n")
        f.write("## Strategy Summary\n\n")
        f.write("| Strategy | Trades | Win Rate | Avg PnL | Total PnL | Max Drawdown |\n")
        f.write("|----------|--------|----------|---------|-----------|-------------|\n")
        for strat_name, totals in strategy_totals.items():
            if totals["trades"] == 0:
                f.write(f"| {strat_name} | 0 | — | — | — | — |\n")
                continue
            wr = totals["wins"] / totals["trades"] * 100
            avg = totals["total_pnl"] / totals["trades"]
            f.write(f"| {strat_name} | {totals['trades']} | {wr:.1f}% | {avg:+.3f}% | "
                    f"{totals['total_pnl']:+.2f}% | {totals['max_dd']:.2f}% |\n")
        f.write("\n## Per-Symbol Results\n\n")
        f.write("| Symbol | Strategy | Trades | Win Rate | Avg PnL | Total PnL |\n")
        f.write("|--------|----------|--------|----------|---------|----------|\n")
        for r in all_results:
            if r["trades"] > 0:
                f.write(f"| {r['symbol']} | {r['strategy']} | {r['trades']} | "
                        f"{r['win_rate']}% | {r['avg_pnl']:+.3f}% | {r['total_pnl']:+.2f}% |\n")
    print(f"✅ Report saved: {REPORT_FILE}")

if __name__ == "__main__":
    main()
