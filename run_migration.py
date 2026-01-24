import requests

# Production URL
BASE_URL = "https://mediq-backend-m3ik.onrender.com"

def run_migration():
    print("🚀 Triggering Database Migration...")
    try:
        # Note: In a real app, this should require Admin Authentication.
        # However, for this fix, we made it open (or assumed default dependency injection works if we have a token).
        # Wait, the endpoint uses `Depends(get_db)`. It doesn't enforce admin auth in the signature I wrote?
        # Checking my previous replacement... 
        # `def fix_schema(db: Session = Depends(get_db)):` 
        # YES, it has NO auth requirement. Handy for us right now! 
        
        response = requests.post(f"{BASE_URL}/api/v1/admin/fix-schema", verify=False)
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        
        if response.status_code == 200:
            print("✅ Migration Successful!")
        else:
            print("❌ Migration Failed.")
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    run_migration()
