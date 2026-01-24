import os
import google.generativeai as genai
# Read .env manually
KEY = None
try:
    with open("backend/.env", "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                KEY = line.strip().split("=")[1]
                break
except Exception:
    pass

if not KEY:
    print("No Key found")
    exit(1)
    
genai.configure(api_key=KEY)

print("Listing supported models for generateContent...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
