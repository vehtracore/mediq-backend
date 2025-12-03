import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure the SDK
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("WARNING: GEMINI_API_KEY not found in .env file.")

# Initialize the model
# CHANGED: using 'gemini-1.5-flash-latest' which is often more stable for resolution
# If this still fails, we will switch to 'gemini-pro'
model = genai.GenerativeModel('gemini-2.0-flash')

# ... (imports and model setup remain the same)

SYSTEM_INSTRUCTION = """
You are MedIQ, an efficient medical triage assistant. 
Your Goal: Quickly assess symptoms and recommend the next step (Self-care, Doctor, or Emergency).

**Rules for Interaction:**
1. **Speed is Key:** Do NOT ask endless follow-up questions. Gather the bare minimum context in ONE response, then provide an assessment in the next.
2. **Assessment Format:**
   - **Likely Causes:** (List 1-2 possibilities)
   - **Recommended Action:** (Self-care / See Doctor / Emergency)
   - **Immediate Relief:** (1 simple tip, e.g., "Hydrate", "Rest in dark room")
3. **No Disclaimer Spam:** Do NOT include a disclaimer in every message. The application interface handles this legal warning. Only include a warning if the situation is a critical emergency.
4. **Tone:** Professional, concise, and direct. 

**Example Interaction:**
User: "I have a throbbing headache and light sensitivity."
AI: "That sounds like a migraine. **Recommended Action:** Rest in a dark, quiet room. If it persists for >24 hours, consult a doctor."
"""

# ... (rest of the file remains the same)

async def get_medical_response(user_text: str) -> str:
    """
    Sends the user's symptoms to Gemini and returns the triage advice.
    """
    if not GEMINI_API_KEY:
        return "System Error: AI Service is not configured properly."

    try:
        # Construct the prompt with the persona and user input
        prompt = f"{SYSTEM_INSTRUCTION}\n\nUser Input: {user_text}"
        
        # Async generation for non-blocking I/O
        response = await model.generate_content_async(prompt)
        
        return response.text
    except Exception as e:
        # Log the actual error
        print(f"Gemini API Error: {e}")
        return "I'm having trouble connecting to the medical database right now. Please try again in a moment."