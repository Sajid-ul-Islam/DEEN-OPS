import requests
import time
import json
import os

from src.utils.http import request_with_backoff
from src.utils.logging import log_system_event

class PathaoClient:
    def __init__(self, base_url, client_id, client_secret, username, password):
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0
        self.token_file = "pathao_token.json"
        self._load_token()

    def _save_token(self, data):
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")
        # expires_in is usually in seconds
        self.expires_at = time.time() + data.get("expires_in", 3600) - 60  # 1 min buffer

        token_data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at
        }
        with open(self.token_file, "w") as f:
            json.dump(token_data, f)

    def _load_token(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, "r") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
                    self.expires_at = data.get("expires_at", 0)
            except Exception:
                pass

    def ensure_token(self):
        if not self.access_token or time.time() > self.expires_at:
            if self.refresh_token:
                self.refresh_access_token()
            else:
                self.issue_access_token()

    def issue_access_token(self):
        url = f"{self.base_url}/aladdin/api/v1/issue-token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
            "grant_type": "password"
        }
        try:
            res = request_with_backoff("POST", url, json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                self._save_token(data)
                return True
            else:
                log_system_event("PATHAO_AUTH_FAILED", f"{res.status_code} - {res.text}")
                return False
        except Exception as e:
            log_system_event("PATHAO_AUTH_ERROR", str(e))
            return False

    def refresh_access_token(self):
        url = f"{self.base_url}/aladdin/api/v1/issue-token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }
        try:
            res = request_with_backoff("POST", url, json=payload, timeout=10)
            if res.status_code == 200:
                self._save_token(res.json())
                return True
            else:
                log_system_event("PATHAO_REFRESH_FAILED", f"{res.status_code} - {res.text}")
                return self.issue_access_token()
        except Exception:
            return self.issue_access_token()

    def _get_headers(self):
        self.ensure_token()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get_cities(self):
        url = f"{self.base_url}/aladdin/api/v1/cities"
        try:
            res = request_with_backoff("GET", url, headers=self._get_headers(), timeout=10)
            if res.status_code == 200:
                return res.json().get("data", {}).get("data", []), None
            else:
                return [], f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            return [], f"Connection Error: {e}"

    def get_zones(self, city_id):
        url = f"{self.base_url}/aladdin/api/v1/cities/{city_id}/zone-list"
        try:
            res = request_with_backoff("GET", url, headers=self._get_headers(), timeout=10)
            if res.status_code == 200:
                return res.json().get("data", {}).get("data", []), None
            else:
                return [], f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            return [], f"Connection Error: {e}"

    def get_areas(self, zone_id):
        url = f"{self.base_url}/aladdin/api/v1/zones/{zone_id}/area-list"
        try:
            res = request_with_backoff("GET", url, headers=self._get_headers(), timeout=10)
            if res.status_code == 200:
                return res.json().get("data", {}).get("data", []), None
            else:
                return [], f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            return [], f"Connection Error: {e}"
