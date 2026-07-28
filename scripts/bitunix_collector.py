#!/usr/bin/env python3
"""
NEXYROTH Bitunix Intraday Collector v1.0
Runs every 15 minutes. Appends a snapshot to today's JSON log:
  /home/ubuntu/trading_sniper/data/bitunix_YYYY-MM-DD.json

Each snapshot captures per-symbol:
- Price, 24h%, OHLC, volume
- Funding rate
- BEST ENTRY signal (neg FR + near daily low)
- Distance from daily low/high
"""
import requests, json, os, time
from datetime import datetime, timezone

BITUNIX_API = "https://fapi.bitunix.com"
DATA_DIR    = "/home/ubuntu/trading_sniper/data"
LOG_FILE    = "/home/ubuntu/trading_sniper/bitunix_collector.log"
WATCHLIST   = "/home/ubuntu/trading_sniper/watchlist.json"

os.makedirs(DATA_DIR, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_watchlist_config():
    """Load symbols + EV tier metadata from watchlist.json."""
    try:
        with open(WATCHLIST) as f:
            data = json.load(f)
        symbols = list(dict.fromkeys(
            data.get("priority_watchlist", []) +
            data.get("added_high_value", [])
        ))
        # Build EV tier lookup: symbol -> {tier, ev_boost}
        ev_lookup = {}
        for tier_name, tier_data in data.get("ev_tiers", {}).items():
            for sym in tier_data.get("symbols", []):
                ev_lookup[sym] = {
                    "ev_tier": tier_name,
                    "ev_boost": tier_data.get("ev_boost", 0.0),
                }
        avoid = set(data.get("avoid_symbols", []))
        return symbols, ev_lookup, avoid
    except:
        return (["BTCUSDT","ETHUSDT","XRPUSDT","DOGEUSDT",
                 "HYPEUSDT","AGLDUSDT","JUPUSDT","AVAXUSDT",
                 "AAVEUSDT","WIFUSDT","LTCUSDT","NEARUSDT",
                 "FARTCOINUSDT","DOTUSDT","TIAUSDT","PIPPINUSDT"],
                {}, set())

def load_symbols():
    symbols, _, _ = load_watchlist_config()
    return symbols

def get_tickers():
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/tickers", timeout=12)
        return {t["symbol"]: t for t in r.json().get("data", [])}
    except Exception as e:
        log(f"Ticker fetch error: {e}")
        return {}

def get_funding_rate(symbol):
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/funding_rate",
                         params={"symbol": symbol}, timeout=5)
        return float(r.json().get("data", {}).get("fundingRate", 0)) * 100
    except:
        return 0.0

def classify_signal(pct, fr, dist_from_low, vol):
    """Return signal direction and setup label."""
    if fr < -15:
        return "LONG", "🔥 FUNDING SQUEEZE"
    elif fr < 0 and dist_from_low < 3:
        return "LONG", "✅ BEST ENTRY"
    elif fr < 0 and dist_from_low < 6:
        return "LONG", "⚡ NEG FUNDING + LOW"
    elif fr < 0:
        return "LONG", "⚡ NEG FUNDING"
    elif pct >= 8 and fr < 5:
        return "LONG", "🚀 MOMENTUM"
    elif fr > 20:
        return "SHORT", "📉 LONGS OVEREXTENDED"
    elif pct <= -8:
        return "SHORT", "💀 DUMP"
    elif pct >= 5:
        return "LONG", "📈 MOMENTUM"
    else:
        return "WATCH", "—"

def collect():
    now_utc = datetime.now(timezone.utc)
    today   = now_utc.strftime("%Y-%m-%d")
    data_file = os.path.join(DATA_DIR, f"bitunix_{today}.json")

    log(f"Collecting Bitunix snapshot...")

    symbols, ev_lookup, avoid_set = load_watchlist_config()
    tickers = get_tickers()
    if not tickers:
        log("No ticker data — aborting.")
        return

    # Also grab top 10 movers dynamically
    all_t = list(tickers.values())
    def pct_chg(t):
        try:
            l, o = float(t.get("lastPrice",0)), float(t.get("open",0))
            return abs(((l-o)/o)*100) if o else 0
        except: return 0
    top_movers = [t["symbol"] for t in sorted(all_t, key=pct_chg, reverse=True)
                  if float(t.get("quoteVol",0))/1e6 >= 0.5][:10]

    scan_symbols = list(dict.fromkeys(symbols + top_movers))

    snap_symbols = []
    best_entries = []

    for sym in scan_symbols:
        t = tickers.get(sym)
        if not t:
            continue
        try:
            price = float(t.get("lastPrice", 0))
            open_ = float(t.get("open", 0))
            high  = float(t.get("high", 0))
            low   = float(t.get("low", 0))
            pct   = ((price - open_) / open_) * 100 if open_ else 0
            vol   = float(t.get("quoteVol", 0)) / 1e6
            dist_low  = ((price - low)  / low)  * 100 if low  else 0
            dist_high = ((high - price) / high) * 100 if high else 0

            fr = get_funding_rate(sym)
            signal, setup = classify_signal(pct, fr, dist_low, vol)

            ev_meta = ev_lookup.get(sym, {"ev_tier": "TIER_4_NEUTRAL", "ev_boost": 0.0})
            is_avoid = sym in avoid_set
            # Suppress BEST ENTRY label for avoid symbols — flag them instead
            if is_avoid and "BEST" in setup:
                setup = f"⚠️ AVOID ({setup.replace('✅ ', '')})"
                signal = "AVOID"

            entry = {
                "symbol":     sym,
                "price":      price,
                "open":       open_,
                "high":       high,
                "low":        low,
                "pct":        round(pct, 4),
                "fr":         round(fr, 6),
                "vol_m":      round(vol, 2),
                "dist_low":   round(dist_low, 2),
                "dist_high":  round(dist_high, 2),
                "signal":     signal,
                "setup":      setup,
                "is_priority": sym in symbols,
                "ev_tier":    ev_meta["ev_tier"],
                "ev_boost":   ev_meta["ev_boost"],
                "is_avoid":   is_avoid,
            }
            snap_symbols.append(entry)
            if signal in ("LONG", "SHORT") and "BEST" in setup or "SQUEEZE" in setup:
                best_entries.append(entry)

            time.sleep(0.06)
        except Exception as e:
            log(f"Error on {sym}: {e}")

    snapshot = {
        "ts":          now_utc.isoformat(),
        "ts_local":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbols_scanned": len(snap_symbols),
        "best_entries":    len(best_entries),
        "symbols":         snap_symbols,
    }

    # Load or create day log
    if os.path.exists(data_file):
        with open(data_file) as f:
            day_log = json.load(f)
    else:
        day_log = {"date": today, "snapshots": []}

    day_log["snapshots"].append(snapshot)

    with open(data_file, "w") as f:
        json.dump(day_log, f, indent=2)

    best_str = ", ".join(f"{e['symbol']}({e['setup']})" for e in best_entries[:5]) or "none"
    log(f"Saved {len(snap_symbols)} symbols | BEST ENTRIES: {best_str} → {data_file}")

if __name__ == "__main__":
    collect()
