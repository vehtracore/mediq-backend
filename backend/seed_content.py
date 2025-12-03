import sys
import os

sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.models.content import HealthTip

def seed_content():
    db = SessionLocal()
    
    if db.query(HealthTip).first():
        print("Content already seeded.")
        db.close()
        return

    tips_data = [
        {
            "title": "10 Signs of Dehydration",
            "category": "Prevention",
            "read_time": "2 min",
            "image_url": "https://i.pravatar.cc/150?u=water", # Placeholder
            "content": "Dehydration happens when your body loses more fluid than you take in. Look out for dry mouth, fatigue, and dizziness. Drink at least 8 glasses of water a day."
        },
        {
            "title": "Managing High Blood Pressure",
            "category": "Cardiology",
            "read_time": "5 min",
            "image_url": "https://i.pravatar.cc/150?u=heart",
            "content": "High blood pressure is a silent killer. Reduce sodium intake, exercise regularly, and manage stress to keep your heart healthy."
        },
        {
            "title": "Sleep Hygiene Basics",
            "category": "Wellness",
            "read_time": "3 min",
            "image_url": "https://i.pravatar.cc/150?u=sleep",
            "content": "Good sleep improves brain performance and mood. Stick to a schedule, avoid caffeine late in the day, and create a restful environment."
        },
        {
            "title": "Understanding Antibiotics",
            "category": "Medication",
            "read_time": "4 min",
            "image_url": "https://i.pravatar.cc/150?u=pill",
            "content": "Antibiotics treat bacterial infections, not viruses like the flu. Always finish your prescribed course to prevent resistance."
        },
        {
            "title": "Flu Season Precautions",
            "category": "Immunity",
            "read_time": "2 min",
            "image_url": "https://i.pravatar.cc/150?u=flu",
            "content": "Wash hands frequently, get vaccinated, and avoid close contact with sick individuals to stay healthy this flu season."
        }
    ]

    for data in tips_data:
        tip = HealthTip(**data)
        db.add(tip)

    db.commit()
    print("Successfully seeded 5 Health Tips.")
    db.close()

if __name__ == "__main__":
    seed_content()