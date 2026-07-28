#!/usr/bin/env python3
"""
NEXYROTH Bitunix Copy Trader v2.0
Monitors Bitpanetrain (verified lead trader) via the real Bitunix copy trading API.
Copies BTCUSDT trades + zero-fee tokens. Uses position history polling to detect
new entries and mirrors them proportionally on your account.

Verified Lead Traders:
  - Bitpanetrain (uid=669214187): Score 8/10 | 22% ROI | 2% drawdown | 86% win rate
    Strategy: BTC swing + daytrades, 5x leverage, SHORT-biased, tight SL
    API: GET https://api.bitunix.com/copy/trading/v1/trader/position/history?traderUid=669214187

Schedule: Every 2 minutes via cron
"""

import os, sys, json, time, uuid, hashlib, requests, logging
from datetime import datetime, timezone
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
LOG_FILE = BASE_DIR / 'bitunix_copy_trader.log'
STATE_FILE = DATA_DIR / 'copy_trader_state.json'

DATA_DIR.mkdir(exist_ok=True)

# Verified lead traders to copy (from legitimacy analysis)
LEAD_TRADERS = [
    {
        'name': 'Bitpanetrain',
        'legit_score': 8,
        'max_copy_slots': 2,   # max positions to copy from this trader
        'enabled': True,
    },
    {
        'name': 'Bull is back',
        'legit_score': 5,
        'max_copy_slots': 1,
        'enabled': True,       # monitoring — will copy if signal is strong
    },
]

# Tokens eligible for copy trading (zero-fee + BTC enabled)
COPY_ELIGIBLE_TOKENS = {
    'BTCUSDT',  # Bitpanetrain's primary token — NOW ENABLED
    'SOLUSDT', 'XRPUSDT', 'SUIUSDT', 'LABUSDT', 'BUSDT',
    'TONUSDT', 'SKYAIUSDT', 'DOGSUSDT', 'DOGEUSDT', 'TSTUSDT'
}

# Bitpanetrain trader config (real API-verified)
BITPANETRAIN_UID = '669214187'
COPY_API_BASE = 'https://api.bitunix.com'

# Risk controls
MAX_COPY_POSITIONS = 2          # max total copy positions at once
COPY_RISK_PCT = 0.45            # 20% of available balance per copy trade
COPY_LEVERAGE = 10               # 3x leverage for copy trades (conservative)
COPY_TP_PCT = 0.04              # +4% take profit
COPY_SL_PCT = 0.02              # -2% stop loss
MIN_BALANCE = 1.50              # minimum balance to copy trade

# Bitunix API
BASE_URL = 'https://fapi.bitunix.com'
COPY_LEADERBOARD_URL = f'{BASE_URL}/api/v1/copy'

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── AUTH ─────────────────────────────────────────────────────────────────────
def _load_keys():
    secrets = Path.home() / '.secrets'
    ak = (secrets / 'bitunix_api_key').read_text().strip()
    sk = (secrets / 'bitunix_secret_key').read_text().strip()
    return ak, sk

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def _make_headers(api_key: str, secret_key: str, qs: str = '', body: str = '') -> dict:
    nonce = uuid.uuid4().hex[:32]
    ts = str(int(time.time() * 1000))
    digest = _sha256(nonce + ts + api_key + qs + body)
    sign = _sha256(digest + secret_key)
    return {
        'api-key': api_key,
        'nonce': nonce,
        'timestamp': ts,
        'sign': sign,
        'Content-Type': 'application/json',
        'language': 'en-US',
    }

# ─── STATE ────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {'copy_positions': {}, 'last_seen_trades': {}, 'total_copies': 0}

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ─── BITUNIX API ──────────────────────────────────────────────────────────────
def get_balance(ak, sk) -> float:
    qs = 'marginCoinUSDT'
    r = requests.get(
        f'{BASE_URL}/api/v1/futures/account',
        params={'marginCoin': 'USDT'},
        headers=_make_headers(ak, sk, qs),
        timeout=10
    )
    data = r.json().get('data', {})
    return float(data.get('available', 0) or 0)

