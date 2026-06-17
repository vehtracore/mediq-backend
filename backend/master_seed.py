import os

from supabase import Client, create_client


# --- 1. CREDENTIALS ---
# Set these to staging values before running:
#   $env:STAGING_SUPABASE_URL="https://yubenefrqokzhikajpkf.supabase.co"
#   $env:STAGING_SUPABASE_SERVICE_ROLE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl1YmVuZWZycW9remhpa2FqcGtmIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MTY4NDk0MCwiZXhwIjoyMDk3MjYwOTQwfQ.z5obTzLdcKYcxicDxgN_w0WC9Hf6MZ9g0l4KDKyTTXo"
SUPABASE_URL = os.getenv("STAGING_SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = (
    os.getenv("STAGING_SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "Set STAGING_SUPABASE_URL and STAGING_SUPABASE_SERVICE_ROLE_KEY before seeding."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


USER_DEFAULTS = {
    "hashed_password": "SUPABASE_MANAGED",
    "image_url": None,
    "is_active": True,
    "is_banned": False,
    "is_verified": True,
    "verification_token": None,
    "auth_provider": None,
    "plan": "free",
    "subscription_expiry": None,
    "auto_renew": False,
    "monthly_chat_count": 0,
    "monthly_chat_image_count": 0,
    "last_chat_month_reset": None,
    "rolling_chat_count": 0,
    "rolling_chat_image_count": 0,
    "rolling_chat_window_start": None,
    "burst_chat_count": 0,
    "burst_start_time": None,
    "chat_blocked_until": None,
    "daily_chat_count": 0,
    "last_chat_date": None,
    "monthly_lab_count": 0,
    "last_lab_reset": None,
    "monthly_audio_count": 0,
    "rolling_audio_count": 0,
    "rolling_audio_window_start": None,
    "last_audio_month_reset": None,
    "primary_account_id": None,
    "blood_type": None,
    "allergies": None,
    "chronic_conditions": None,
    "medications": None,
    "past_surgeries": None,
    "settings_theme": "light",
    "settings_notifications": True,
    "settings_email_updates": False,
    "kin_phone": None,
    "emergency_sms_enabled": False,
    "last_emergency_trigger": None,
    "emergency_sms_count": 0,
    "paystack_subscription_code": None,
    "paystack_email_token": None,
    "fcm_token": None,
    "deletion_requested_at": None,
}


# --- 2. MASTER DATA PAYLOAD ---
master_users = [
    # ---------------- DOCTORS ----------------
    {
        "email": "house@mediq.com",
        "first_name": "Dr. Gregory",
        "last_name": "House",
        "dob": "1980-01-01",
        "location": "Lagos, Nigeria",
        "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Gregory House",
            "specialty": "Diagnostician",
            "bio": "Specializes in infectious diseases and nephrology.",
            "image_url": None,
            "hourly_rate": 5000.0,
            "rating": 4.8,
            "review_count": 120,
            "license_number": "MDCN-001",
            "years_experience": 15,
        },
    },
    {
        "email": "cuddy@mediq.com",
        "first_name": "Dr. Lisa",
        "last_name": "Cuddy",
        "dob": "1980-01-01",
        "location": "Lagos, Nigeria",
        "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Lisa Cuddy",
            "specialty": "Endocrinologist",
            "bio": "Dean of Medicine. Expert in administrative medicine.",
            "image_url": None,
            "hourly_rate": 4500.0,
            "rating": 4.9,
            "review_count": 95,
            "license_number": "MDCN-002",
            "years_experience": 12,
        },
    },
    {
        "email": "wilson@mediq.com",
        "first_name": "Dr. James",
        "last_name": "Wilson",
        "dob": "1980-01-01",
        "location": "Lagos, Nigeria",
        "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. James Wilson",
            "specialty": "Oncologist",
            "bio": "Head of the Department of Oncology.",
            "image_url": None,
            "hourly_rate": 4800.0,
            "rating": 5.0,
            "review_count": 110,
            "license_number": "MDCN-003",
            "years_experience": 10,
        },
    },
    {
        "email": "jd@mediq.com",
        "first_name": "Dr. John",
        "last_name": "Dorian",
        "dob": "1980-01-01",
        "location": "Lagos, Nigeria",
        "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. John Dorian",
            "specialty": "General Practitioner",
            "bio": "Friendly and approachable GP.",
            "image_url": None,
            "hourly_rate": 3000.0,
            "rating": 4.7,
            "review_count": 60,
            "license_number": "MDCN-004",
            "years_experience": 5,
        },
    },
    {
        "email": "elliot@mediq.com",
        "first_name": "Dr. Elliot",
        "last_name": "Reid",
        "dob": "1980-01-01",
        "location": "Lagos, Nigeria",
        "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Elliot Reid",
            "specialty": "Endocrinologist",
            "bio": "Private practice specialist.",
            "image_url": None,
            "hourly_rate": 3500.0,
            "rating": 4.6,
            "review_count": 55,
            "license_number": "MDCN-005",
            "years_experience": 6,
        },
    },
    {
        "email": "kunle@mediq.com",
        "first_name": "Dr",
        "last_name": "Adeboye",
        "dob": "1980-01-01",
        "location": "Princeton-Plainsboro",
        "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Adeboye",
            "specialty": "General",
            "bio": "Staff Physician",
            "image_url": None,
            "hourly_rate": 4000.0,
            "rating": 4.5,
            "review_count": 10,
            "license_number": "MDCN-006",
            "years_experience": 8,
        },
    },
    {
        "email": "tunde@mediq.com",
        "first_name": "Dr.",
        "last_name": "Adeboye",
        "dob": "1980-01-01",
        "location": "Princeton-Plainsboro",
        "role": "doctor",
        "doctor_profile": {
            "full_name": "Dr. Tunde Adeboye",
            "specialty": "General",
            "bio": "Staff Physician",
            "image_url": None,
            "hourly_rate": 4000.0,
            "rating": 4.5,
            "review_count": 10,
            "license_number": "MDCN-007",
            "years_experience": 8,
        },
    },
    # ---------------- ADMINS ----------------
    {
        "email": "controller@mdqplus.com",
        "first_name": "Super",
        "last_name": "Admin",
        "dob": "1990-01-01",
        "location": None,
        "role": "admin",
    },
    {
        "email": "owner@mdqplus.com",
        "first_name": "Super",
        "last_name": "Admin",
        "dob": "1990-01-01",
        "location": None,
        "role": "admin",
    },
    # ---------------- PATIENTS ----------------
    {
        "email": "john@test.com",
        "first_name": "John",
        "last_name": "Ode",
        "dob": "2000-01-18",
        "location": "Ibadan",
        "role": "patient",
    },
    {
        "email": "james@test.com",
        "first_name": "James",
        "last_name": "Morris",
        "dob": "2000-12-05",
        "location": "Ibadan",
        "role": "patient",
    },
    {
        "email": "imtzz@yahoo.com",
        "first_name": "tayo",
        "last_name": "abo",
        "dob": "2000-01-18",
        "location": None,
        "role": "patient",
    },
    {
        "email": "kemi@test.com",
        "first_name": "Kemi",
        "last_name": "longs",
        "dob": "1980-01-01",
        "location": "Princeton-Plainsboro",
        "role": "patient",
    },
]


