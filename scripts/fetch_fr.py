import requests
BASE = "https://fapi.bitunix.com"
symbols = ['IDUSDT', 'TLMUSDT', 'LIGHTERUSDT']
print(f"{'Symbol':<12} | {'Funding Rate (%)':>15}")
print("-" * 30)
for s in symbols:
    try:
        r = requests.get(f"{BASE}/api/v1/futures/market/funding_rate", params={"symbol": s})
        fr = float(r.json().get("data", {}).get("fundingRate", 0)) * 100
        print(f"{s:<12} | {fr:>15.4f}%")
    except:
        print(f"{s:<12} | {'Error':>15}")
