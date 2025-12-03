import sys
import os
from datetime import date

sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.models.user import User
from app.core.security import get_password_hash

def seed_admin():
    db = SessionLocal()
    
    # --- 🔒 SECURITY CONFIGURATION ---
    # CHANGE THESE VALUES to your preferred secure credentials
    ADMIN_EMAIL = "controller@mdqplus.com" 
    ADMIN_PASSWORD = "Superadmin2025!" 
    # ---------------------------------

    if db.query(User).filter(User.email == ADMIN_EMAIL).first():
        print(f"Admin account ({ADMIN_EMAIL}) already exists.")
        return

    print(f"Creating Super Admin: {ADMIN_EMAIL}...")

    admin_user = User(
        email=ADMIN_EMAIL,
        first_name="Super",
        last_name="Admin",
        dob=date(1990, 1, 1),
        hashed_password=get_password_hash(ADMIN_PASSWORD),
        role="admin",
        is_active=True,
        is_banned=False
    )
    
    db.add(admin_user)
    db.commit()
    print("✅ Admin account created successfully.")
    print(f"📧 Email: {ADMIN_EMAIL}")
    print("🔑 Password: [HIDDEN] (The one you set in the script)")
    db.close()

if __name__ == "__main__":
    seed_admin()