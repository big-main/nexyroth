#!/usr/bin/env python3
"""
NEXYROTH FOMO Copy Trader v1.0
================================
Monitors top Hyperliquid leaderboard traders via FOMO.trade intelligence.
When a top trader opens a position on a zero-fee Bitunix token, copies it
automatically using 2 reserved position slots.

Strategy:
- Fetches top 20 traders from Hyperliquid leaderboard (by 7-day PnL + ROI)
- Polls each trader's positions every 60 seconds
- Detects NEW positions on SOL/XRP/SUI/DOGE/TON (overlap with Bitunix zero-fee)
- Filters: position size > $200, leverage <= 20x, not already in a copy slot
- Copies to Bitunix using copy_slot_1 and copy_slot_2
- TP +5%, SL -2.5% (same as executor)
- Exits when leader closes their position OR TP/SL hits

Run: python3 fomo_copy_trader.py
Cron: */1 * * * * (every minute for fast signal detection)
"""

import os, sys, json, time, uuid, hashlib, requests, logging
from datetime import datetime, timezone
from pathlib import Path

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BITUNIX_API       = 'https://fapi.bitunix.com'
HL_INFO_URL       = 'https://api.hyperliquid.xyz/info'
HL_LEADERBOARD_URL = 'https://stats-data.hyperliquid.xyz/Mainnet/leaderboard'

# Bitunix zero-fee tokens that overlap with Hyperliquid
ZERO_FEE_MAP = {
    'SOL':  'SOLUSDT',
    'XRP':  'XRPUSDT',
    'SUI':  'SUIUSDT',
    'DOGE': 'DOGEUSDT',
    'TON':  'TONUSDT',
}

# Copy trade settings
MAX_COPY_SLOTS       = 2       # Reserve 2 of 5 executor slots for copy trades
COPY_LEVERAGE        = 5       # 5x leverage on copy trades
COPY_RISK_PCT        = 0.30    # 30% of available balance per copy trade
TP_PCT               = 0.05    # Take profit at +5%
SL_PCT               = 0.025   # Stop loss at -2.5%
MIN_LEADER_SIZE_USD  = 200     # Ignore leader positions < $200 notional
MAX_LEADER_LEVERAGE  = 20      # Ignore if leader uses > 20x (too risky to copy)
TOP_N_TRADERS        = 20      # Monitor top N traders from leaderboard
POLL_INTERVAL_SEC    = 60      # Poll each trader every 60 seconds
MIN_TRADER_7D_PNL    = 5000    # Only follow traders with >$5k 7-day PnL
MIN_TRADER_ROI_7D    = 0.10    # Only follow traders with >10% 7-day ROI

# Per-symbol minimum qty (Bitunix exchange minimums)
MIN_QTY_MAP = {
    'SOLUSDT':  0.1,
    'XRPUSDT':  5.0,
    'SUIUSDT':  10.0,
    'DOGEUSDT': 10.0,
    'TONUSDT':  1.0,
}

# Price precision (decimal places) per symbol
PRICE_PREC_MAP = {
    'SOLUSDT':  2,
    'XRPUSDT':  4,
    'SUIUSDT':  4,
    'DOGEUSDT': 5,
    'TONUSDT':  4,
}

# ─── PATHS ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.parent
STATE_FILE  = BASE_DIR / 'data' / 'fomo_copy_state.json'
LOG_FILE    = BASE_DIR / 'fomo_copy_trader.log'

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)

def log(msg):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logging.info(f'[{ts}] {msg}')

# ─── STATE ─────────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        'copy_positions': {},    # order_id -> {symbol, leader_addr, leader_size, entry, side, tp, sl, opened_at}
        'leader_snapshots': {},  # addr -> {coin -> {szi, entryPx, leverage}}
        'top_traders': [],       # list of {addr, name, pnl_7d, roi_7d}
        'last_leaderboard_update': 0,
    }

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ─── BITUNIX AUTH ───────────────────────────────────────────────────────────────
def _load_keys():
    ak = open(os.path.expanduser('~/.secrets/bitunix_api_key')).read().strip()
    sk = open(os.path.expanduser('~/.secrets/bitunix_secret_key')).read().strip()
    return ak, sk

