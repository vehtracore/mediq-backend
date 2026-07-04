import os

import resend
from dotenv import load_dotenv

load_dotenv('backend/.env')

RESEND_API_KEY = os.getenv('RESEND_API_KEY')
RESEND_FROM_EMAIL = os.getenv('RESEND_FROM_EMAIL', 'MedIQ <noreply@mdqplus.com>')
TEST_EMAIL_TO = os.getenv('TEST_EMAIL_TO')


def test_resend_direct():
    if not RESEND_API_KEY:
        raise SystemExit('Set RESEND_API_KEY before running this script.')
    if not TEST_EMAIL_TO:
        raise SystemExit('Set TEST_EMAIL_TO before running this script.')

    print('Testing Resend library direct send...')
    resend.api_key = RESEND_API_KEY

    try:
        result = resend.Emails.send({
            'from': RESEND_FROM_EMAIL,
            'to': [TEST_EMAIL_TO],
            'subject': 'MedIQ Direct Test',
            'html': 'This is a direct test.',
        })
        print(f'Success: {result}')
    except Exception as exc:
        print(f'Failed: {exc}')


if __name__ == '__main__':
    test_resend_direct()
