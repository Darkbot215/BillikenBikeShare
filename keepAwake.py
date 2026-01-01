import os
import sys
import requests

RENDER_URL = os.getenv("RENDER_URL")

if not RENDER_URL:
    print("RENDER_URL not set")
    sys.exit(1)

try:
    r = requests.get(f"{RENDER_URL}/health", timeout=10)
    print("Status:", r.status_code)
    print("Response:", r.text)
except Exception as e:
    print("Ping failed:", e)
    sys.exit(1)
