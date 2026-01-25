import smtplib
import os
from email.message import EmailMessage
from dotenv import load_dotenv

# Load from .env file explicitly
load_dotenv("backend/.env")

def test_email():
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")

    print(f"📧 Testing Email with:")
    print(f"User: {smtp_email}")
    print(f"Pass: {'*' * len(smtp_password) if smtp_password else 'NONE'}")

    if not smtp_email or not smtp_password:
        print("❌ Credentials missing in .env")
        return

    try:
        msg = EmailMessage()
        msg.set_content("This is a test email from MedIQ Debugger.")
        msg['Subject'] = "MedIQ SMTP Test"
        msg['From'] = smtp_email
        msg['To'] = smtp_email # Send to self

        print("Connecting to smtp.gmail.com:465...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            print("Logging in...")
            server.login(smtp_email, smtp_password)
            print("Sending message...")
            server.send_message(msg)
        
        print("✅ Email sent successfully! Check your inbox.")
    except Exception as e:
        print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test_email()
