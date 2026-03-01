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
model = genai.GenerativeModel('gemini-1.5-flash-latest')

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

async def get_medical_response(user_text: str, history: list = None, image_url: str = None, user_context: dict = None) -> str:
    """
    Intelligently switches between Simple, Complex, and Visual responses.
    Supports Session-Based Memory via 'history'.
    """
    if not GEMINI_API_KEY:
        return "System Error: AI Service is not configured properly."

    try:
        # 1. Build Context
        context_str = ""
        if user_context:
            age = user_context.get('age', 'Unknown')
            conditions = user_context.get('conditions', 'None')
            context_str = f"""
            **USER PROFILE:**
            - Age: {age}
            - Chronic Conditions: {conditions}
            """

        # 2. Setup the "Chat" Session
        # Initialize with history from frontend (or empty)
        # Verify history format safeguards here if needed, but assuming frontend sends correct structure
        chat_session = model.start_chat(history=history or [])

        # 3. Prepare the New Message
        # We stick the Context + Router Instructions to the FRONT of the new message
        # so the AI sees it immediately for this turn.
        full_prompt = [SYSTEM_INSTRUCTION, f"{context_str}\n\nUser Query: {user_text}"]

        # 4. Handle Image (If present)
        if image_url:
            clean_path = image_url.lstrip("/")
            if os.path.exists(clean_path):
                img = PIL.Image.open(clean_path)
                full_prompt.append(img)
                full_prompt.append("Analyze the medical relevance of this image in context of the user's message.")
            else:
                logger.warning(f"Image not found at: {clean_path}")

        # 5. Send Message to the Chat Session
        response = await chat_session.send_message_async(full_prompt)
        raw_text = response.text

        # 6. POST-PROCESSING (The Magic Trick)
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


# --- LAB TECHNICIAN PROMPT FOR URINALYSIS STRIP ANALYSIS ---
LAB_TECHNICIAN_PROMPT = """
You are a certified laboratory technician with expertise in urinalysis test strip interpretation.
Your task is to analyze the provided image of a urinalysis test strip with EXTREME precision.

**STEP 1: QUALITY CONTROL**
First, assess the image quality:
- Is the image blurry or out of focus?
- Is the lighting adequate (not too dark, not overexposed)?
- Is the test strip clearly visible and properly oriented?

If the image fails quality control, respond ONLY with:
{"status": "REJECTED", "reason": "[specific issue]", "lighting_score": "Poor"}

**STEP 2: CALIBRATION**
Look for a white background or reference area in the image.
Mentally calibrate for any color cast or lighting conditions.
Note the overall lighting quality as "Good", "Acceptable", or "Poor".

**STEP 3: VALUE EXTRACTION**
For each test pad on the strip, compare the color to the standard reference chart.
Extract values for ALL of the following parameters:
- Leukocytes (LEU)
- Nitrites (NIT)
- Urobilinogen (UBG)
- Protein (PRO)
- pH
- Blood (BLD)
- Specific Gravity (SG)
- Ketones (KET)
- Bilirubin (BIL)
- Glucose (GLU)

**STEP 4: RESPONSE FORMAT**
Return ONLY valid JSON in this exact format (no markdown, no explanation):
{
    "status": "SUCCESS",
    "lighting_score": "Good|Acceptable|Poor",
    "readings": {
        "leukocytes": {"value": "Negative|Trace|+|++|+++", "color": "observed color"},
        "nitrites": {"value": "Negative|Positive", "color": "observed color"},
        "urobilinogen": {"value": "Normal|+|++|+++", "color": "observed color"},
        "protein": {"value": "Negative|Trace|+|++|+++", "color": "observed color"},
        "ph": {"value": "5.0-9.0", "color": "observed color"},
        "blood": {"value": "Negative|Trace|+|++|+++", "color": "observed color"},
        "specific_gravity": {"value": "1.000-1.030", "color": "observed color"},
        "ketones": {"value": "Negative|Trace|+|++|+++", "color": "observed color"},
        "bilirubin": {"value": "Negative|+|++|+++", "color": "observed color"},
        "glucose": {"value": "Negative|Trace|+|++|+++", "color": "observed color"}
    },
    "notes": "Any additional observations about the sample"
}
"""


async def analyze_lab_strip(image_bytes: bytes) -> dict:
    """
    Analyze a urinalysis test strip image using Gemini Vision.
    
    Args:
        image_bytes: Raw bytes of the uploaded image
        
    Returns:
        dict: Analysis results with status, readings, and quality score
    """
    import io
    import json
    
    if not GEMINI_API_KEY:
        return {"status": "ERROR", "reason": "AI Service is not configured properly."}
    
    try:
        # 1. Load Image from Bytes
        img = PIL.Image.open(io.BytesIO(image_bytes))
        
        # 2. Initialize Vision Model
        vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        # 3. Send to Gemini with Lab Technician Prompt
        response = await vision_model.generate_content_async([
            LAB_TECHNICIAN_PROMPT,
            img,
            "Analyze this urinalysis test strip image and provide the results in the specified JSON format."
        ])
        
        raw_text = response.text.strip()
        
        # 4. Clean Response (remove markdown code blocks if present)
        if raw_text.startswith("```"):
            # Remove ```json and trailing ```
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()
        
        # 5. Parse JSON Response
        result = json.loads(raw_text)
        
        logger.info(f"Lab Strip Analysis: Status={result.get('status')}, Lighting={result.get('lighting_score')}")
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Lab Strip JSON Parse Error: {e}")
        logger.error(f"Raw response: {raw_text[:500] if 'raw_text' in dir() else 'N/A'}")
        return {"status": "ERROR", "reason": "Failed to parse AI response"}
        
    except Exception as e:
        logger.error(f"Lab Strip Analysis Error: {e}")
        return {"status": "ERROR", "reason": str(e)}