API_KEY, SECRET_KEY = _load_keys()

def sha256_hex(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def make_headers(query_params='', body=''):
    nonce = uuid.uuid4().hex[:32]
    ts = str(int(time.time() * 1000))
    digest = sha256_hex(nonce + ts + API_KEY + query_params + body)
    sign = sha256_hex(digest + SECRET_KEY)
    return {
        'api-key': API_KEY, 'nonce': nonce, 'timestamp': ts, 'sign': sign,
        'Content-Type': 'application/json', 'language': 'en-US'
    }

def bitunix_get(path, params=None):
    if params:
        sp = sorted(params.items())
        qs = ''.join(f'{k}{v}' for k, v in sp)
        qu = '&'.join(f'{k}={v}' for k, v in sp)
    else:
        qs = qu = ''
    headers = make_headers(query_params=qs)
    url = f'{BITUNIX_API}{path}' + (f'?{qu}' if qu else '')
    r = requests.get(url, headers=headers, timeout=15)
    d = r.json()
    return d.get('data') if d.get('code') == 0 else None

def bitunix_post(path, body_dict):
    body = json.dumps(body_dict, separators=(',', ':'))
    headers = make_headers(body=body)
    url = f'{BITUNIX_API}{path}'
    r = requests.post(url, headers=headers, data=body, timeout=15)
    return r.json()

# ─── HYPERLIQUID ────────────────────────────────────────────────────────────────
def hl_post(payload):
    try:
        r = requests.post(HL_INFO_URL, json=payload, timeout=15)
        return r.json()
    except Exception as e:
        log(f'  HL API error: {e}')
        return None

def get_top_traders():
    """Fetch top traders from Hyperliquid leaderboard, filter by 7-day performance."""
    try:
        r = requests.get(HL_LEADERBOARD_URL, timeout=15)
        rows = r.json().get('leaderboardRows', [])
    except Exception as e:
        log(f'  Leaderboard fetch error: {e}')
        return []

    scored = []
    for row in rows:
        addr = row.get('ethAddress', '')
        name = row.get('displayName') or addr[:10]
        acct_val = float(row.get('accountValue', 0) or 0)

        pnl_7d = roi_7d = pnl_30d = 0.0
        for window, perf in row.get('windowPerformances', []):
            pnl = float(perf.get('pnl', 0) or 0)
            roi = float(perf.get('roi', 0) or 0)
            if window == 'week':
                pnl_7d, roi_7d = pnl, roi
            elif window == 'month':
                pnl_30d = pnl

        # Filter: meaningful 7-day performance
        if pnl_7d < MIN_TRADER_7D_PNL:
            continue
        if roi_7d < MIN_TRADER_ROI_7D:
            continue
        # Filter: account must have real value (not dust)
        if acct_val < 1000:
            continue

        scored.append({
            'addr': addr,
            'name': name,
            'pnl_7d': pnl_7d,
            'roi_7d': roi_7d,
            'pnl_30d': pnl_30d,
            'acct_val': acct_val,
        })

    # Sort by 7-day PnL descending, take top N
    scored.sort(key=lambda x: x['pnl_7d'], reverse=True)
    return scored[:TOP_N_TRADERS]

def get_trader_positions(addr):
    """Get current open positions for a Hyperliquid wallet."""
    data = hl_post({'type': 'clearinghouseState', 'user': addr})
    if not data:
        return {}
    positions = {}
    for pos in data.get('assetPositions', []):
        p = pos.get('position', {})
        coin = p.get('coin', '')
        szi = float(p.get('szi', 0) or 0)
        if szi == 0:
            continue
        entry_px = float(p.get('entryPx', 0) or 0)
        leverage = float(p.get('leverage', {}).get('value', 1) or 1)
        notional = abs(szi) * entry_px
        positions[coin] = {
            'szi': szi,
            'entryPx': entry_px,
            'leverage': leverage,
            'notional': notional,
            'side': 'LONG' if szi > 0 else 'SHORT',
        }
    return positions

# ─── BITUNIX TRADING ────────────────────────────────────────────────────────────
def get_balance():
    bal = bitunix_get('/api/v1/futures/account', {'marginCoin': 'USDT'})
    return float(bal.get('available', 0)) if bal else 0.0

def get_current_price(symbol):
    r = requests.get(f'{BITUNIX_API}/api/v1/futures/market/tickers', timeout=8)
    for t in r.json().get('data', []):
        if t.get('symbol') == symbol:
            p = t.get('last') or t.get('lastPrice') or 0
            return float(p) if p else 0.0
    return 0.0

def get_open_positions():
    pos = bitunix_get('/api/v1/futures/position/get_pending_positions', {'marginCoin': 'USDT'})
    positions = pos if isinstance(pos, list) else (pos.get('positionList', []) if pos else [])
    return [p for p in positions if float(p.get('qty', 0) or 0) > 0]

def place_copy_trade(symbol, side, balance, leader_info):
    """Place a copy trade on Bitunix."""
    price = get_current_price(symbol)
    if not price:
        log(f'  ⚠️  Cannot get price for {symbol} — skipping')
        return None

    price_prec = PRICE_PREC_MAP.get(symbol, 4)
    min_qty = MIN_QTY_MAP.get(symbol, 1.0)

    # Calculate qty
    risk_usd = balance * COPY_RISK_PCT
    notional = risk_usd * COPY_LEVERAGE
    qty = notional / price

    # Enforce minimum
    if qty < min_qty:
        if qty >= min_qty * 0.5:
            qty = min_qty
            log(f'  ℹ️  {symbol}: bumping qty {qty:.4f} → {min_qty} (min_qty)')
        else:
            log(f'  ⚠️  {symbol}: qty {qty:.4f} too far below min {min_qty} — skipping')
            return None

    # Round qty to appropriate precision
    if min_qty >= 100:
        qty = int(qty)
    elif min_qty >= 1:
        qty = round(qty, 0)
    else:
        qty = round(qty, 2)

    # TP/SL
    if side == 'BUY':
        tp_price = round(price * (1 + TP_PCT), price_prec)
        sl_price = round(price * (1 - SL_PCT), price_prec)
    else:
        tp_price = round(price * (1 - TP_PCT), price_prec)
        sl_price = round(price * (1 + SL_PCT), price_prec)

    order_body = {
        'symbol': symbol,
        'qty': str(qty),
        'side': side,
        'tradeSide': 'OPEN',
        'orderType': 'MARKET',
        'leverage': str(COPY_LEVERAGE),
        'marginCoin': 'USDT',
        'marginMode': 'ISOLATED',
        'tpPrice': str(tp_price),
        'slPrice': str(sl_price),
    }

    resp = bitunix_post('/api/v1/futures/trade/place_order', order_body)
    if resp.get('code') == 0:
        order_id = resp['data'].get('orderId', 'unknown')
        log(f'  ✅ COPY TRADE: {side} {symbol} | qty={qty} | entry≈${price:.{price_prec}f} | TP=${tp_price} | SL=${sl_price}')
        log(f'     Leader: {leader_info["name"]} ({leader_info["addr"][:12]}...) | Leader size=${leader_info["notional"]:.0f} | Leader lev={leader_info["leverage"]:.0f}x')
        log(f'     Order ID: {order_id}')
        return order_id
    else:
        log(f'  ❌ Order failed for {symbol}: {resp}')
        return None

def close_position(symbol, side, qty):
    """Close a copy trade position."""
    close_side = 'SELL' if side == 'BUY' else 'BUY'
    order_body = {
        'symbol': symbol,
        'qty': str(qty),
        'side': close_side,
        'tradeSide': 'CLOSE',
        'orderType': 'MARKET',
        'marginCoin': 'USDT',
    }
    resp = bitunix_post('/api/v1/futures/trade/place_order', order_body)
    if resp.get('code') == 0:
        log(f'  🔴 CLOSED copy position: {symbol} (leader exited)')
        return True
    else:
        log(f'  ⚠️  Failed to close {symbol}: {resp}')
        return False

def send_alert(subject, body):
    """Send email alert via Resend."""
    try:
        resend_key = os.environ.get('RESEND_API_KEY', '')
        if not resend_key:
            return
        requests.post('https://api.resend.com/emails', json={
            'from': 'NEXYROTH <alerts@nexyroth.com>',
            'to': ['big.main@protonmail.com'],
            'subject': subject,
            'text': body,
        }, headers={'Authorization': f'Bearer {resend_key}'}, timeout=10)
    except Exception:
        pass

# ─── MAIN LOOP ──────────────────────────────────────────────────────────────────
def main():
    log('=' * 70)
    log('NEXYROTH FOMO Copy Trader v1.0')
    log('=' * 70)

    state = load_state()
    now = time.time()

    # ── Step 1: Refresh top traders list every 30 minutes ──────────────────────
    if now - state.get('last_leaderboard_update', 0) > 1800:
        log('  📊 Refreshing top trader leaderboard...')
        traders = get_top_traders()
        if traders:
            state['top_traders'] = traders
            state['last_leaderboard_update'] = now
            log(f'  ✅ Tracking {len(traders)} top traders:')
            for i, t in enumerate(traders[:5]):
                log(f'     #{i+1} {t["name"]} | 7d PnL=${t["pnl_7d"]:,.0f} | ROI={t["roi_7d"]*100:.1f}%')
        else:
            log('  ⚠️  Failed to refresh leaderboard — using cached list')
        save_state(state)

    traders = state.get('top_traders', [])
    if not traders:
        log('  ⚠️  No traders in watchlist — run again to populate')
        return

    # ── Step 2: Get current Bitunix state ──────────────────────────────────────
    balance = get_balance()
    open_positions = get_open_positions()
    open_symbols = {p.get('symbol') for p in open_positions}
    copy_positions = state.get('copy_positions', {})

    # Count active copy slots
    active_copy_slots = len([oid for oid, cp in copy_positions.items()
                              if cp.get('symbol') in open_symbols])
    available_copy_slots = MAX_COPY_SLOTS - active_copy_slots

    log(f'  Balance: ${balance:.2f} | Open positions: {len(open_positions)} | Copy slots: {active_copy_slots}/{MAX_COPY_SLOTS}')

    # ── Step 3: Check if any copy positions need to be closed (leader exited) ──
    for oid, cp in list(copy_positions.items()):
        sym = cp.get('symbol')
        if sym not in open_symbols:
            # Already closed by TP/SL — clean up state
            log(f'  ℹ️  Copy position {sym} already closed (TP/SL hit) — removing from state')
            del copy_positions[oid]
            continue

        # Check if leader still has the position
        leader_addr = cp.get('leader_addr')
        leader_coin = cp.get('leader_coin')
        leader_positions = get_trader_positions(leader_addr)

        if leader_coin not in leader_positions:
            # Leader closed their position — we close ours too
            log(f'  🔔 Leader {cp.get("leader_name", "?")} closed {leader_coin} — closing our copy position')
            # Find our position qty
            for p in open_positions:
                if p.get('symbol') == sym:
                    qty = float(p.get('qty', 0))
                    our_side = 'BUY' if p.get('side') == 'BUY' else 'SELL'
                    close_position(sym, our_side, qty)
                    send_alert(
                        f'NEXYROTH: Copy trade closed — {sym}',
                        f'Leader {cp.get("leader_name")} exited {leader_coin}.\nOur position {sym} closed.'
                    )
                    break
            del copy_positions[oid]

    state['copy_positions'] = copy_positions
    save_state(state)

    # ── Step 4: Scan top traders for new positions ──────────────────────────────
    if available_copy_slots <= 0:
        log(f'  ℹ️  All {MAX_COPY_SLOTS} copy slots filled — monitoring only')
        # Still update snapshots
        for trader in traders[:5]:
            addr = trader['addr']
            positions = get_trader_positions(addr)
            state['leader_snapshots'][addr] = positions
        save_state(state)
        return

    log(f'  🔍 Scanning {len(traders)} top traders for new positions...')
    new_trades_placed = 0

    for trader in traders:
        if available_copy_slots <= 0:
            break

        addr = trader['addr']
        name = trader['name']
        prev_snapshot = state.get('leader_snapshots', {}).get(addr, {})

        # Get current positions
        current_positions = get_trader_positions(addr)
        state.setdefault('leader_snapshots', {})[addr] = current_positions

        # Detect NEW positions (in current but not in previous snapshot)
        for coin, pos in current_positions.items():
            if coin in prev_snapshot:
                continue  # Not new

            # Check if this coin maps to a Bitunix zero-fee token
            bitunix_sym = ZERO_FEE_MAP.get(coin)
            if not bitunix_sym:
                continue  # Not a zero-fee token

            # Filter checks
            if pos['notional'] < MIN_LEADER_SIZE_USD:
                log(f'  ⏭️  {name} opened {coin} but size ${pos["notional"]:.0f} < ${MIN_LEADER_SIZE_USD} min — skipping')
                continue

            if pos['leverage'] > MAX_LEADER_LEVERAGE:
                log(f'  ⏭️  {name} opened {coin} at {pos["leverage"]:.0f}x leverage > {MAX_LEADER_LEVERAGE}x max — skipping')
                continue

            if bitunix_sym in open_symbols:
                log(f'  ⏭️  Already have {bitunix_sym} position — skipping copy')
                continue

            # All checks passed — place copy trade
            side = 'SELL' if pos['side'] == 'SHORT' else 'BUY'
            log(f'  🎯 SIGNAL: {name} opened {pos["side"]} {coin} | size=${pos["notional"]:.0f} | lev={pos["leverage"]:.0f}x | entry=${pos["entryPx"]:.4f}')

            leader_info = {
                'name': name,
                'addr': addr,
                'notional': pos['notional'],
                'leverage': pos['leverage'],
            }
            order_id = place_copy_trade(bitunix_sym, side, balance, leader_info)

            if order_id:
                copy_positions[order_id] = {
                    'symbol': bitunix_sym,
                    'leader_addr': addr,
                    'leader_name': name,
                    'leader_coin': coin,
                    'leader_side': pos['side'],
                    'leader_entry': pos['entryPx'],
                    'leader_notional': pos['notional'],
                    'our_side': side,
                    'opened_at': datetime.now(timezone.utc).isoformat(),
                }
                available_copy_slots -= 1
                new_trades_placed += 1
                open_symbols.add(bitunix_sym)

                send_alert(
                    f'NEXYROTH: Copy trade opened — {bitunix_sym}',
                    f'Copied {name}\'s {pos["side"]} on {coin} (${pos["notional"]:.0f} notional, {pos["leverage"]:.0f}x lev)\n'
                    f'Our trade: {side} {bitunix_sym} at market'
                )

        time.sleep(0.5)  # Rate limit between trader polls

    state['copy_positions'] = copy_positions
    save_state(state)

    log(f'')
    log(f'  📊 Session Summary:')
    log(f'       Copy trades placed: {new_trades_placed}')
    log(f'       Active copy slots:  {MAX_COPY_SLOTS - available_copy_slots}/{MAX_COPY_SLOTS}')
    log(f'       Traders monitored:  {len(traders)}')
    log('=' * 70)


if __name__ == '__main__':
    main()
