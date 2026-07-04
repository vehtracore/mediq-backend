import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv('backend/.env')

DB_URL = os.getenv('DATABASE_URL')


def reset_limits():
    if not DB_URL:
        raise SystemExit('Set DATABASE_URL before running this script.')

    print('Connecting to database...')
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            print('Resetting daily chat count for ALL users...')
            sql = text('UPDATE users SET daily_chat_count = 0;')
            result = conn.execute(sql)
            conn.commit()
            print(f'SUCCESS: Reset usage limit for {result.rowcount} user(s).')
    except Exception as exc:
        print(f'ERROR: Failed to reset limits: {exc}')


if __name__ == '__main__':
    reset_limits()