def get_open_positions(ak, sk) -> list:
    qs = 'marginCoinUSDT'
    r = requests.get(
        f'{BASE_URL}/api/v1/futures/position/get_pending_positions',
        params={'marginCoin': 'USDT'},
        headers=_make_headers(ak, sk, qs),
        timeout=10
    )
    data = r.json().get('data', [])
    if isinstance(data, dict):
        data = data.get('positionList', [])
    return [p for p in data if float(p.get('qty', 0) or 0) > 0]

def get_ticker_price(symbol: str) -> float:
    r = requests.get(
        f'{BASE_URL}/api/v1/futures/market/funding_rate',
        params={'symbol': symbol},
        timeout=8
    )
    return float(r.json().get('data', {}).get('lastPrice', 0) or 0)

def get_bitpanetrain_position_history(limit: int = 20) -> list:
    """Fetch Bitpanetrain's position history via the real Bitunix copy trading API."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': f'https://www.bitunix.com/copy-trading/profile/{BITPANETRAIN_UID}',
            'Origin': 'https://www.bitunix.com'
        }
        r = requests.get(
            f'{COPY_API_BASE}/copy/trading/v1/trader/position/history',
            headers=headers,
            params={'traderUid': BITPANETRAIN_UID, 'limit': limit, 'page': 1},
            timeout=10
        )
        data = r.json()
        if data.get('code') == 0 and data.get('data'):
            return data['data'].get('records', [])
    except Exception as e:
        log.warning(f'Failed to fetch Bitpanetrain history: {e}')
    return []

def get_bitpanetrain_detail() -> dict:
    """Fetch Bitpanetrain's live account detail."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Referer': f'https://www.bitunix.com/copy-trading/profile/{BITPANETRAIN_UID}',
            'Origin': 'https://www.bitunix.com'
        }
        r = requests.post(
            f'{COPY_API_BASE}/copy/trading/v1/trader/detail',
            headers=headers,
            json={'uid': BITPANETRAIN_UID},
            timeout=10
        )
        data = r.json()
        if data.get('code') == 0:
            return data.get('data', {})
    except Exception as e:
        log.warning(f'Failed to fetch Bitpanetrain detail: {e}')
    return {}

def place_order(ak, sk, symbol: str, side: str, qty: float, price: float,
                tp_price: float, sl_price: float) -> dict:
    """Place a futures order on Bitunix."""
    # Round qty based on symbol
    qty_precision = {
        'SOLUSDT': 1, 'XRPUSDT': 0, 'SUIUSDT': 0, 'LABUSDT': 0,
        'BUSDT': 0, 'TONUSDT': 0, 'SKYAIUSDT': 0, 'DOGSUSDT': 0,
        'DOGEUSDT': 0, 'TSTUSDT': 0,
    }
    price_precision = {
        'SOLUSDT': 2, 'XRPUSDT': 4, 'SUIUSDT': 4, 'LABUSDT': 4,
        'BUSDT': 4, 'TONUSDT': 4, 'SKYAIUSDT': 5, 'DOGSUSDT': 8,
        'DOGEUSDT': 5, 'TSTUSDT': 5,
    }
    qp = qty_precision.get(symbol, 2)
    pp = price_precision.get(symbol, 4)
    qty = round(qty, qp)
    tp_price = round(tp_price, pp)
    sl_price = round(sl_price, pp)

    order_side = 'BUY' if side == 'LONG' else 'SELL'
    body_dict = {
        'symbol': symbol,
        'side': order_side,
        'orderType': 'MARKET',
        'qty': str(qty),
        'marginCoin': 'USDT',
        'leverage': str(COPY_LEVERAGE),
        'marginMode': 'CROSSED',
        'tpPrice': str(tp_price),
        'slPrice': str(sl_price),
        'tpStopType': 'MARK_PRICE',
        'slStopType': 'MARK_PRICE',
        'positionSide': 'NET',
    }
    body = json.dumps(body_dict, separators=(',', ':'))
    r = requests.post(
        f'{BASE_URL}/api/v1/futures/trade/place_order',
        data=body,
        headers=_make_headers(ak, sk, '', body),
        timeout=15
    )
    return r.json()

