import sys
import os
import uvicorn

if __name__ == "__main__":
    # Add backend to sys.path
    sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))
    
    os.environ["RESEND_API_KEY"] = "re_HQAuhT8U_8tbbait4RJ9iyXDPGPGSamgq"
    os.environ["RESEND_FROM_EMAIL"] = "MedIQ <noreply@mdqplus.com>"
    os.environ["DATABASE_URL"] = "postgresql://postgres.hzrjaquqlpkbggwdcres:MDQsecurepass2025@aws-1-eu-west-2.pooler.supabase.com:6543/postgres"
    
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
