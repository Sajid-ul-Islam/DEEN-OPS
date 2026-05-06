import sys
import json
sys.path.append('g:\\DEEN-OPS')
from src.services.pathao.client import PathaoClient
from src.config.ui_config import PATHAO_CONFIG
import requests

client = PathaoClient(**PATHAO_CONFIG)
headers = client._get_headers()

# Try getting orders
res1 = requests.get(f"{client.base_url}/aladdin/api/v1/orders", headers=headers, params={"search": "017"})
print("Status:", res1.status_code)
if res1.status_code == 200:
    print(res1.text[:500])

res2 = requests.get(f"{client.base_url}/aladdin/api/v1/orders", headers=headers, params={"phone": "017"})
if res2.status_code == 200:
    print(res2.text[:500])
