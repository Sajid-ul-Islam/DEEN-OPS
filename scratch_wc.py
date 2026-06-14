from src.config.settings import get_woocommerce_config
from src.utils.http import request_with_backoff
from requests.auth import HTTPBasicAuth

wc_info = get_woocommerce_config()
url = wc_info["store_url"].rstrip("/") + "/wp-json/wc/v3/orders/177190"
auth = HTTPBasicAuth(wc_info["consumer_key"], wc_info["consumer_secret"])
res = request_with_backoff("GET", url, auth=auth)
print(res.status_code)
if res.status_code == 200:
    print("Order number:", res.json().get("number"))
