import re
import json
from agent.llm import invoke_gemini

VALID_INTENTS = [
    "EC2_DEPLOY", "S3_CREATE", "VPC_SETUP",
    "DOCKER_SINGLE", "DOCKER_COMPOSE", "DESTROY",
    "MONITORING", "AMBIGUOUS", "OUT_OF_SCOPE", "GENERAL_CHAT"
]

SYSTEM_PROMPT = """You are the Intent Classification engine AND an expert Cloud Instructor.
Classify the user's message into EXACTLY one of these intents:
- EC2_DEPLOY: User wants a VM/server
- S3_CREATE: User wants cloud storage or static website
- VPC_SETUP: User wants isolated networking
- DOCKER_SINGLE: User wants to run a single Docker image
- DOCKER_COMPOSE: User wants multi-container (app + database)
- DESTROY: User wants to delete resources
- MONITORING: User wants CloudWatch/metrics/logs
- GENERAL_CHAT: Casual chat, OR how-to questions about cloud topics (Docker PAT, AWS setup, VPC explained, etc.)
- AMBIGUOUS: Intent is unclear between two services
- OUT_OF_SCOPE: Kubernetes, Azure, GCP, unsupported requests

Rules:
1. For GENERAL_CHAT how-to questions: provide a DETAILED step-by-step tutorial in the message field.
2. For AMBIGUOUS: ask a short clarifying question in the message field.
3. For OUT_OF_SCOPE: politely explain what you support.
4. For deployment intents (EC2_DEPLOY etc.): leave message empty.

You MUST respond with ONLY valid JSON in this exact format (no extra text, no markdown):
{"intent": "INTENT_HERE", "message": "your message here"}

Context:
{chat_history}"""

def classify_intent(user_input: str, chat_history: str = "") -> dict:
    """
    LLM Call 1: Intent classification using plain text + JSON parsing.
    Returns a dict with 'intent' and 'message' keys.
    Works reliably with all free OpenRouter models.
    """
    prompt = SYSTEM_PROMPT.replace("{chat_history}", chat_history or "None") + \
             f"\n\nUser: {user_input}"
    
    try:
        content = invoke_gemini(prompt)
        
        # Extract JSON from the response (handle markdown code blocks too)
        json_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            intent = parsed.get("intent", "GENERAL_CHAT").strip().upper()
            if intent not in VALID_INTENTS:
                intent = "GENERAL_CHAT"
            return {
                "intent": intent,
                "message": parsed.get("message", "")
            }
        else:
            # If model returned plain text instead of JSON, treat as GENERAL_CHAT
            return {"intent": "GENERAL_CHAT", "message": content}
            
    except Exception as e:
        return {"intent": "GENERAL_CHAT", "message": f"I had trouble understanding that. Could you rephrase? (Debug: {str(e)})"}
