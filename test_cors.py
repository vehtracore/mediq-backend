import requests

url = "https://mediq-backend-m3ik.onrender.com/api/v1/auth/signup"
headers = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
    "Origin": "http://localhost:58155"
}

print(f"Testing OPTIONS {url} with Origin: {headers['Origin']}")

try:
    response = requests.options(url, headers=headers)
    print(f"Status Code: {response.status_code}")
    print("Headers:")
    for k, v in response.headers.items():
        if "access-control" in k.lower():
            print(f"{k}: {v}")
            
    if response.status_code == 200 and "Access-Control-Allow-Origin" in response.headers:
        print("\n✅ CORS Preflight seems SUCCESSFUL.")
    else:
        print("\n❌ CORS Preflight FAILED.")

except Exception as e:
    print(f"\n❌ Request Exception: {e}")
