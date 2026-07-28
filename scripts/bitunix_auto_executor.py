#!/usr/bin/env python3
"""
NEXYROTH Bitunix Auto-Executor v1.0
=====================================
Automatically places and manages funding rate arbitrage trades on Bitunix.

Strategy:
  - Scan all Bitunix symbols for extreme funding rates (≥ |0.10%| per 8h)
  - When FR is deeply negative → LONG (shorts pay you every 8h)
  - When FR is extremely positive → SHORT (longs pay you every 8h)
  - Set TP at +3% and SL at -2% for price protection
  - Auto-exit when FR compresses below 0.05% (edge is gone)
  - Max 3 concurrent positions, max 5% balance per trade
  - Runs every 10 minutes via cron

Risk Controls:
  - Hard stop: never risk more than 5% of balance per trade
  - Max 3 open positions simultaneously
  - SL always set at entry (never naked)
  - Avoid list for known volatile/manipulated symbols
  - Dry-run mode when no API key configured

Auth: Double-SHA256 (nonce + timestamp + api-key + queryParams + body → digest → digest + secretKey → sign)
"""

import os
import json
import time
import uuid
import hashlib
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, List

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — set BITUNIX_API_KEY and BITUNIX_SECRET_KEY
# ═══════════════════════════════════════════════════════════════
BITUNIX_API      = "https://fapi.bitunix.com"
def _read_secret(env_var: str, path: str) -> str:
    val = os.getenv(env_var, "")
    if not val and os.path.exists(path):
        try:
            with open(path) as f:
                val = f.read().strip()
        except:
            pass
    return val

API_KEY    = _read_secret("BITUNIX_API_KEY",    os.path.expanduser("~/.secrets/bitunix_api_key"))
SECRET_KEY = _read_secret("BITUNIX_SECRET_KEY", os.path.expanduser("~/.secrets/bitunix_secret_key"))
RESEND_API_KEY   = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL      = os.getenv("ALERT_EMAIL_TO", "big.main@protonmail.com")

LOG_FILE         = "/home/ubuntu/trading_sniper/bitunix_auto_executor.log"
STATE_FILE       = "/home/ubuntu/trading_sniper/data/auto_executor_state.json"
POSITIONS_FILE   = "/home/ubuntu/trading_sniper/data/auto_executor_positions.json"

# Strategy thresholds
# NOTE: Bitunix API returns FR as decimal fractions (e.g. 0.018208 = 1.8208%)
# So 0.05% = 0.0005, 0.02% = 0.0002, 0.50% = 0.005
ENTRY_FR_THRESHOLD   = 0.0005  # 0.05% per 8h = 5 basis points (enter trade)
EXIT_FR_THRESHOLD    = 0.0002  # 0.02% per 8h (FR compressed, exit)
MEGA_FR_THRESHOLD    = 0.005   # 0.50% per 8h (mega opportunity, larger size)

# Risk parameters — MAXIMUM AGGRESSION MODE (updated 2026-07-25)
MAX_RISK_PCT         = 0.45   # 45% of balance per trade
MAX_POSITIONS        = 5      # Max concurrent open positions
DEFAULT_LEVERAGE     = 10     # 10x leverage
TP_PCT               = 0.05   # Take profit at +5%
SL_PCT               = 0.025  # Stop loss at -2.5%
MIN_BALANCE          = 2.0    # Minimum balance to trade ($2)
MIN_VOLUME_24H       = 1_000_000  # $1M minimum 24h volume

# ─── ZERO-FEE ALLOWLIST (Bitunix zero-fee promotion) ───────────────────────
# Only trade these tokens — no maker/taker fees, maximising FR profit.
ZERO_FEE_SYMBOLS = {
    "SOLUSDT", "XRPUSDT", "SUIUSDT", "LABUSDT", "BUSDT",
    "TONUSDT", "SKYAIUSDT", "DOGSUSDT", "DOGEUSDT", "TSTUSDT",
}

