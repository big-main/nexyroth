#!/usr/bin/env python3
"""
NEXYROTH — Bitunix WebSocket Market Data Streamer v1.1
=======================================================
Replaces REST polling for real-time tick data.
Streams live kline (OHLCV) data via WebSocket for all zero-fee tokens.
Writes latest candle data to /tmp/nexyroth_ws_data.json for the scalper to consume.

WebSocket Endpoint: wss://fapi.bitunix.com/public/
Subscription format:
  { "op": "subscribe", "args": [{ "ch": "market_kline_1min", "symbol": "SOLUSDT" }] }

Available channels:
  - market_kline_1min  — 1-minute OHLCV candles
  - market_kline_5min  — 5-minute candles
  - depth_books        — order book depth
  - ticker             — 24h ticker stats

Rate Limits: max 5 messages/second, connection valid 24h (auto-reconnect)

Usage:
  python3 bitunix_ws_streamer.py          # runs as persistent daemon
  python3 bitunix_ws_streamer.py --test   # test connection and exit
  python3 bitunix_ws_streamer.py --read   # print latest cached data

Integration:
  The scalper reads /tmp/nexyroth_ws_data.json instead of polling REST.
  Falls back to REST if WS data is stale (>90 seconds).
"""

import os
import sys
import json
import time
import asyncio
import logging
import signal
import threading
from datetime import datetime, timezone
from typing import Dict, Optional
import websockets
import websockets.exceptions

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
WS_URL = "wss://fapi.bitunix.com/public/"
OUTPUT_FILE = "/tmp/nexyroth_ws_data.json"
LOG_FILE = "/home/ubuntu/trading_sniper/data/ws_streamer.log"
PING_INTERVAL_SEC = 25      # send ping every 25s (server expects heartbeat)
RECONNECT_DELAY = 5         # seconds before reconnect attempt
MAX_RECONNECT_DELAY = 60    # cap backoff at 60s
STALE_THRESHOLD = 90        # seconds before data considered stale

ZERO_FEE_TOKENS = [
    "SOLUSDT", "XRPUSDT", "SUIUSDT", "DOGEUSDT",
    "TSTUSDT", "LABUSDT", "BUSDT", "TONUSDT",
    "SKYAIUSDT", "DOGSUSDT"
]

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WS] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("nexyroth_ws")

# ═══════════════════════════════════════════════════════════════
# SHARED STATE
# ═══════════════════════════════════════════════════════════════
market_data: Dict[str, dict] = {}
data_lock = threading.Lock()


def save_data():
    """Atomically write market data to output file."""
    with data_lock:
        payload = {
            "updated_at": time.time(),
            "updated_at_iso": datetime.now(timezone.utc).isoformat(),
            "source": "websocket",
            "symbols": dict(market_data),
        }
    tmp = OUTPUT_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, OUTPUT_FILE)
    except Exception as e:
        log.error(f"Failed to save data: {e}")


def process_kline_msg(msg: dict):
    """
    Parse Bitunix kline WebSocket message.
    Expected format:
    {
      "ch": "market_kline_1min",
      "symbol": "SOLUSDT",
      "data": { "o": "73.5", "h": "74.0", "l": "73.2", "c": "73.8",
                "v": "12345", "t": 1722220800000 }
    }
    """
    try:
        symbol = msg.get("symbol", "").upper()
        if not symbol:
            return
        data = msg.get("data", {})
        if isinstance(data, list):
            data = data[0] if data else {}

        close = float(data.get("c", data.get("close", 0)))
        if close <= 0:
            return

        with data_lock:
            market_data[symbol] = {
                "open":    float(data.get("o", data.get("open", close))),
                "high":    float(data.get("h", data.get("high", close))),
                "low":     float(data.get("l", data.get("low", close))),
                "close":   close,
                "volume":  float(data.get("b", data.get("v", data.get("volume", 0)))),  # 'b'=base vol, 'q'=quote vol
                "quote_vol": float(data.get("q", 0)),
                "ts":      int(data.get("t", data.get("ts", int(time.time() * 1000)))),
                "updated": time.time(),
                "channel": msg.get("ch", "kline"),
            }
        save_data()
        log.debug(f"Kline {symbol}: close={close}")
    except Exception as e:
        log.warning(f"Kline parse error: {e} | msg={msg}")


def process_ticker_msg(msg: dict):
    """Parse ticker message — update close price if kline not yet received."""
    try:
        symbol = msg.get("symbol", "").upper()
        if not symbol:
            return
        data = msg.get("data", {})
        if isinstance(data, list):
            data = data[0] if data else {}

        price = float(data.get("c", data.get("lastPrice", data.get("last", 0))))
        if price <= 0:
            return

        with data_lock:
            if symbol not in market_data:
                market_data[symbol] = {}
            existing = market_data[symbol]
            existing["close"] = price
            existing["updated"] = time.time()
            if "channel" not in existing:
                existing["channel"] = "ticker"
        save_data()
    except Exception as e:
        log.warning(f"Ticker parse error: {e}")


def build_subscribe_msgs() -> list:
    """Build subscription messages for all zero-fee tokens."""
    msgs = []
    for symbol in ZERO_FEE_TOKENS:
        msgs.append({
            "op": "subscribe",
            "args": [{"ch": "market_kline_1min", "symbol": symbol}]
        })
        msgs.append({
            "op": "subscribe",
            "args": [{"ch": "ticker", "symbol": symbol}]
        })
    return msgs


