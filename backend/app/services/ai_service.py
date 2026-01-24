import os
import google.generativeai as genai
from dotenv import load_dotenv
import PIL.Image
import logging

# Configure Logging
logger = logging.getLogger("uvicorn.error")

load_dotenv()
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

# Initialize Model (Preserving the WORKING model name)
model = genai.GenerativeModel('gemini-flash-latest')

# 1. THE BRAIN: This prompt forces the AI to classify the request first.
SYSTEM_INSTRUCTION = """
You are MedIQ. Your goal is to provide the RIGHT level of detail.

**STEP 1: CLASSIFY THE REQUEST**
Analyze the user's input and determine the complexity.
- **[MODE: SIMPLE]** -> For common, mild issues (Headache, small cut, cold, "I'm tired").
  * Output: Short, direct advice. No diagrams. No long explanations.
  
- **[MODE: COMPLEX]** -> For chronic issues, deep questions, or confusing symptoms (Green stool, chronic rash, "How does digestion work?").
  * Output: detailed explanation, "MedIQ Blueprint" structure, and educational tone.

- **[MODE: VISUAL]** -> If the user asks about anatomy, a cycle (itch-scratch), or a process that needs a picture.
  * Output: detailed explanation AND insert a 
[Image of X]
 tag where relevant.

- **[MODE: EMERGENCY]** -> Life-threatening signs (Chest pain, unconsciousness).
  * Output: EMERGENCY template only.

**STEP 2: GENERATE RESPONSE**
Start your response with the mode tag (e.g., [MODE: SIMPLE]), then provide the answer.
"""

async def get_medical_response(user_text: str, image_url: str = None, user_context: dict = None) -> str:
    """
    Intelligently switches between Simple, Complex, and Visual responses.
    """
    if not GEMINI_API_KEY:
        return "System Error: AI Service is not configured properly."

    try:
        # 1. Build Context
        context_str = ""
        if user_context:
            # Safely get age if dob exists, else 'Unknown'
            # Assuming user_context has fields passed from chat.py
            age = user_context.get('age', 'Unknown')
            conditions = user_context.get('conditions', 'None')
            context_str = f"""
            **USER PROFILE:**
            - Age: {age}
            - Chronic Conditions: {conditions}
            """

        # 2. Combine Prompt with the "Router" Instruction
        content_parts = [SYSTEM_INSTRUCTION, f"{context_str}\n\nUser Query: {user_text}"]

        # 3. Handle Image Input
        if image_url:
            clean_path = image_url.lstrip("/")
            if os.path.exists(clean_path):
                img = PIL.Image.open(clean_path)
                content_parts.append(img)
                content_parts.append("Analyze the medical relevance of this image in context of the user's message.")
            else:
                logger.warning(f"Image not found at: {clean_path}")

        # 4. Generate
        response = await model.generate_content_async(content_parts)
        raw_text = response.text

        # 5. POST-PROCESSING (The Magic Trick)
        # Strip the "Mode Tag" so the user doesn't see it
        clean_text = raw_text.replace("[MODE: SIMPLE]", "") \
                             .replace("[MODE: COMPLEX]", "") \
                             .replace("[MODE: VISUAL]", "") \
                             .replace("[MODE: EMERGENCY]", "") \
                             .strip()
        
        return clean_text

    except Exception as e:
        logger.error(f"Gemini API Error: {e}")
        return f"System Error: {str(e)}"