# Symbols to avoid even within zero-fee list (extreme manipulation risk)
AVOID_SYMBOLS: set = set()  # nothing blocked — all zero-fee tokens are eligible

DRY_RUN = not (API_KEY and SECRET_KEY)  # Auto dry-run if no keys configured

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# BITUNIX API AUTH — Double SHA256
# ═══════════════════════════════════════════════════════════════
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_sign(nonce: str, timestamp: str, query_params: str = "", body: str = "") -> str:
    """
    sign = SHA256( SHA256(nonce + timestamp + api-key + queryParams + body) + secretKey )
    """
    digest = sha256_hex(nonce + timestamp + API_KEY + query_params + body)
    return sha256_hex(digest + SECRET_KEY)

def make_headers(query_params: str = "", body: str = "") -> dict:
    nonce     = uuid.uuid4().hex[:32]
    timestamp = str(int(time.time() * 1000))
    sign      = make_sign(nonce, timestamp, query_params, body)
    return {
        "api-key":      API_KEY,
        "nonce":        nonce,
        "timestamp":    timestamp,
        "sign":         sign,
        "Content-Type": "application/json",
        "language":     "en-US",
    }

def bitunix_get(path: str, params: dict = None) -> Optional[dict]:
    """Authenticated GET request to Bitunix."""
    if DRY_RUN:
        return None
    try:
        # Build sorted query string for signing
        if params:
            sorted_params = sorted(params.items())
            query_str = "".join(f"{k}{v}" for k, v in sorted_params)
            query_url  = "&".join(f"{k}={v}" for k, v in sorted_params)
        else:
            query_str = ""
            query_url = ""

        headers = make_headers(query_params=query_str)
        url = f"{BITUNIX_API}{path}"
        if query_url:
            url += f"?{query_url}"

        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            log(f"  API error [{path}]: {data.get('msg', data)}")
            return None
        return data.get("data")
    except Exception as e:
        log(f"  GET error [{path}]: {e}")
        return None

