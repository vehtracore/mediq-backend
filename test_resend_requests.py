import requests
import json
import os

RESEND_API_KEY = "re_HQAuhT8U_8tbbait4RJ9iyXDPGPGSamgq"
RESEND_FROM_EMAIL = "MedIQ <noreply@mdqplus.com>"

def test_resend_requests():
    print(f"Testing Resend via raw requests...")
    
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "from": RESEND_FROM_EMAIL,
        "to": ["vehtracore@gmail.com"],
        "subject": "MedIQ Raw Requests Test",
        "html": "This is a raw requests test."
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, verify=False)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_resend_requests()
