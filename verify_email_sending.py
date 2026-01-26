import smtplib
import os
from email.message import EmailMessage
from dotenv import load_dotenv

# Force load .env from backend folder if running from root
if os.path.exists("backend/.env"):
    load_dotenv("backend/.env")
else:
    load_dotenv()

def test_smtp():
    smtp_user = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    
    print(f"--- SMTP CONFIG CHECK ---")
    print(f"User: {smtp_user}")
    print(f"Server: {smtp_server}:{smtp_port}")
    print(f"Password Found? {'YES' if smtp_password else 'NO'}")
    print(f"-------------------------")

    if not smtp_user or not smtp_password:
        print("❌ ERROR: Credentials missing in .env")
        return

    try:
        print("1. Connecting to server...")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.set_debuglevel(1)  # Show full handshake
        
        print("2. Starting TLS...")
        server.starttls()
        
        print(f"3. Logging in as {smtp_user}...")
        server.login(smtp_user, smtp_password)
        
        print("4. Sending test email...")
        msg = EmailMessage()
        msg.set_content(f"This is a test email from MedIQ Backend Debugger.\n\nSent from: {os.getcwd()}")
        msg["Subject"] = "MedIQ SMTP Test"
        msg["From"] = smtp_user
        msg["To"] = smtp_user # Send to self
        
        server.send_message(msg)
        server.quit()
        print("SUCCESS: Email sent successfully!")
        
    except Exception as e:
        print(f"CONNECTION FAILED: {e}")

if __name__ == "__main__":
    test_smtp()
