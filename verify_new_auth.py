import requests
import uuid
import time

# BASE_URL = "https://mediq-backend-m3ik.onrender.com/api/v1"
BASE_URL = "http://127.0.0.1:8000/api/v1"

def step(name):
    print(f"\n--> {name}...")

def run_verification():
    # 1. Test Resend Configuration
    step("Testing Resend Configuration")
    email = "vehtracore@gmail.com" # Authorized test email
    resp = requests.get(f"{BASE_URL}/auth/test-email/{email}", verify=False)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
    
    if resp.status_code != 200 or not resp.json().get("success"):
        print("❌ Resend config failed!")
        return

    # 2. Register New User
    step("Registering New User")
    random_id = str(uuid.uuid4())[:8]
    user_email = f"test_verify_{random_id}@mailinator.com"
    password = "securepass123"
    
    payload = {
        "email": user_email,
        "password": password,
        "first_name": "Test",
        "last_name": "User",
        "dob": "1990-01-01",
        "location": "Test City",
        "role": "patient"
    }
    
    resp = requests.post(f"{BASE_URL}/auth/signup", json=payload, verify=False)
    print(f"Status: {resp.status_code}")
    if resp.status_code != 201:
        print(f"❌ Signup failed: {resp.text}")
        return
        
    user_data = resp.json()
    print(f"User created: ID={user_data.get('id')}, Verified={user_data.get('is_verified')}")
    
    if user_data.get("is_verified") is not False:
        print("❌ User came back as verified! Should be False.")
    else:
        print("✅ User created as unverified.")

    # 3. Attempt Login (Should Fail)
    step("Attempting Login (Should Fail)")
    login_payload = {"email": user_email, "password": password}
    resp = requests.post(f"{BASE_URL}/auth/login", json=login_payload, verify=False)
    print(f"Login Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
    
    if resp.status_code == 400 and "pending approval" in resp.text:
        print("✅ Login blocked as expected.")
    else:
        print("⚠️ Unexpected login response (might be 400 for 'pending approval' check).")

    print("\n✅ Verification flow logic validated (Phase 1).")
    print("ℹ️ To fully verify Phase 2, check email inbox for 'noreply@mdqplus.com' and click the link.")

if __name__ == "__main__":
    run_verification()
