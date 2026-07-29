"""
NEXYROTH Zero-Fee Token Configuration v2.0
═══════════════════════════════════════════
Updated 2026-07-29 from Bitunix 0 Fees tab.
All scalpers/bots import this single source of truth.

Rule: ONLY trade these tokens (zero fees). Trade others ONLY if a huge win signal appears.
"""

# ═══════════════════════════════════════════════════════════════
# ZERO-FEE TOKEN LIST (from Bitunix "0 Fees" tab, 2026-07-29)
# Sorted by 24h volume descending
# ═══════════════════════════════════════════════════════════════
ZERO_FEE_TOKENS = [
    "SOLUSDT",          # $73.49   | 277.31M vol | Crypto
    "XRPUSDT",          # $1.0746  | 102.93M vol | Crypto
    "OILUSDT",          # $84.24   | 97.79M vol  | TradFi (CL/WTI)
    "HYPEUSDT",         # $54.992  | 78.46M vol  | Crypto
    "GOLDXAUTUSDT",     # $4012.29 | 61.18M vol  | TradFi (Gold)
    "SILVERXAGUSDT",    # $57.37   | 56.17M vol  | TradFi (Silver)
    "OILBZUSDT",        # $86.75   | 26.39M vol  | TradFi (Brent)
    "DOGEUSDT",         # $0.07040 | 21.30M vol  | Crypto
    "ADAUSDT",          # $0.1638  | 14.49M vol  | Crypto
    "SUIUSDT",          # $0.6870  | 12.31M vol  | Crypto
    "XLMUSDT",          # $0.17402 | 10.22M vol  | Crypto
    "BEATUSDT",         # $3.788   | 7.79M vol   | Crypto (+18.30%!)
    "VELVETUSDT",       # $0.4218  | 717.59K vol | Crypto
]

# Legacy tokens that may still be zero-fee (keep monitoring)
LEGACY_ZERO_FEE = [
    "LABUSDT",
    "BUSDT",
    "TONUSDT",
    "SKYAIUSDT",
    "DOGSUSDT",
    "TSTUSDT",
]

# Combined list for backward compatibility
ALL_ZERO_FEE = ZERO_FEE_TOKENS + LEGACY_ZERO_FEE

# ═══════════════════════════════════════════════════════════════
# PRECISION MAPS (qty decimals, price decimals, min qty)
# ═══════════════════════════════════════════════════════════════
QTY_PRECISION = {
    "SOLUSDT": 2,
    "XRPUSDT": 1,
    "OILUSDT": 2,
    "HYPEUSDT": 2,
    "GOLDXAUTUSDT": 3,
    "SILVERXAGUSDT": 2,
    "OILBZUSDT": 2,
    "DOGEUSDT": 0,
    "ADAUSDT": 0,
    "SUIUSDT": 1,
    "XLMUSDT": 0,
    "BEATUSDT": 1,
    "VELVETUSDT": 1,
    # Legacy
    "LABUSDT": 1,
    "BUSDT": 1,
    "TONUSDT": 2,
    "SKYAIUSDT": 0,
    "DOGSUSDT": 0,
    "TSTUSDT": 0,
}

PRICE_PRECISION = {
    "SOLUSDT": 2,
    "XRPUSDT": 4,
    "OILUSDT": 2,
    "HYPEUSDT": 3,
    "GOLDXAUTUSDT": 2,
    "SILVERXAGUSDT": 2,
    "OILBZUSDT": 2,
    "DOGEUSDT": 5,
    "ADAUSDT": 4,
    "SUIUSDT": 4,
    "XLMUSDT": 5,
    "BEATUSDT": 3,
    "VELVETUSDT": 4,
    # Legacy
    "LABUSDT": 4,
    "BUSDT": 4,
    "TONUSDT": 4,
    "SKYAIUSDT": 5,
    "DOGSUSDT": 7,
    "TSTUSDT": 6,
}

MIN_QTY = {
    "SOLUSDT": 0.01,
    "XRPUSDT": 1.0,
    "OILUSDT": 0.01,
    "HYPEUSDT": 0.01,
    "GOLDXAUTUSDT": 0.001,
    "SILVERXAGUSDT": 0.01,
    "OILBZUSDT": 0.01,
    "DOGEUSDT": 1,
    "ADAUSDT": 1,
    "SUIUSDT": 1.0,
    "XLMUSDT": 1,
    "BEATUSDT": 0.1,
    "VELVETUSDT": 1.0,
    # Legacy
    "LABUSDT": 1.0,
    "BUSDT": 1.0,
    "TONUSDT": 0.1,
    "SKYAIUSDT": 1,
    "DOGSUSDT": 1000,
    "TSTUSDT": 100,
}

# ═══════════════════════════════════════════════════════════════
# CATEGORIZATION
# ═══════════════════════════════════════════════════════════════
CRYPTO_TOKENS = ["SOLUSDT", "XRPUSDT", "HYPEUSDT", "DOGEUSDT", "ADAUSDT",
                 "SUIUSDT", "XLMUSDT", "BEATUSDT", "VELVETUSDT"]
TRADFI_TOKENS = ["OILUSDT", "GOLDXAUTUSDT", "SILVERXAGUSDT", "OILBZUSDT"]

# TradFi tokens trade during specific hours (rough guide)
# Gold/Silver: ~23h/day (Sun 6PM - Fri 5PM ET)
# Oil: ~23h/day (Sun 6PM - Fri 5PM ET)
# Crypto: 24/7

# ═══════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════
def get_precision(symbol: str):
    """Return (qty_precision, price_precision, min_qty) for a symbol."""
    return (
        QTY_PRECISION.get(symbol, 2),
        PRICE_PRECISION.get(symbol, 4),
        MIN_QTY.get(symbol, 1.0),
    )
