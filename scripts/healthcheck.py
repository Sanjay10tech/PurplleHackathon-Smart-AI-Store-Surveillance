"""Container health probe — checks /health/ready (database connectivity)."""

import sys
import urllib.error
import urllib.request


def main() -> int:
    url = "http://127.0.0.1:8000/health/ready"
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            if response.status != 200:
                return 1
            body = response.read().decode("utf-8")
            if '"not_ready"' in body or '"down"' in body:
                return 1
    except (urllib.error.URLError, TimeoutError, OSError):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
