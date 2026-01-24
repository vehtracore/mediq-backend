import os
import google.generativeai as genai
from dotenv import load_dotenv
import PIL.Image  # <--- NEW IMPORT (Requires 'Pillow' library)

# Load environment variables
load_dotenv()

import logging

# Configure Logging
logger = logging.getLogger("uvicorn.error")

# Configure the SDK
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

logger.info(f"DEBUG: Loading AI Service. Key found? {bool(GEMINI_API_KEY)}")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("DEBUG: Gemini Configured Successfully")
    except Exception as e:
        logger.error(f"DEBUG: Gemini Configuration Failed: {e}")
else:
    logger.warning("WARNING: GEMINI_API_KEY not found in environment.")

# Initialize the model (Flash is great for vision + speed)
# 'gemini-1.5-flash' was deprecated/not found. Using 'gemini-1.5-flash-latest'
model = genai.GenerativeModel('gemini-1.5-flash-latest')

SYSTEM_INSTRUCTION = """
You are MedIQ, an efficient medical triage assistant. 
Your Goal: Quickly assess symptoms (text or visual) and recommend the next step (Self-care, Doctor, or Emergency).

**Rules for Interaction:**
1. **Visual Analysis:** If an image is provided, analyze visible symptoms (rashes, swelling, wounds) or read text (prescriptions/reports).
2. **Speed is Key:** Gather context in ONE response.
3. **Assessment Format:**
   - **Visual Observation:** (If image provided: "I see redness/swelling...")
   - **Likely Causes:** (List 1-2 possibilities)
   - **Recommended Action:** (Self-care / See Doctor / Emergency)
   - **Immediate Relief:** (1 simple tip)
4. **Tone:** Professional, concise, direct. NO disclaimers unless critical.
"""

async def get_medical_response(user_text: str, image_url: str = None) -> str:
    """
    Sends text AND optional image to Gemini for analysis.
    image_url: The relative path (e.g., /static/uploads/abc.jpg)
    """
    if not GEMINI_API_KEY:
        return "System Error: AI Service is not configured properly."

    try:
        # 1. Prepare inputs list
        content_parts = [SYSTEM_INSTRUCTION, f"User Input: {user_text}"]

        # 2. If Image exists, load it and add to inputs
        if image_url:
            # Clean path: remove leading slash if present to find file on disk
            # E.g., "/static/uploads/x.jpg" -> "static/uploads/x.jpg"
            clean_path = image_url.lstrip("/")
            
            if os.path.exists(clean_path):
                img = PIL.Image.open(clean_path)
                content_parts.append(img) # Add image to prompt
                content_parts.append("Analyze the medical relevance of this image in context of the user's message.")
            else:
                print(f"❌ Image file not found at: {clean_path}")
                # We continue with just text if image fails to load

        # 3. Generate
        # Gemini accepts a list [Text, Image, Text...]
        response = await model.generate_content_async(content_parts)
        
        return response.text
    except Exception as e:
        logger.error(f"Gemini API Error: {e}")
        # DEBUG MODE: Return the actual error to the user to see what's wrong
        return f"System Error: {str(e)}"
        # return "I'm having trouble analyzing that right now. Please try again."