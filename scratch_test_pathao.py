from src.services.pathao.client import PathaoClient
from src.config.settings import get_pathao_config
import requests

print("Testing Raw Pathao Auth...")
creds = get_pathao_config(required=True)
client = PathaoClient(**creds)

url = f"{client.base_url}/aladdin/api/v1/issue-token"
payload = {
    "client_id": client.client_id,
    "client_secret": client.client_secret,
    "username": client.username,
    "password": client.password,
    "grant_type": "password"
}
res = requests.post(url, json=payload, timeout=10)

if res.status_code == 200:
    token = res.json().get("access_token")
    print(f"Auth Success! Token starts with: {token[:10]}")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Let's test a fake order to see if it gives 404 or Unauthorized
    print("\nTesting order info endpoint...")
    status_url = f"{client.base_url}/aladdin/api/v1/orders/DD12345/info"
    c_res = requests.get(status_url, headers=headers)
    print(f"Status Code: {c_res.status_code}")
    print(c_res.json())
