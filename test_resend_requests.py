import os

import requests
from dotenv import load_dotenv

load_dotenv('backend/.env')

RESEND_API_KEY = os.getenv('RESEND_API_KEY')
RESEND_FROM_EMAIL = os.getenv('RESEND_FROM_EMAIL', 'MedIQ <noreply@mdqplus.com>')
TEST_EMAIL_TO = os.getenv('TEST_EMAIL_TO')


def test_resend_requests():
    if not RESEND_API_KEY:
        raise SystemExit('Set RESEND_API_KEY before running this script.')
    if not TEST_EMAIL_TO:
        raise SystemExit('Set TEST_EMAIL_TO before running this script.')

    print('Testing Resend via raw requests...')

    url = 'https://api.resend.com/emails'
    headers = {
        'Authorization': f'Bearer {RESEND_API_KEY}',
        'Content-Type': 'application/json',
    }
    data = {
        'from': RESEND_FROM_EMAIL,
        'to': [TEST_EMAIL_TO],
        'subject': 'MedIQ Raw Requests Test',
        'html': 'This is a raw requests test.',
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        print(f'Status: {resp.status_code}')
        print(f'Response: {resp.text}')
    except Exception as exc:
        print(f'Failed: {exc}')


if __name__ == '__main__':
    test_resend_requests()
