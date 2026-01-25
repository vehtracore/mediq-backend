import requests

def check_prod_email():
    url = "https://mediq-backend-m3ik.onrender.com/api/v1/auth/debug-email"
    print(f"📡 Connecting to {url}...")
    
    try:
        response = requests.get(url, params={"email": "mediq_debug_agent@mailinator.com"})
        print(f"Status Code: {response.status_code}")
        print("Response JSON:")
        print(response.json())
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    check_prod_email()
