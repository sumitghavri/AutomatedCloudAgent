import os
import json
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

try:
    # Try the more stable dot-import for namespace packages
    import google.genai as genai
    from google.genai import types
except ImportError:
    try:
        # Fallback to standard
        from google import genai
        from google.genai import types
    except ImportError:
        print("❌ Fatal: Cannot import genai from google. Please check your python environment.")
        genai = None
        types = None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if genai and GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None
    if not GEMINI_API_KEY:
        print("⚠️ Warning: GEMINI_API_KEY not found in environment.")

def invoke_gemini(prompt: str, system_instruction: Optional[str] = None, use_json: bool = False) -> str:
    """
    Invokes Gemini 1.5 Flash for extraction/intent tasks.
    """
    if not client:
        return "{}"

    try:
        # Configure generation settings
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,  # Keep it deterministic for infra tasks
            # Native JSON Mode toggle
            response_mime_type="application/json" if use_json else "text/plain",
        )

        # Call the model
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=config
        )

        return response.text if response.text else "{}"

    except Exception as e:
        print(f"--- Gemini SDK Error --- \n{str(e)}")
        return "{}"