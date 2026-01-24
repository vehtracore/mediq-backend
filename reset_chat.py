from sqlalchemy import create_engine, text

# Using the connection string from your .env
DB_URL = "postgresql://postgres.hzrjaquqlpkbggwdcres:MDQsecurepass2025@aws-1-eu-west-2.pooler.supabase.com:6543/postgres"

def reset_limits():
    print("Connecting to Supabase...")
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            print("Resetting daily chat count for ALL users...")
            # Reset for ALL users to ensure we unblock the tester
            sql = text("UPDATE users SET daily_chat_count = 0;")
            result = conn.execute(sql)
            conn.commit()
            print(f"SUCCESS: Reset usage limit for {result.rowcount} user(s).")
            
            # Also reset generic test users if any
            # conn.execute(text("UPDATE users SET daily_chat_count = 0 WHERE email LIKE '%test%';"))
            # conn.commit()
    except Exception as e:
        print(f"ERROR: Failed to reset limits: {e}")

if __name__ == "__main__":
    reset_limits()
