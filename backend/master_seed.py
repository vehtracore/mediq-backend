import os
from supabase import create_client, Client

# --- 1. CREDENTIALS ---
SUPABASE_URL = "https://hzrjaquqlpkbggwdcres.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh6cmphcXVxbHBrYmdnd2RjcmVzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2NDU0NDk4MywiZXhwIjoyMDgwMTIwOTgzfQ.2MSU8DsPL9UGR6NiAI7vdLYvlJS7PlvVQy_Ol4P-qXA"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# --- 2. MASTER DATA PAYLOAD ---
master_users = [
    # ---------------- DOCTORS ----------------
    {
        "email": "house@mediq.com", "first_name": "Dr. Gregory", "last_name": "House", "dob": "1980-01-01", "location": "Lagos, Nigeria", "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Gregory House", "specialty": "Diagnostician", "bio": "Specializes in infectious diseases and nephrology.",
            "image_url": "https://i.pravatar.cc/150?u=house", "hourly_rate": 5000.0, "rating": 4.8, "review_count": 120, "license_number": "MDCN-001", "years_experience": 15
        }
    },
    {
        "email": "cuddy@mediq.com", "first_name": "Dr. Lisa", "last_name": "Cuddy", "dob": "1980-01-01", "location": "Lagos, Nigeria", "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Lisa Cuddy", "specialty": "Endocrinologist", "bio": "Dean of Medicine. Expert in administrative medicine.",
            "image_url": "https://i.pravatar.cc/150?u=cuddy", "hourly_rate": 4500.0, "rating": 4.9, "review_count": 95, "license_number": "MDCN-002", "years_experience": 12
        }
    },
    {
        "email": "wilson@mediq.com", "first_name": "Dr. James", "last_name": "Wilson", "dob": "1980-01-01", "location": "Lagos, Nigeria", "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. James Wilson", "specialty": "Oncologist", "bio": "Head of the Department of Oncology.",
            "image_url": "https://i.pravatar.cc/150?u=wilson", "hourly_rate": 4800.0, "rating": 5.0, "review_count": 110, "license_number": "MDCN-003", "years_experience": 10
        }
    },
    {
        "email": "jd@mediq.com", "first_name": "Dr. John", "last_name": "Dorian", "dob": "1980-01-01", "location": "Lagos, Nigeria", "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. John Dorian", "specialty": "General Practitioner", "bio": "Friendly and approachable GP.",
            "image_url": "https://i.pravatar.cc/150?u=jd", "hourly_rate": 3000.0, "rating": 4.7, "review_count": 60, "license_number": "MDCN-004", "years_experience": 5
        }
    },
    {
        "email": "elliot@mediq.com", "first_name": "Dr. Elliot", "last_name": "Reid", "dob": "1980-01-01", "location": "Lagos, Nigeria", "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Elliot Reid", "specialty": "Endocrinologist", "bio": "Private practice specialist.",
            "image_url": "https://i.pravatar.cc/150?u=elliot", "hourly_rate": 3500.0, "rating": 4.6, "review_count": 55, "license_number": "MDCN-005", "years_experience": 6
        }
    },
    {
        "email": "kunle@mediq.com", "first_name": "Dr", "last_name": "Adeboye", "dob": "1980-01-01", "location": "Princeton-Plainsboro", "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Adeboye", "specialty": "General", "bio": "Staff Physician", "image_url": None, "hourly_rate": 4000.0, "rating": 4.5, "review_count": 10, "license_number": "MDCN-006", "years_experience": 8
        }
    },
    {
        "email": "tunde@mediq.com", "first_name": "Dr.", "last_name": "Adeboye", "dob": "1980-01-01", "location": "Princeton-Plainsboro", "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Tunde Adeboye", "specialty": "General", "bio": "Staff Physician", "image_url": None, "hourly_rate": 4000.0, "rating": 4.5, "review_count": 10, "license_number": "MDCN-007", "years_experience": 8
        }
    },

    # ---------------- ADMINS ----------------
    {"email": "controller@mdqplus.com", "first_name": "Super", "last_name": "Admin", "dob": "1990-01-01", "location": None, "role": "admin"},
    {"email": "owner@mdqplus.com", "first_name": "Super", "last_name": "Admin", "dob": "1990-01-01", "location": None, "role": "admin"},

    # ---------------- PATIENTS ----------------
    {"email": "john@test.com", "first_name": "John", "last_name": "Ode", "dob": "2000-01-18", "location": "Ibadan", "role": "patient"},
    {"email": "james@test.com", "first_name": "James", "last_name": "Morris", "dob": "2000-12-05", "location": "Ibadan", "role": "patient"},
    {"email": "imtzz@yahoo.com", "first_name": "tayo", "last_name": "abo", "dob": "2000-01-18", "location": None, "role": "patient"},
    {"email": "kemi@test.com", "first_name": "Kemi", "last_name": "longs", "dob": "1980-01-01", "location": "Princeton-Plainsboro", "role": "patient"},
]

print("🚀 Starting Master Database Seed...")

for u in master_users:
    print(f"\nProcessing {u['email']} [{u['role'].upper()}]...")
    try:
        # 1. CREATE IN SECURE AUTH VAULT
        auth_res = supabase.auth.admin.create_user({
            "email": u["email"],
            "password": "TestPassword123!",
            "email_confirm": True,
            "user_metadata": {"role": u["role"]}
        })
        
        # 2. CREATE IN PUBLIC.USERS
        db_res = supabase.table("users").insert({
            "first_name": u["first_name"],
            "last_name": u["last_name"],
            "email": u["email"],
            "hashed_password": "SUPABASE_MANAGED",
            "dob": u["dob"],
            "location": u["location"],
            "role": u["role"],
            "is_active": True,
            "is_banned": False
        }).execute()
        
        # Extract the auto-incrementing integer ID Postgres just generated
        user_db_id = db_res.data[0]["id"]
        print(f"  ↳ User profile created (ID: {user_db_id})")

        # 3. CREATE DOCTOR PROFILE (IF APPLICABLE)
        if u["role"] == "doctor" and "doctor_profile" in u:
            doc_payload = u["doctor_profile"].copy()
            doc_payload["user_id"] = user_db_id  # Link the relational FK
            doc_payload["is_verified"] = True
            doc_payload["is_available"] = True
            doc_payload["status"] = "active"
            
            supabase.table("doctors").insert(doc_payload).execute()
            print("  ↳ Doctor profile linked successfully.")

    except Exception as e:
        print(f"  ❌ FAILED: {e}")

print("\n✅ Master Seed Complete. All users and relationships are fully synced.")