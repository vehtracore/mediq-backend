import os

from dotenv import load_dotenv

load_dotenv('backend/.env')

RESEND_API_KEY = os.getenv('RESEND_API_KEY')
RESEND_FROM_EMAIL = os.getenv('RESEND_FROM_EMAIL', 'MedIQ <noreply@mdqplus.com>')
TEST_EMAIL_TO = os.getenv('TEST_EMAIL_TO')


def test_resend():
    if not RESEND_API_KEY:
        raise SystemExit('Set RESEND_API_KEY before running this script.')
    if not TEST_EMAIL_TO:
        raise SystemExit('Set TEST_EMAIL_TO before running this script.')

    try:
        import resend

        resend.api_key = RESEND_API_KEY
        print('Testing Resend API...')

        result = resend.Emails.send({
            'from': RESEND_FROM_EMAIL,
            'to': [TEST_EMAIL_TO],
            'subject': 'MedIQ Resend Test',
            'text': 'This is a test email from MedIQ using Resend HTTP API.',
        })

        print(f'SUCCESS! Email ID: {result}')

    except Exception as exc:
        print(f'FAILED: {exc}')


if __name__ == '__main__':
    test_resend()