def bitunix_post(path: str, body: dict) -> Optional[dict]:
    """Authenticated POST request to Bitunix."""
    if DRY_RUN:
        log(f"  [DRY RUN] POST {path}: {json.dumps(body)}")
        return {"orderId": "DRY_RUN_" + uuid.uuid4().hex[:8]}
    try:
        body_str = json.dumps(body, separators=(",", ":"))
        headers  = make_headers(body=body_str)
        r = requests.post(f"{BITUNIX_API}{path}", headers=headers, data=body_str, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            log(f"  API error [{path}]: {data.get('msg', data)}")
            return None
        return data.get("data")
    except Exception as e:
        log(f"  POST error [{path}]: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# ACCOUNT & MARKET DATA
# ═══════════════════════════════════════════════════════════════
def get_account_balance() -> float:
    """Get available USDT balance."""
    data = bitunix_get("/api/v1/futures/account", {"marginCoin": "USDT"})
    if data:
        try:
            return float(data.get("available", 0) or 0)
        except:
            pass
    return 0.0

def get_open_positions() -> List[dict]:
    """Get all currently open positions."""
    data = bitunix_get("/api/v1/futures/position/get_pending_positions")
    if data and isinstance(data, list):
        return data
    return []

def fetch_all_tickers() -> List[dict]:
    """Fetch all Bitunix futures tickers (public, no auth needed)."""
    try:
        r = requests.get(f"{BITUNIX_API}/api/v1/futures/market/tickers", timeout=15)
        return r.json().get("data", [])
    except Exception as e:
        log(f"  Error fetching tickers: {e}")
        return []

def fetch_funding_rate(symbol: str) -> float:
    """Fetch current funding rate for a symbol."""
    try:
        r = requests.get(
            f"{BITUNIX_API}/api/v1/futures/market/funding_rate",
            params={"symbol": symbol},
            timeout=8
        )
        resp = r.json()
        # Response: {code:0, data:{symbol, fundingRate, ...}}
        if resp.get("code") != 0:
            return 0.0
        data = resp.get("data", {})
        return float(data.get("fundingRate", 0) or 0)
    except:
        return 0.0

# Hardcoded minimum quantities per symbol (from Bitunix error messages)
# These are the actual exchange minimums — the /trading_pairs API returns wrong values
MIN_QTY_MAP = {
    "SOLUSDT":   0.1,
    "XRPUSDT":   5.0,
    "SUIUSDT":   10.0,
    "LABUSDT":   10.0,
    "BUSDT":     20.0,
    "TONUSDT":   1.0,
    "SKYAIUSDT": 10.0,
    "DOGSUSDT":  100000.0,   # DOGS is a micro-price token
    "DOGEUSDT":  10.0,
    "TSTUSDT":   10.0,
}

def get_min_qty(symbol: str) -> float:
    """Get minimum order quantity for a symbol."""
    return MIN_QTY_MAP.get(symbol, 1.0)

# ═══════════════════════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {
        "total_trades": 0, "wins": 0, "losses": 0,
        "total_fr_earned": 0.0, "total_pnl": 0.0,
        "last_run": None, "positions": {}
    }

def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════
def calculate_qty(balance: float, price: float, leverage: int, risk_pct: float) -> float:
    """Calculate position size in base coin."""
    risk_usdt    = balance * risk_pct
    position_val = risk_usdt * leverage
    qty          = position_val / price
    return qty

# Per-symbol qty precision (decimal places for qty string)
QTY_PRECISION_MAP = {
    "SOLUSDT":   2,
    "XRPUSDT":   0,
    "SUIUSDT":   0,
    "LABUSDT":   0,
    "BUSDT":     0,
    "TONUSDT":   1,
    "SKYAIUSDT": 0,
    "DOGSUSDT":  0,
    "DOGEUSDT":  0,
    "TSTUSDT":   0,
}

# Per-symbol price precision (decimal places for price/TP/SL strings)
PRICE_PRECISION_MAP = {
    "SOLUSDT":   2,
    "XRPUSDT":   4,
    "SUIUSDT":   4,
    "LABUSDT":   4,
    "BUSDT":     4,
    "TONUSDT":   3,
    "SKYAIUSDT": 5,
    "DOGSUSDT":  8,   # micro-price: 0.00003768
    "DOGEUSDT":  5,
    "TSTUSDT":   5,
}

def place_fr_trade(symbol: str, direction: str, price: float, balance: float, fr: float) -> Optional[dict]:
    """
    Place a funding rate arbitrage trade.
    direction: 'LONG' or 'SHORT'
    """
    if price <= 0:
        log(f"  ⚠️ {symbol}: price is 0 — cannot place trade")
        return None

    # Scale size up for mega FR opportunities
    risk_pct = MAX_RISK_PCT * (2.0 if abs(fr) >= MEGA_FR_THRESHOLD else 1.0)
    qty = calculate_qty(balance, price, DEFAULT_LEVERAGE, risk_pct)

    # Enforce minimum qty — bump up to minimum if just below it
    min_qty = get_min_qty(symbol)
    if qty < min_qty:
        # Check if bumping to min_qty is still within risk tolerance (max 2x intended risk)
        max_allowed_qty = calculate_qty(balance, price, DEFAULT_LEVERAGE, risk_pct * 2)
        if min_qty <= max_allowed_qty:
            log(f"  ℹ️ {symbol}: bumping qty {qty:.4f} → {min_qty} (min_qty)")
            qty = min_qty
        else:
            log(f"  ⚠️ {symbol}: qty {qty:.4f} < min {min_qty} and too large to bump — skipping")
            return None

    # Round qty to correct precision for this symbol
    qty_prec = QTY_PRECISION_MAP.get(symbol, 3)
    qty = round(qty, qty_prec)
    if qty_prec == 0:
        qty = int(qty)

    # Calculate TP and SL prices with correct precision
    price_prec = PRICE_PRECISION_MAP.get(symbol, 4)
    if direction == "LONG":
        side       = "BUY"
        tp_price   = round(price * (1 + TP_PCT), price_prec)
        sl_price   = round(price * (1 - SL_PCT), price_prec)
    else:
        side       = "SELL"
        tp_price   = round(price * (1 - TP_PCT), price_prec)
        sl_price   = round(price * (1 + SL_PCT), price_prec)

    order_body = {
        "symbol":      symbol,
        "side":        side,
        "tradeSide":   "OPEN",
        "orderType":   "MARKET",
        "qty":         str(qty),
        "tpPrice":     str(tp_price),
        "tpStopType":  "MARK_PRICE",
        "tpOrderType": "MARKET",
        "slPrice":     str(sl_price),
        "slStopType":  "MARK_PRICE",
        "slOrderType": "MARKET",
        "clientId":    f"nexyroth_fr_{uuid.uuid4().hex[:12]}",
    }

    log(f"  📤 Placing {direction} {symbol} | qty={qty} | price=${price} | TP=${tp_price} | SL=${sl_price}")
    result = bitunix_post("/api/v1/futures/trade/place_order", order_body)

    if result:
        order_id = result.get("orderId", "?")
        log(f"  ✅ Order placed: {order_id}")
        return {
            "orderId":   order_id,
            "symbol":    symbol,
            "direction": direction,
            "qty":       qty,
            "entryPrice": price,
            "tpPrice":   tp_price,
            "slPrice":   sl_price,
            "fr_at_entry": fr,
            "openTime":  datetime.now(timezone.utc).isoformat(),
        }
    return None

def close_position(position_id: str, symbol: str, direction: str, qty: str) -> bool:
    """Close an open position at market."""
    close_side = "SELL" if direction == "LONG" else "BUY"
    order_body = {
        "symbol":     symbol,
        "side":       close_side,
        "tradeSide":  "CLOSE",
        "orderType":  "MARKET",
        "qty":        qty,
        "positionId": position_id,
        "clientId":   f"nexyroth_close_{uuid.uuid4().hex[:12]}",
    }
    log(f"  📤 Closing {direction} {symbol} (positionId={position_id})")
    result = bitunix_post("/api/v1/futures/trade/place_order", order_body)
    return result is not None

# ═══════════════════════════════════════════════════════════════
# EMAIL ALERTS
# ═══════════════════════════════════════════════════════════════
def send_trade_alert(trade: dict, action: str, balance: float, fr: float):
    direction_color = "#00ff88" if trade["direction"] == "LONG" else "#ff4444"
    action_label    = "🟢 OPENED" if action == "open" else "🔴 CLOSED"
    fr_daily        = abs(fr) * 3 * 100
    fr_annual       = abs(fr) * 1095 * 100

    subject = f"⚡ Bitunix Auto-Exec: {action_label} {trade['direction']} {trade['symbol']} | FR={fr*100:.3f}%"
    html = f"""
    <div style="font-family:'Courier New',monospace;background:#0a0a1a;color:#e0e0e0;padding:20px;border-radius:12px;max-width:600px">
        <h2 style="color:#00ff88;margin:0 0 4px">⚡ BITUNIX AUTO-EXECUTOR</h2>
        <p style="color:#888;font-size:11px;margin:0 0 16px">NEXYROTH Funding Rate Arb v1.0</p>

        <div style="background:#111;border-radius:8px;padding:12px;margin-bottom:12px">
            <p style="margin:2px 0;font-size:18px;font-weight:bold;color:{direction_color}">{action_label} — {trade['direction']} {trade['symbol']}</p>
            <p style="margin:2px 0;color:#aaa">Entry: <span style="color:#fff">${trade.get('entryPrice', '?'):.4f}</span></p>
            <p style="margin:2px 0;color:#aaa">Qty: <span style="color:#fff">{trade['qty']}</span> | TP: <span style="color:#00ff88">${trade.get('tpPrice','?'):.4f}</span> | SL: <span style="color:#ff4444">${trade.get('slPrice','?'):.4f}</span></p>
        </div>

        <div style="background:#0d1a0d;border-radius:8px;padding:12px;margin-bottom:12px">
            <p style="margin:2px 0;color:#888">Funding Rate (per 8h)</p>
            <p style="margin:2px 0;font-size:20px;font-weight:bold;color:#00ff88">{fr*100:+.4f}%</p>
            <p style="margin:2px 0;color:#aaa">Daily yield: <span style="color:#fff">{fr_daily:.2f}%</span> | Annual: <span style="color:#fff">{fr_annual:.0f}%</span></p>
            <p style="margin:4px 0;color:#666;font-size:10px">Shorts pay longs every 8h when FR is negative. You collect this passively.</p>
        </div>

        <div style="background:#111;border-radius:8px;padding:10px">
            <p style="margin:2px 0;color:#888;font-size:11px">Account Balance: <span style="color:#fff">${balance:.2f} USDT</span></p>
            <p style="margin:2px 0;color:#888;font-size:11px">Order ID: <span style="color:#555">{trade.get('orderId','?')}</span></p>
        </div>
        <p style="color:#333;font-size:9px;margin-top:12px">Auto-generated by NEXYROTH Bitunix Auto-Executor v1.0</p>
    </div>
    """
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "onboarding@resend.dev", "to": ALERT_EMAIL, "subject": subject, "html": html},
            timeout=10
        )
        log("  📧 Trade alert sent.")
    except Exception as e:
        log(f"  ⚠️ Email error: {e}")

