#!/usr/bin/env python3
def calc_vwap(candles):
    if not candles: return 0.0
    cum_tp_vol = cum_vol = 0.0
    for c in candles:
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        cum_tp_vol += tp * c["volume"]; cum_vol += c["volume"]
    return cum_tp_vol / cum_vol if cum_vol else 0.0

def calc_cvd(candles, lookback=20):
    if len(candles) < lookback: return 0.0
    cvd = 0.0
    for c in candles[-lookback:]:
        if c["close"] > c["open"]: cvd += c["volume"]
        elif c["close"] < c["open"]: cvd -= c["volume"]
    return cvd

candles = [
    {"open":100,"high":105,"low":99,"close":103,"volume":1000},
    {"open":103,"high":107,"low":102,"close":106,"volume":1500},
    {"open":106,"high":108,"low":104,"close":105,"volume":800},
]
vwap = calc_vwap(candles)
cvd  = calc_cvd(candles, lookback=3)
print(f"VWAP: {vwap:.4f} (expect ~104.35)")
print(f"CVD:  {cvd:.1f} (expect +1700.0)")
assert 104.0 < vwap < 105.0
assert cvd == 1700.0
print("✅ All tests passed!")
