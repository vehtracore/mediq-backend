import sys
import os
from datetime import date

# Ensure the script can see the 'app' package
sys.path.append(os.getcwd())

from app.core.database import SessionLocal, engine, Base
# Import ALL models so the Base knows what tables to build
from app.models import user, doctor, appointment, content, review, audit
from app.models.doctor import Doctor
from app.models.user import User
from app.core.security import get_password_hash

def seed_doctors():
    # --- THE FIX: CREATE TABLES IF MISSING ---
    print("🏗️  Checking database schema...")
    Base.metadata.create_all(bind=engine)
    print("✅  Tables verified/created.")
    # -----------------------------------------

    db = SessionLocal()

    if db.query(Doctor).first():
        print("Doctors already seeded.")
        db.close()
        return

    print("Seeding Doctors and their User accounts...")

    doctors_data = [
        {
            "email": "house@mediq.com",
            "password": "password123",
            "full_name": "Dr. Gregory House",
            "specialty": "Diagnostician",
            "bio": "Specializes in infectious diseases and nephrology. Known for unconventional methods.",
            "image_url": "https://i.pravatar.cc/150?u=house",
            "hourly_rate": 5000.0, # 5k NGN
            "rating": 4.8,
            "review_count": 120,
            "license": "MDCN-001",
            "exp": 15
        },
        {
            "email": "cuddy@mediq.com",
            "password": "password123",
            "full_name": "Dr. Lisa Cuddy",
            "specialty": "Endocrinologist",
            "bio": "Dean of Medicine. Expert in administrative medicine and endocrinology.",
            "image_url": "https://i.pravatar.cc/150?u=cuddy",
            "hourly_rate": 4500.0,
            "rating": 4.9,
            "review_count": 95,
            "license": "MDCN-002",
            "exp": 12
        },
        {
            "email": "wilson@mediq.com",
            "password": "password123",
            "full_name": "Dr. James Wilson",
            "specialty": "Oncologist",
            "bio": "Head of the Department of Oncology. Empathetic and dedicated to patient care.",
            "image_url": "https://i.pravatar.cc/150?u=wilson",
            "hourly_rate": 4800.0,
            "rating": 5.0,
            "review_count": 110,
            "license": "MDCN-003",
            "exp": 10
        },
        {
            "email": "jd@mediq.com",
            "password": "password123",
            "full_name": "Dr. John Dorian",
            "specialty": "General Practitioner",
            "bio": "Friendly and approachable GP. Focuses on holistic patient well-being.",
            "image_url": "https://i.pravatar.cc/150?u=jd",
            "hourly_rate": 3000.0,
            "rating": 4.7,
            "review_count": 60,
            "license": "MDCN-004",
            "exp": 5
        },
        {
            "email": "elliot@mediq.com",
            "password": "password123",
            "full_name": "Dr. Elliot Reid",
            "specialty": "Endocrinologist",
            "bio": "Private practice specialist. Expert in hormonal imbalances and diabetes care.",
            "image_url": "https://i.pravatar.cc/150?u=elliot",
            "hourly_rate": 3500.0,
            "rating": 4.6,
            "review_count": 55,
            "license": "MDCN-005",
            "exp": 6
        }
    ]

    for data in doctors_data:
        # 1. Create User
        existing_user = db.query(User).filter(User.email == data["email"]).first()
        if not existing_user:
            hashed_pwd = get_password_hash(data["password"])
            names = data["full_name"].split(" ")
            first_name = names[0] + " " + names[1] if len(names) > 2 else names[0]
            last_name = names[-1]

            new_user = User(
                email=data["email"],
                first_name=first_name,
                last_name=last_name,
                hashed_password=hashed_pwd,
                role="doctor",
                dob=date(1980, 1, 1),
                location="Lagos, Nigeria",
                is_active=True,
                is_banned=False
            )
            db.add(new_user)
            db.flush() # Generate ID
            user_id = new_user.id
        else:
            user_id = existing_user.id

        # 2. Create Doctor Profile
        # Check if profile exists to avoid duplicates
        existing_doctor = db.query(Doctor).filter(Doctor.user_id == user_id).first()
        if not existing_doctor:
            db_doctor = Doctor(
                user_id=user_id,
                full_name=data["full_name"],
                specialty=data["specialty"],
                bio=data["bio"],
                image_url=data["image_url"],
                hourly_rate=data["hourly_rate"],
                rating=data["rating"],
                review_count=data["review_count"],
                license_number=data["license"],
                is_verified=True,
                is_available=True,
                years_experience=data["exp"]
            )
            db.add(db_doctor)

    db.commit()
    print("✅ Successfully seeded 5 doctors into Cloud Database.")
    db.close()

if __name__ == "__main__":
    seed_doctors()