async def send_ping(ws):
    """Send a ping to keep the connection alive."""
    ping_msg = {"op": "ping", "ping": int(time.time())}
    await ws.send(json.dumps(ping_msg))


async def ws_connect_and_stream():
    """Main WebSocket coroutine with auto-reconnect and ping keepalive."""
    backoff = RECONNECT_DELAY
    attempt = 0

    while True:
        attempt += 1
        log.info(f"Connecting to {WS_URL} (attempt {attempt})")
        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=None,   # we handle pings manually
                ping_timeout=None,
                close_timeout=5,
                max_size=2**20,
            ) as ws:
                log.info("Connected. Subscribing to channels...")
                backoff = RECONNECT_DELAY  # reset on successful connect

                # Send subscriptions (rate limit: 5 msg/sec)
                sub_msgs = build_subscribe_msgs()
                for i, msg in enumerate(sub_msgs):
                    await ws.send(json.dumps(msg))
                    if (i + 1) % 4 == 0:
                        await asyncio.sleep(1.1)
                    else:
                        await asyncio.sleep(0.25)

                log.info(f"Subscribed {len(sub_msgs)} channels for {len(ZERO_FEE_TOKENS)} symbols")

                last_ping = time.time()

                # Listen loop
                while True:
                    # Send ping if needed
                    if time.time() - last_ping > PING_INTERVAL_SEC:
                        await send_ping(ws)
                        last_ping = time.time()

                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    except asyncio.TimeoutError:
                        continue  # no message, loop back to check ping

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    op = msg.get("op", "")
                    ch = msg.get("ch", "")
                    event = msg.get("event", "")

                    # Skip pong/system messages
                    if op == "pong" or event == "pong":
                        continue
                    if event in ("subscribe", "unsubscribe"):
                        log.debug(f"Subscription ack: {msg}")
                        continue
                    if event == "error" or op == "error":
                        log.warning(f"WS error msg: {msg}")
                        continue

                    # Route data
                    if "kline" in ch:
                        process_kline_msg(msg)
                    elif "ticker" in ch:
                        process_ticker_msg(msg)

        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"Connection closed: {e}. Reconnecting in {backoff}s...")
        except Exception as e:
            log.error(f"WebSocket error: {type(e).__name__}: {e}. Reconnecting in {backoff}s...")

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, MAX_RECONNECT_DELAY)


def read_ws_data(symbol: str, max_age: float = STALE_THRESHOLD) -> Optional[dict]:
    """
    Read latest WebSocket data for a symbol.
    Returns None if data is stale or missing (caller should fall back to REST).
    Call this from the scalper to get real-time price data.
    """
    try:
        with open(OUTPUT_FILE) as f:
            payload = json.load(f)
        sym_data = payload.get("symbols", {}).get(symbol)
        if not sym_data:
            return None
        age = time.time() - sym_data.get("updated", 0)
        if age > max_age:
            return None
        return sym_data
    except Exception:
        return None


def is_ws_healthy() -> bool:
    """Check if WebSocket data is fresh."""
    try:
        with open(OUTPUT_FILE) as f:
            payload = json.load(f)
        age = time.time() - payload.get("updated_at", 0)
        return age < STALE_THRESHOLD
    except Exception:
        return False


async def test_connection():
    """Quick test: connect, subscribe to SOLUSDT, receive one kline, exit."""
    log.info("TEST MODE — connecting to Bitunix WebSocket...")
    try:
        async with websockets.connect(WS_URL, ping_interval=None) as ws:
            sub = {"op": "subscribe", "args": [{"ch": "market_kline_1min", "symbol": "SOLUSDT"}]}
            await ws.send(json.dumps(sub))
            log.info(f"Sent: {sub}")
            log.info("Waiting for messages (up to 30s)...")
            for _ in range(50):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    log.warning("Timeout waiting for message")
                    break
                msg = json.loads(raw)
                log.info(f"Received: {msg}")
                if msg.get("ch") and "kline" in msg.get("ch", ""):
                    log.info("✅ Kline data received successfully!")
                    return True
                if msg.get("event") == "subscribe":
                    log.info("Subscription confirmed, waiting for data...")
                    continue
            log.warning("No kline data received in time window")
            return False
    except Exception as e:
        log.error(f"❌ Test failed: {type(e).__name__}: {e}")
        return False


def main():
    if "--test" in sys.argv:
        result = asyncio.run(test_connection())
        sys.exit(0 if result else 1)

    if "--read" in sys.argv:
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE) as f:
                data = json.load(f)
            age = time.time() - data.get("updated_at", 0)
            print(f"Data age: {age:.1f}s | Symbols: {len(data.get('symbols', {}))}")
            for sym, d in data.get("symbols", {}).items():
                sym_age = time.time() - d.get("updated", 0)
                print(f"  {sym}: close={d.get('close', 'N/A')} | age={sym_age:.1f}s")
        else:
            print("No data file found. Is the streamer running?")
        sys.exit(0)

    log.info("=" * 60)
    log.info("NEXYROTH WebSocket Streamer v1.1 starting...")
    log.info(f"Endpoint: {WS_URL}")
    log.info(f"Streaming {len(ZERO_FEE_TOKENS)} zero-fee tokens")
    log.info(f"Output: {OUTPUT_FILE}")
    log.info("=" * 60)

    def _shutdown(sig, frame):
        log.info("Shutdown signal received. Exiting.")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    asyncio.run(ws_connect_and_stream())


if __name__ == "__main__":
    main()
