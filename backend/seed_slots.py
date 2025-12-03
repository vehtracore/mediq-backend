import sys
import os
from datetime import datetime, timedelta

# Ensure the script can see the 'app' package
sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.models.doctor import Doctor
from app.models.appointment import DoctorSlot
# --- CRITICAL FIX: Import User AND Review so Appointment relationships work ---
from app.models.user import User 
from app.models.review import Review

def seed_slots():
    db = SessionLocal()
    
    # 1. Find Dr. Gregory House (ID 1)
    doctor = db.query(Doctor).filter(Doctor.id == 1).first()
    if not doctor:
        print("Error: Doctor ID 1 not found. Run seed_doctors.py first.")
        db.close()
        return

    print(f"Creating slots for {doctor.full_name}...")

    # 2. Calculate "Tomorrow" at 9:00 AM
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    start_time_base = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)

    # 3. Create 5 slots (9 AM to 1 PM)
    slots_created = 0
    for i in range(5):
        slot_time = start_time_base + timedelta(hours=i)
        
        # Check if exists to prevent duplicates
        exists = db.query(DoctorSlot).filter(
            DoctorSlot.doctor_id == doctor.id, 
            DoctorSlot.start_time == slot_time
        ).first()

        if not exists:
            slot = DoctorSlot(
                doctor_id=doctor.id,
                start_time=slot_time,
                is_booked=False
            )
            db.add(slot)
            slots_created += 1

    db.commit()
    print(f"Successfully created {slots_created} slots for {start_time_base.date()}.")
    db.close()

if __name__ == "__main__":
    seed_slots()