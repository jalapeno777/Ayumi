import os  # noqa: E401, I001
import sys

sys.path.insert(0, "/home/TacoPants/projects/Ayumi")
sys.path.insert(0, "/home/TacoPants/projects/Ayumi/src/forex-bot")
os.chdir("/home/TacoPants/projects/Ayumi")

from dotenv import load_dotenv

load_dotenv("/home/TacoPants/projects/Ayumi/.env")

from adapters.ctrader.open_api_client import CTraderOpenApiClient

client_id = os.getenv("CTRADER_OPENAPI_CLIENT_ID")
client_secret = os.getenv("CTRADER_OPENAPI_CLIENT_SECRET")
access_token = os.getenv("CTRADER_OPENAPI_ACCESS_TOKEN")
account_id = int(os.getenv("CTRADER_OPENAPI_ACCOUNT_ID"))

print("Testing with access_token", access_token[:20], "...")
client = CTraderOpenApiClient(
    client_id=client_id,
    client_secret=client_secret,
    account_id=account_id,
    access_token=access_token,
    host="demo.ctraderapi.com",
    port=5035,
)
ok = client.connect()
print("connect() returned", ok)
if ok:
    symbols = client.get_all_symbols()
    print("symbols count", len(symbols))
    if symbols:
        print("first symbol", symbols[0])
client.disconnect()
