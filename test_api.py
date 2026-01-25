import requests
import json

BASE_URL = "https://mediq-backend-m3ik.onrender.com"

print("=" * 50)
print("1. Testing GET / (Root Endpoint)")
print("=" * 50)
try:
    response = requests.get(f"{BASE_URL}/", timeout=60)
    print(f"Status: {response.status_code}")
    print(f"Body: {response.json()}")
except Exception as e:
    print(f"Error: {e}")

print()
print("=" * 50)
print("2. Testing POST /api/v1/auth/signup")
print("=" * 50)
try:
    data = {
        "email": "test_cors_check@example.com",
        "password": "password123",
        "first_name": "Test",
        "last_name": "User",
        "dob": "2000-01-01",
        "role": "patient"
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/signup",
        json=data,
        headers=headers,
        timeout=60
    )
    print(f"Status: {response.status_code}")
    print(f"Body: {response.text}")
    print(f"CORS Headers:")
    for k, v in response.headers.items():
        if "access-control" in k.lower() or "cors" in k.lower():
            print(f"  {k}: {v}")
except Exception as e:
    print(f"Error: {e}")

print()
print("=" * 50)
print("3. Testing OPTIONS /api/v1/auth/signup (CORS Preflight)")
print("=" * 50)
try:
    headers = {
        "Origin": "http://localhost:58155",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"
    }
    response = requests.options(
        f"{BASE_URL}/api/v1/auth/signup",
        headers=headers,
        timeout=60
    )
    print(f"Status: {response.status_code}")
    print(f"Headers:")
    for k, v in response.headers.items():
        print(f"  {k}: {v}")
except Exception as e:
    print(f"Error: {e}")
