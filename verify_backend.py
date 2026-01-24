import requests
import json

BASE_URL = "https://mediq-backend-m3ik.onrender.com/api/v1/auth"
LOGIN_EMAIL = "john@test.com"
LOGIN_PASSWORD = "password123" 

def test_persistence():
    # 1. Login
    print(f"Logging in as {LOGIN_EMAIL}...")
    login_resp = requests.post(f"{BASE_URL}/login", json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD})
    
    if login_resp.status_code != 200:
        print(f"❌ Login Failed: {login_resp.text}")
        return

    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Login Successful")

    # 2. Update Image URL
    test_url = "https://res.cloudinary.com/demo/image/upload/sample.jpg"
    print(f"Updating image_url to: {test_url}")
    
    update_data = {
        "image_url": test_url,
        "first_name": "John" # Sending another field just in case
    }
    
    update_resp = requests.put(f"{BASE_URL}/me", json=update_data, headers=headers)
    
    if update_resp.status_code != 200:
        print(f"❌ Update Failed: {update_resp.text}")
        return
        
    print("✅ Update Request Successful")
    
    # 3. Fetch User to Verify
    print("Fetching user profile to verify persistence...")
    me_resp = requests.get(f"{BASE_URL}/me", headers=headers)
    
    userData = me_resp.json()
    saved_url = userData.get("image_url")
    
    print(f"📦 Fetched image_url: {saved_url}")
    
    if saved_url == test_url:
        print("🎉 SUCCESS: Backend is saving image_url correctly!")
    else:
        print("❌ FAILURE: Backend did NOT save image_url.")
        print(f"Full Response: {userData}")

if __name__ == "__main__":
    test_persistence()