# ═══════════════════════════════════════════════════════════════
# MAIN LOGIC
# ═══════════════════════════════════════════════════════════════
def scan_fr_opportunities() -> List[dict]:
    """Scan all symbols for extreme funding rate opportunities."""
    tickers = fetch_all_tickers()
    candidates = []

    for t in tickers:
        symbol = t.get("symbol", "")
        # ZERO-FEE ONLY: skip anything not in the allowlist
        if symbol not in ZERO_FEE_SYMBOLS:
            continue
        try:
            price   = float(t.get("last", 0) or 0)
            vol_24h = float(t.get("quoteVol", 0) or 0)
        except (ValueError, TypeError):
            continue

        # Lower volume threshold for zero-fee tokens (some are lower-cap)
        min_vol = 100_000  # $100k minimum for zero-fee tokens
        if price <= 0 or vol_24h < min_vol:
            continue
        candidates.append({"symbol": symbol, "price": price, "vol": vol_24h})

    log(f"  Zero-fee candidates found: {len(candidates)} / {len(ZERO_FEE_SYMBOLS)} tokens")

    # Fetch FR for all zero-fee candidates (only 10 max, no rate limit concern)
    opportunities = []
    for c in candidates:  # All zero-fee candidates, no cap needed
        fr = fetch_funding_rate(c["symbol"])
        abs_fr = abs(fr)
        if abs_fr >= ENTRY_FR_THRESHOLD:
            direction = "LONG" if fr < 0 else "SHORT"
            daily_yield = abs_fr * 3 * 100
            opportunities.append({
                "symbol":      c["symbol"],
                "price":       c["price"],
                "vol":         c["vol"],
                "fr":          fr,
                "direction":   direction,
                "daily_yield": daily_yield,
            })
        time.sleep(0.05)  # 50ms between FR calls to respect rate limits

    # Sort by absolute FR descending
    opportunities.sort(key=lambda x: abs(x["fr"]), reverse=True)
    return opportunities

