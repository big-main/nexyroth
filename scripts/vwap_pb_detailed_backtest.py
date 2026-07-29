#!/usr/bin/env python3
"""
NEXYROTH × VWAP Pullback Detailed Backtest v1.0
================================================
Full multi-trade simulation over 180 days of 5-min bars.
Allows multiple trades per symbol (no cooldown limit).
Tracks equity curve, per-trade log, drawdown, Sharpe, Sortino.

Symbols: 15 liquid stocks + ETFs
Period:  180 days of 5-min bars (~21,000 bars per symbol)
"""

import os, json, requests, statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Tuple

def _s(p): return open(os.path.expanduser(p)).read().strip() if os.path.exists(os.path.expanduser(p)) else ""
API_KEY    = _s("~/.secrets/alpaca_api_key")
SECRET_KEY = _s("~/.secrets/alpaca_secret_key")
DATA_URL   = "https://data.alpaca.markets"
RESULTS_FILE = "/home/ubuntu/trading_sniper/data/vwap_pb_backtest_detailed.json"
REPORT_FILE  = "/home/ubuntu/trading_sniper/data/vwap_pb_backtest_report.md"

HEADERS = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
ET = ZoneInfo("America/New_York")

# ── Strategy Parameters ──────────────────────────────────────────
VWAP_TOUCH_PCT  = 0.0015   # Within 0.15% of VWAP
RSI_MIN         = 40
RSI_MAX         = 55
TP_PCT          = 0.010    # +1.0% TP
SL_PCT          = 0.005    # -0.5% SL
MIN_BARS_ABOVE  = 3        # Must have been above VWAP in last 5 bars
MAX_HOLD_BARS   = 48       # Max 4 hours hold (48 × 5min)
COOLDOWN_BARS   = 6        # 30-min cooldown per symbol after trade

SYMBOLS = [
    "NVDA","AMD","TSLA","AAPL","MSFT","AMZN","META","GOOGL",
    "PLTR","COIN","SPY","QQQ","TQQQ","IWM","SOFI",
]

# ── Data Fetching ────────────────────────────────────────────────
def fetch_bars(symbol: str, days: int = 180) -> List[Dict]:
    end   = datetime.now(ET).replace(hour=16, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    params = {
        "timeframe": "5Min",
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 10000,
        "feed":  "iex",
    }
    all_bars = []
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    page = 0
    while url:
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code != 200: break
            d = r.json()
            bars = d.get("bars", [])
            all_bars.extend(bars)
            page += 1
            next_token = d.get("next_page_token")
            if next_token:
                params = {"page_token": next_token}
            else:
                break
        except Exception as e:
            print(f"    Fetch error page {page}: {e}"); break
    return [{"t": b["t"], "o": float(b["o"]), "h": float(b["h"]),
             "l": float(b["l"]), "c": float(b["c"]), "v": float(b["v"])} for b in all_bars]

# ── Indicators ───────────────────────────────────────────────────
def calc_vwap_rolling(bars: List[Dict], window: int = 78) -> List[float]:
    """Rolling intraday VWAP using a sliding window of `window` bars."""
    vwaps = []
    for i in range(len(bars)):
        start = max(0, i - window + 1)
        w = bars[start:i+1]
        cv = sum(b["v"] for b in w)
        ctpv = sum((b["h"]+b["l"]+b["c"])/3 * b["v"] for b in w)
        vwaps.append(ctpv / cv if cv > 0 else bars[i]["c"])
    return vwaps

def calc_rsi_series(closes: List[float], period: int = 14) -> List[float]:
    rsis = [50.0] * period
    if len(closes) < period + 1: return rsis
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[:period])/period
    al = sum(losses[:period])/period
    rsis.append(100.0 if al == 0 else 100.0 - (100.0/(1+ag/al)))
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period
        al = (al*(period-1)+losses[i])/period
        rsis.append(100.0 if al == 0 else 100.0 - (100.0/(1+ag/al)))
    return rsis

def calc_vol_ratio_series(vols: List[float], lookback: int = 20) -> List[float]:
    ratios = [1.0] * lookback
    for i in range(lookback, len(vols)):
        avg = sum(vols[i-lookback:i]) / lookback
        ratios.append(vols[i] / avg if avg > 0 else 1.0)
    return ratios

