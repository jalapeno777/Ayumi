"""Test cTrader OpenAPI REST endpoints."""
import json, urllib.request, os, time
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

token = os.environ["CTRADER_OPENAPI_ACCESS_TOKEN"]
client_id = os.environ["CTRADER_OPENAPI_CLIENT_ID"]
client_secret = os.environ["CTRADER_OPENAPI_CLIENT_SECRET"]
base = "https://openapi.spotware.com"

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}

# 1. Get account info
print("=== Account Info ===")
try:
    req = urllib.request.Request(f"{base}/api/v2/accounts", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        print(json.dumps(data, indent=2)[:2000])
except Exception as e:
    print(f"Error: {e}")

# 2. Get symbols
print("\n=== Symbols ===")
try:
    req = urllib.request.Request(f"{base}/api/v2/symbols", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        # Find XAU
        for s in data.get("data", data) if isinstance(data, dict) else data:
            name = s.get("symbolName", s.get("name", ""))
            if "XAU" in name.upper() or "GOLD" in name.upper():
                print(f"  FOUND: {json.dumps(s, indent=2)}")
        print(f"Total symbols: {len(data.get('data', data)) if isinstance(data, dict) else len(data)}")
except Exception as e:
    print(f"Error: {e}")

# 3. Get tick data for EUR/USD
print("\n=== EUR/USD Tick ===")
try:
    # Try v3 ticks endpoint
    req = urllib.request.Request(f"{base}/api/v3/accounts/17087404/prices?symbols=1", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        print(json.dumps(data, indent=2)[:2000])
except Exception as e:
    print(f"Error: {e}")