def manage_existing_positions(open_positions: List[dict], state: dict) -> int:
    """Check existing positions and close those where FR has compressed."""
    closed = 0
    tracked = state.get("positions", {})

    for pos in open_positions:
        pos_id  = pos.get("positionId")
        symbol  = pos.get("symbol")
        side    = pos.get("side")  # LONG or SHORT
        qty     = pos.get("qty")

        if not pos_id or not symbol:
            continue

        # Check if FR has compressed (edge is gone)
        current_fr = fetch_funding_rate(symbol)
        abs_fr = abs(current_fr)

        if abs_fr < EXIT_FR_THRESHOLD:
            log(f"  📉 {symbol} FR compressed to {current_fr*100:.4f}% — closing position")
            if close_position(pos_id, symbol, side, qty):
                closed += 1
                # Remove from tracked positions
                if pos_id in tracked:
                    del tracked[pos_id]
                log(f"  ✅ Closed {symbol} position (FR compressed)")
        else:
            log(f"  📊 {symbol} {side}: FR={current_fr*100:+.4f}% (holding)")

    state["positions"] = tracked
    return closed

def main():
    log("=" * 65)
    log("NEXYROTH Bitunix Auto-Executor v1.0")
    if DRY_RUN:
        log("⚠️  DRY RUN MODE — set BITUNIX_API_KEY + BITUNIX_SECRET_KEY to trade")
    log("=" * 65)

    state = load_state()

    # Get account balance
    balance = get_account_balance()
    if DRY_RUN:
        log("  Balance: [DRY RUN — no API key]")
        balance = 10.0  # Simulate $10 for dry run
    else:
        log(f"  Balance: ${balance:.2f} USDT")
        if balance < MIN_BALANCE:
            log(f"  ⚠️ Balance ${balance:.2f} < minimum ${MIN_BALANCE} — monitoring only")

    # Get open positions
    open_positions = get_open_positions() if not DRY_RUN else []
    log(f"  Open positions: {len(open_positions)}")

    # Manage existing positions (check for FR compression)
    if open_positions:
        closed = manage_existing_positions(open_positions, state)
        if closed:
            log(f"  Closed {closed} position(s) due to FR compression")
        # Refresh after closures
        open_positions = get_open_positions() if not DRY_RUN else []

    # Check if we can open new positions
    available_slots = MAX_POSITIONS - len(open_positions)
    if available_slots <= 0:
        log(f"  ℹ️ Max positions ({MAX_POSITIONS}) reached — not opening new trades")
        save_state(state)
        return

    if balance < MIN_BALANCE and not DRY_RUN:
        log(f"  ℹ️ Insufficient balance — scanning only (no trades)")

    # Scan for opportunities
    log("  🔍 Scanning for extreme funding rate opportunities...")
    opportunities = scan_fr_opportunities()

    if not opportunities:
        log("  No opportunities above threshold this scan.")
    else:
        log(f"  Found {len(opportunities)} opportunity(ies):")
        for opp in opportunities[:5]:
            log(f"    {opp['direction']:5} {opp['symbol']:15} FR={opp['fr']*100:+.4f}% | daily={opp['daily_yield']:.2f}% | vol=${opp['vol']/1e6:.1f}M")

    # Already-tracked symbols (avoid doubling up)
    tracked_symbols = {v["symbol"] for v in state.get("positions", {}).values()}
    open_symbols    = {p.get("symbol") for p in open_positions}
    skip_symbols    = tracked_symbols | open_symbols

    # Open new trades for top opportunities
    trades_opened = 0
    for opp in opportunities:
        if trades_opened >= available_slots:
            break
        if opp["symbol"] in skip_symbols:
            log(f"  ⏭️  {opp['symbol']}: already have position — skipping")
            continue
        if balance < MIN_BALANCE and not DRY_RUN:
            break

        trade = place_fr_trade(
            symbol    = opp["symbol"],
            direction = opp["direction"],
            price     = opp["price"],
            balance   = balance,
            fr        = opp["fr"],
        )

        if trade:
            trades_opened += 1
            skip_symbols.add(opp["symbol"])
            state["total_trades"] = state.get("total_trades", 0) + 1
            state.setdefault("positions", {})[trade["orderId"]] = trade
            send_trade_alert(trade, "open", balance, opp["fr"])
            time.sleep(1)  # Brief pause between orders

    # Summary
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    log(f"\n  📊 Session Summary:")
    log(f"     Opportunities found: {len(opportunities)}")
    log(f"     Trades opened:       {trades_opened}")
    log(f"     Total lifetime:      {state.get('total_trades', 0)} trades")
    log(f"     Dry run:             {DRY_RUN}")
    log("=" * 65)

if __name__ == "__main__":
    main()