# ── Backtest Engine ──────────────────────────────────────────────
def backtest_vwap_pullback(symbol: str, bars: List[Dict]) -> Dict:
    if len(bars) < 100:
        return {"symbol": symbol, "trades": [], "error": "insufficient data"}

    closes = [b["c"] for b in bars]
    vols   = [b["v"] for b in bars]
    vwaps  = calc_vwap_rolling(bars, window=78)
    rsis   = calc_rsi_series(closes)
    vratios = calc_vol_ratio_series(vols)

    trades = []
    in_trade = False
    trade_entry_bar = 0
    cooldown_until = 0

    for i in range(20, len(bars)):
        if in_trade:
            # Check exit conditions
            b = bars[i]
            t = trades[-1]
            entry = t["entry"]
            tp = t["tp"]; sl = t["sl"]
            if b["h"] >= tp:
                t["exit"] = tp; t["exit_bar"] = i; t["exit_reason"] = "TP"
                t["pnl_pct"] = round((tp - entry) / entry * 100, 4)
                t["hold_bars"] = i - trade_entry_bar
                in_trade = False; cooldown_until = i + COOLDOWN_BARS
            elif b["l"] <= sl:
                t["exit"] = sl; t["exit_bar"] = i; t["exit_reason"] = "SL"
                t["pnl_pct"] = round((sl - entry) / entry * 100, 4)
                t["hold_bars"] = i - trade_entry_bar
                in_trade = False; cooldown_until = i + COOLDOWN_BARS
            elif (i - trade_entry_bar) >= MAX_HOLD_BARS:
                t["exit"] = closes[i]; t["exit_bar"] = i; t["exit_reason"] = "TIMEOUT"
                t["pnl_pct"] = round((closes[i] - entry) / entry * 100, 4)
                t["hold_bars"] = i - trade_entry_bar
                in_trade = False; cooldown_until = i + COOLDOWN_BARS
            continue

        if i < cooldown_until: continue

        price = closes[i]
        vwap  = vwaps[i]
        rsi_v = rsis[i] if i < len(rsis) else 50.0
        vr    = vratios[i] if i < len(vratios) else 1.0

        if vwap == 0: continue
        dist = abs(price - vwap) / vwap

        # Check if price was above VWAP in recent bars (pullback condition)
        recent_above = sum(1 for j in range(max(0,i-5), i) if closes[j] > vwaps[j])

        if (dist <= VWAP_TOUCH_PCT and
            RSI_MIN <= rsi_v <= RSI_MAX and
            recent_above >= MIN_BARS_ABOVE and
            vr < 1.5):  # Volume declining on pullback

            entry = price
            tp = round(entry * (1 + TP_PCT), 4)
            sl = round(entry * (1 - SL_PCT), 4)
            trades.append({
                "symbol": symbol, "entry_bar": i, "entry": entry,
                "tp": tp, "sl": sl, "vwap": round(vwap, 4),
                "rsi": round(rsi_v, 2), "vol_ratio": round(vr, 3),
                "dist_pct": round(dist * 100, 4),
                "exit": None, "exit_bar": None, "exit_reason": None,
                "pnl_pct": None, "hold_bars": None,
                "timestamp": bars[i]["t"]
            })
            in_trade = True
            trade_entry_bar = i

    # Close any open trade at last bar
    if in_trade and trades:
        t = trades[-1]
        t["exit"] = closes[-1]; t["exit_bar"] = len(bars)-1
        t["exit_reason"] = "EOD"; t["hold_bars"] = len(bars)-1 - trade_entry_bar
        t["pnl_pct"] = round((closes[-1] - t["entry"]) / t["entry"] * 100, 4)

    return {"symbol": symbol, "bars_total": len(bars), "trades": trades}