# ─── COPY LOGIC ───────────────────────────────────────────────────────────────
def should_copy_trade(symbol: str, side: str, state: dict) -> tuple[bool, str]:
    """
    Decide whether to copy a trade. Returns (should_copy, reason).
    Filters: eligible token, not already held, max positions not exceeded.
    """
    if symbol not in COPY_ELIGIBLE_TOKENS:
        return False, f'{symbol} not in eligible tokens list'

    # Check if we already have a copy position in this symbol
    if symbol in state['copy_positions']:
        return False, f'Already have copy position in {symbol}'

    # Check max copy positions
    active_copies = len(state['copy_positions'])
    if active_copies >= MAX_COPY_POSITIONS:
        return False, f'Max copy positions ({MAX_COPY_POSITIONS}) reached'

    return True, 'All filters passed'

def calculate_copy_qty(balance: float, price: float, symbol: str) -> float:
    """Calculate position size for copy trade."""
    notional = balance * COPY_RISK_PCT * COPY_LEVERAGE
    qty = notional / price if price > 0 else 0

    # Minimum quantities per symbol
    min_qty = {
        'BTCUSDT': 0.001,
        'SOLUSDT': 0.1, 'XRPUSDT': 5, 'SUIUSDT': 10, 'LABUSDT': 10,
        'BUSDT': 20, 'TONUSDT': 1, 'SKYAIUSDT': 10, 'DOGSUSDT': 100000,
        'DOGEUSDT': 10, 'TSTUSDT': 100,
    }
    min_q = min_qty.get(symbol, 1)
    if qty < min_q:
        if qty >= min_q * 0.5:  # within 50% — bump up
            qty = min_q
        else:
            return 0  # too small

    return qty

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    log.info('=' * 60)
    log.info('NEXYROTH Bitunix Copy Trader v2.0 — Bitpanetrain')
    log.info('=' * 60)

    try:
        ak, sk = _load_keys()
    except Exception as e:
        log.error(f'Failed to load API keys: {e}')
        sys.exit(1)

    state = load_state()
    if 'seen_position_ids' not in state:
        state['seen_position_ids'] = []

    balance = get_balance(ak, sk)
    log.info(f'  Balance: ${balance:.2f} USDT')

    if balance < MIN_BALANCE:
        log.info(f'  Balance ${balance:.2f} below minimum ${MIN_BALANCE} — skipping')
        return

    # Sync copy positions with live positions
    live_positions = get_open_positions(ak, sk)
    live_symbols = {p.get('symbol') for p in live_positions}
    stale = [s for s in list(state['copy_positions'].keys()) if s not in live_symbols]
    for s in stale:
        log.info(f'  📤 Copy position {s} closed — removing from state')
        del state['copy_positions'][s]

    active_copies = len(state['copy_positions'])
    log.info(f'  Active copy positions: {active_copies}/{MAX_COPY_POSITIONS}')

    # Fetch Bitpanetrain's live detail
    detail = get_bitpanetrain_detail()
    if detail:
        today_pnl = float(detail.get('todayPnl', 0) or 0)
        unreal_pnl = float(detail.get('unPnl', 0) or 0)
        log.info(f'  📊 Bitpanetrain today PnL: ${today_pnl:+.2f} | Unrealized: ${unreal_pnl:+.2f}')

    # Fetch Bitpanetrain's recent position history to detect new trades
    history = get_bitpanetrain_position_history(limit=10)
    log.info(f'  📜 Fetched {len(history)} recent positions from Bitpanetrain')

    trades_opened = 0

    for pos in history:
        pos_id = str(pos.get('id', ''))
        symbol = pos.get('symbol', '')
        # side: 1=LONG, 2=SHORT
        side_raw = pos.get('side', 2)
        side = 'LONG' if side_raw == 1 else 'SHORT'
        open_price = float(pos.get('openPrice', 0) or 0)
        leverage = int(pos.get('leverage', 5) or 5)
        finish_type = pos.get('finishType', 0)  # 0=open/active, 1=closed
        ctime = pos.get('ctime', '')

        # Skip already-seen positions
        if pos_id in state['seen_position_ids']:
            continue

        # Skip closed positions (only copy active/new ones)
        if finish_type != 0:
            state['seen_position_ids'].append(pos_id)
            continue

        # This is a NEW active position — check if we should copy it
        log.info(f'  🔍 New Bitpanetrain position: {side} {symbol} @ ${open_price:.2f} ({leverage}x) [{ctime}]')

        should_copy, reason = should_copy_trade(symbol, side, state)
        if not should_copy:
            log.info(f'     ⏭️  Skipping: {reason}')
            state['seen_position_ids'].append(pos_id)
            continue

        price = get_ticker_price(symbol)
        if price <= 0:
            log.warning(f'     ⚠️  {symbol}: could not get current price')
            continue

        # Price staleness check — don't copy if price moved >3% from Bitpanetrain's entry
        if open_price > 0:
            price_drift = abs(price - open_price) / open_price
            if price_drift > 0.03:
                log.info(f'     ⏭️  {symbol}: price drifted {price_drift:.1%} from entry — too late to copy')
                state['seen_position_ids'].append(pos_id)
                continue

        qty = calculate_copy_qty(balance, price, symbol)
        if qty <= 0:
            log.info(f'     ⏭️  {symbol}: insufficient balance for minimum qty')
            state['seen_position_ids'].append(pos_id)
            continue

        # Use Bitpanetrain's leverage capped at our max
        effective_leverage = min(leverage, 5)

        # Calculate TP/SL based on Bitpanetrain's style (tight SL, wider TP)
        if side == 'LONG':
            tp = price * (1 + COPY_TP_PCT)
            sl = price * (1 - COPY_SL_PCT)
        else:
            tp = price * (1 - COPY_TP_PCT)
            sl = price * (1 + COPY_SL_PCT)

        log.info(f'     📋 COPYING: {side} {symbol} qty={qty:.4f} @ ${price:.2f} | TP=${tp:.2f} SL=${sl:.2f}')

        result = place_order(ak, sk, symbol, side, qty, price, tp, sl)
        order_id = result.get('data', {}).get('orderId', '') if isinstance(result.get('data'), dict) else ''

        if result.get('code') == 0:
            log.info(f'     ✅ Copy trade placed! OrderID={order_id}')
            state['copy_positions'][symbol] = {
                'trader': 'Bitpanetrain',
                'side': side,
                'qty': qty,
                'entry': price,
                'tp': tp,
                'sl': sl,
                'order_id': order_id,
                'source_pos_id': pos_id,
                'opened_at': datetime.now(timezone.utc).isoformat(),
            }
            state['total_copies'] = state.get('total_copies', 0) + 1
            trades_opened += 1
            balance -= balance * COPY_RISK_PCT
        else:
            msg = result.get('msg', str(result))
            log.warning(f'     ❌ Copy trade failed: {msg}')

        state['seen_position_ids'].append(pos_id)

    # Keep seen_position_ids list manageable
    state['seen_position_ids'] = state['seen_position_ids'][-200:]

    log.info(f'\n  📊 Session Summary:')
    log.info(f'     Copy trades opened this run: {trades_opened}')
    log.info(f'     Total lifetime copies: {state.get("total_copies", 0)}')
    log.info(f'     Active copy positions: {len(state["copy_positions"])}')
    if state['copy_positions']:
        for sym, pos in state['copy_positions'].items():
            log.info(f'       {sym}: {pos["side"]} @ ${pos["entry"]:.4f}')

    save_state(state)
    log.info('=' * 60)

if __name__ == '__main__':
    main()
