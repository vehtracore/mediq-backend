import requests
import os

def test_ssl():
    try:
        print("Testing HTTPS connection to api.resend.com...")
        resp = requests.get("https://api.resend.com", timeout=10)
        print(f"Status: {resp.status_code}")
        print("Success!")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_ssl()