# ── Statistics ───────────────────────────────────────────────────
def compute_stats(all_trades: List[Dict]) -> Dict:
    if not all_trades:
        return {"trades": 0}
    pnls = [t["pnl_pct"] for t in all_trades if t["pnl_pct"] is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)

    # Equity curve
    equity = 100.0; peak = 100.0; max_dd = 0.0
    equity_curve = [100.0]
    for p in pnls:
        equity *= (1 + p/100)
        equity_curve.append(round(equity, 4))
        if equity > peak: peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd: max_dd = dd

    # Sharpe (annualized, assuming 252 trading days × 78 bars/day)
    sharpe = 0.0
    if len(pnls) > 1:
        avg = sum(pnls)/len(pnls)
        std = statistics.stdev(pnls)
        sharpe = (avg / std) * (252 * 78 / len(pnls)) ** 0.5 if std > 0 else 0

    # Sortino (downside deviation only)
    sortino = 0.0
    if losses:
        down_std = statistics.stdev(losses) if len(losses) > 1 else abs(losses[0])
        avg = sum(pnls)/len(pnls)
        sortino = (avg / down_std) * (252 * 78 / len(pnls)) ** 0.5 if down_std > 0 else 0

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss   = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Avg hold time
    hold_bars = [t["hold_bars"] for t in all_trades if t["hold_bars"] is not None]
    avg_hold = sum(hold_bars)/len(hold_bars) if hold_bars else 0

    # Exit reason breakdown
    reasons = {}
    for t in all_trades:
        r = t.get("exit_reason", "?")
        reasons[r] = reasons.get(r, 0) + 1

    return {
        "trades":        len(pnls),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins)/len(pnls)*100, 2) if pnls else 0,
        "avg_pnl":       round(total_pnl/len(pnls), 4) if pnls else 0,
        "total_pnl":     round(total_pnl, 4),
        "gross_profit":  round(gross_profit, 4),
        "gross_loss":    round(gross_loss, 4),
        "profit_factor": round(profit_factor, 3),
        "max_drawdown":  round(max_dd, 4),
        "sharpe":        round(sharpe, 4),
        "sortino":       round(sortino, 4),
        "avg_hold_bars": round(avg_hold, 1),
        "avg_hold_min":  round(avg_hold * 5, 1),
        "final_equity":  round(equity_curve[-1], 4),
        "exit_reasons":  reasons,
        "best_trade":    round(max(pnls), 4) if pnls else 0,
        "worst_trade":   round(min(pnls), 4) if pnls else 0,
    }

