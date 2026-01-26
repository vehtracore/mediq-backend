import os
from dotenv import load_dotenv

# Load local .env
load_dotenv("backend/.env")

# Override with the actual key from Render
RESEND_API_KEY = "re_HQAuhT8U_8tbbait4RJ9iyXDPGPGSamgq"

def test_resend():
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        
        print(f"Testing Resend API...")
        print(f"API Key: {RESEND_API_KEY[:10]}...")
        
        result = resend.Emails.send({
            "from": "MedIQ <onboarding@resend.dev>",
            "to": ["jennynlongs@gmail.com"],
            "subject": "MedIQ Resend Test",
            "text": "This is a test email from MedIQ using Resend HTTP API.\n\nIf you receive this, Resend is working!"
        })
        
        print(f"SUCCESS! Email ID: {result}")
        
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    test_resend()
