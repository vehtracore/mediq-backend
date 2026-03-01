import os
import resend

RESEND_API_KEY = "re_HQAuhT8U_8tbbait4RJ9iyXDPGPGSamgq"
RESEND_FROM_EMAIL = "MedIQ <noreply@mdqplus.com>"

def test_resend_direct():
    print(f"Testing Resend library direct send...")
    resend.api_key = RESEND_API_KEY
    
    try:
        result = resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": ["vehtracore@gmail.com"],
            "subject": "MedIQ Direct Test",
            "html": "This is a direct test."
        })
        print(f"Success: {result}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_resend_direct()