def ensure_auth_user(user_data: dict) -> None:
    try:
        supabase.auth.admin.create_user(
            {
                "email": user_data["email"],
                "password": "TestPassword123!",
                "email_confirm": True,
                "user_metadata": {"role": user_data["role"]},
            }
        )
        print("  -> Auth user created")
    except Exception as exc:
        message = str(exc).lower()
        if "already" in message or "registered" in message or "exists" in message:
            print("  -> Auth user already exists")
            return
        raise


def upsert_public_user(user_data: dict) -> int:
    user_payload = {
        **USER_DEFAULTS,
        "first_name": user_data["first_name"],
        "last_name": user_data["last_name"],
        "email": user_data["email"],
        "dob": user_data["dob"],
        "location": user_data["location"],
        "role": user_data["role"],
    }

    response = (
        supabase.table("users")
        .upsert(user_payload, on_conflict="email")
        .execute()
    )
    return int(response.data[0]["id"])


def upsert_doctor_profile(user_db_id: int, doctor_profile: dict) -> None:
    doc_payload = {
        **doctor_profile,
        "user_id": user_db_id,
        "is_verified": True,
        "is_available": True,
        "status": "active",
        "mdcn_license_url": None,
        "indemnity_cert_url": None,
        "documents_url": None,
        "rejection_reason": None,
        "bank_code": None,
        "account_number": None,
        "paystack_subaccount_code": None,
    }

    supabase.table("doctors").upsert(
        doc_payload,
        on_conflict="license_number",
    ).execute()


print("Starting Master Database Seed...")

for user_data in master_users:
    print(f"\nProcessing {user_data['email']} [{user_data['role'].upper()}]...")
    try:
        ensure_auth_user(user_data)
        user_db_id = upsert_public_user(user_data)
        print(f"  -> User profile upserted (ID: {user_db_id})")

        doctor_profile = user_data.get("doctor_profile")
        if user_data["role"] == "doctor" and doctor_profile:
            upsert_doctor_profile(user_db_id, doctor_profile)
            print("  -> Doctor profile linked successfully")

    except Exception as exc:
        print(f"  FAILED: {exc}")

print("\nMaster Seed Complete.")
