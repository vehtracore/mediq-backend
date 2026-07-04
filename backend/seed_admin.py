import os
import sys
from datetime import date

sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import User


def seed_admin():
    admin_email = os.getenv('ADMIN_EMAIL', 'owner@mdqplus.com')
    admin_password = os.getenv('ADMIN_PASSWORD')
    if not admin_password:
        raise SystemExit('Set ADMIN_PASSWORD before running seed_admin.py.')

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == admin_email).first():
            print(f'Admin account ({admin_email}) already exists.')
            return

        print(f'Creating Super Admin: {admin_email}...')

        admin_user = User(
            email=admin_email,
            first_name='Super',
            last_name='Admin',
            dob=date(1990, 1, 1),
            hashed_password=get_password_hash(admin_password),
            role='admin',
            is_active=True,
            is_banned=False,
        )

        db.add(admin_user)
        db.commit()
        print('Admin account created successfully.')
        print(f'Email: {admin_email}')
        print('Password: [HIDDEN]')
    finally:
        db.close()


if __name__ == '__main__':
    seed_admin()