# ── Main ─────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("NEXYROTH × VWAP Pullback Detailed Backtest v1.0")
    print(f"Period: 180 days | Symbols: {len(SYMBOLS)} | Timeframe: 5-min")
    print(f"TP: +{TP_PCT*100:.1f}%  SL: -{SL_PCT*100:.1f}%  Max Hold: {MAX_HOLD_BARS*5}min")
    print(f"VWAP Touch: ±{VWAP_TOUCH_PCT*100:.2f}%  RSI: {RSI_MIN}–{RSI_MAX}")
    print("=" * 70)

    all_results = []
    all_trades  = []

    for symbol in SYMBOLS:
        print(f"\n📊 {symbol}: Fetching 180d × 5min bars...")
        bars = fetch_bars(symbol, days=180)
        if len(bars) < 200:
            print(f"  ⚠️ Only {len(bars)} bars — skipping"); continue
        print(f"  ✅ {len(bars):,} bars loaded — running backtest...")
        result = backtest_vwap_pullback(symbol, bars)
        trades = [t for t in result["trades"] if t["pnl_pct"] is not None]
        stats  = compute_stats(trades)
        result["stats"] = stats
        all_results.append(result)
        all_trades.extend(trades)
        if stats.get("trades", 0) > 0:
            print(f"  Trades: {stats['trades']:3d} | WR: {stats['win_rate']:5.1f}% | "
                  f"Avg: {stats['avg_pnl']:+.4f}% | PF: {stats['profit_factor']:.3f} | "
                  f"DD: {stats['max_drawdown']:.2f}% | Sharpe: {stats['sharpe']:.3f}")
        else:
            print(f"  No trades generated")

    # Aggregate stats
    agg = compute_stats(all_trades)
    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS — VWAP Pullback (all symbols combined)")
    print("=" * 70)
    print(f"  Total Trades:    {agg.get('trades', 0)}")
    print(f"  Win Rate:        {agg.get('win_rate', 0):.2f}%")
    print(f"  Avg PnL/Trade:   {agg.get('avg_pnl', 0):+.4f}%")
    print(f"  Total PnL:       {agg.get('total_pnl', 0):+.4f}%")
    print(f"  Profit Factor:   {agg.get('profit_factor', 0):.3f}")
    print(f"  Max Drawdown:    {agg.get('max_drawdown', 0):.4f}%")
    print(f"  Sharpe Ratio:    {agg.get('sharpe', 0):.4f}")
    print(f"  Sortino Ratio:   {agg.get('sortino', 0):.4f}")
    print(f"  Avg Hold Time:   {agg.get('avg_hold_min', 0):.1f} min")
    print(f"  Final Equity:    ${agg.get('final_equity', 100):.2f} (started $100)")
    print(f"  Best Trade:      {agg.get('best_trade', 0):+.4f}%")
    print(f"  Worst Trade:     {agg.get('worst_trade', 0):+.4f}%")
    print(f"  Exit Reasons:    {agg.get('exit_reasons', {})}")

    # Per-symbol summary table
    print("\n" + "-" * 70)
    print(f"{'Symbol':<8} {'Trades':>7} {'WR%':>7} {'Avg%':>8} {'PF':>7} {'DD%':>7} {'Sharpe':>8}")
    print("-" * 70)
    for r in all_results:
        s = r.get("stats", {})
        if s.get("trades", 0) == 0: continue
        print(f"{r['symbol']:<8} {s['trades']:>7} {s['win_rate']:>6.1f}% "
              f"{s['avg_pnl']:>+7.4f}% {s['profit_factor']:>7.3f} "
              f"{s['max_drawdown']:>6.2f}% {s['sharpe']:>8.4f}")

    # Save results
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "strategy": "VWAP Pullback",
            "params": {"vwap_touch_pct": VWAP_TOUCH_PCT, "rsi_min": RSI_MIN,
                       "rsi_max": RSI_MAX, "tp_pct": TP_PCT, "sl_pct": SL_PCT,
                       "max_hold_bars": MAX_HOLD_BARS, "cooldown_bars": COOLDOWN_BARS},
            "aggregate": agg,
            "per_symbol": [{
                "symbol": r["symbol"],
                "bars": r["bars_total"],
                "stats": r.get("stats", {}),
            } for r in all_results],
            "all_trades": all_trades,
        }, f, indent=2)
    print(f"\n✅ Full results saved: {RESULTS_FILE}")

    # Markdown report
    with open(REPORT_FILE, "w") as f:
        f.write("# VWAP Pullback Strategy — Detailed Backtest Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M ET')}\n")
        f.write(f"**Period:** 180 days of 5-minute bars\n")
        f.write(f"**Symbols:** {', '.join(SYMBOLS)}\n\n")
        f.write("## Strategy Parameters\n\n")
        f.write(f"| Parameter | Value |\n|-----------|-------|\n")
        f.write(f"| VWAP Touch Zone | ±{VWAP_TOUCH_PCT*100:.2f}% |\n")
        f.write(f"| RSI Range | {RSI_MIN}–{RSI_MAX} |\n")
        f.write(f"| Take Profit | +{TP_PCT*100:.1f}% |\n")
        f.write(f"| Stop Loss | -{SL_PCT*100:.1f}% |\n")
        f.write(f"| Max Hold | {MAX_HOLD_BARS*5} minutes |\n")
        f.write(f"| Cooldown | {COOLDOWN_BARS*5} minutes |\n\n")
        f.write("## Aggregate Performance\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        for k, v in agg.items():
            if k not in ("exit_reasons",):
                f.write(f"| {k.replace('_',' ').title()} | {v} |\n")
        f.write("\n## Per-Symbol Results\n\n")
        f.write("| Symbol | Trades | Win Rate | Avg PnL | Profit Factor | Max DD | Sharpe |\n")
        f.write("|--------|--------|----------|---------|---------------|--------|--------|\n")
        for r in all_results:
            s = r.get("stats", {})
            if s.get("trades", 0) == 0: continue
            f.write(f"| {r['symbol']} | {s['trades']} | {s['win_rate']}% | "
                    f"{s['avg_pnl']:+.4f}% | {s['profit_factor']:.3f} | "
                    f"{s['max_drawdown']:.2f}% | {s['sharpe']:.4f} |\n")
        f.write("\n## Exit Reason Breakdown\n\n")
        f.write("| Reason | Count |\n|--------|-------|\n")
        for reason, count in agg.get("exit_reasons", {}).items():
            f.write(f"| {reason} | {count} |\n")
    print(f"✅ Report saved: {REPORT_FILE}")

if __name__ == "__main__":
    main()
