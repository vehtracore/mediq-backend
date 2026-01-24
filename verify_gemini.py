import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(dotenv_path="backend/.env")

KEY = os.getenv("GEMINI_API_KEY")
print(f"Checking Key: {KEY[:5]}...{KEY[-5:] if KEY else 'None'}")

if not KEY:
    print("❌ No API Key found")
    exit(1)

genai.configure(api_key=KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

try:
    print("Attempting to generate content...")
    response = model.generate_content("Hello, can you hear me?")
    print("✅ Success!")
    print("Response:", response.text)
except Exception as e:
    print("❌ Failed!")
    print(e)
