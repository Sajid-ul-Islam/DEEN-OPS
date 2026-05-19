import os
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    url = os.getenv("DEEN_OPS_HEALTHCHECK_URL", "http://localhost:8501/_stcore/health")
    timeout = float(os.getenv("DEEN_OPS_HEALTHCHECK_TIMEOUT", "5"))

    try:
        with urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore").strip().lower()
            if response.status == 200 and "ok" in body:
                return 0
    except URLError as exc:
        print(f"Healthcheck failed: {exc}")
        return 1
    except Exception as exc:
        print(f"Healthcheck failed: {exc}")
        return 1

    print(f"Healthcheck failed: unexpected response from {url}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
