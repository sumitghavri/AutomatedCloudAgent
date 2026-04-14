"""
auth/social_auth.py
-------------------
Bridge for Google OAuth and Mobile OTP (SMS) authentication.
Includes helpers for building a stable Google OAuth flow and SMS OTP login.
"""

import os
import random
import json
import base64
import secrets
from db.init_db import get_connection

# Real Auth Libraries
from google_auth_oauthlib.flow import Flow
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _encode_state_payload(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _decode_state_payload(value: str) -> dict:
    padding = "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode((value + padding).encode("utf-8"))
    return json.loads(raw.decode("utf-8"))

class SocialAuth:
    @staticmethod
    def _build_google_flow(state: str | None = None, code_verifier: str | None = None) -> Flow:
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501")

        if not client_id or not client_secret:
            raise ValueError("Missing Google OAuth credentials in environment.")

        client_config = {
            "web": {
                "client_id": client_id,
                "project_id": "ai-cloud-agent",
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": client_secret,
                "redirect_uris": [redirect_uri]
            }
        }

        flow = Flow.from_client_config(
            client_config,
            scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri,
            state=state
        )
        if code_verifier:
            flow.code_verifier = code_verifier
        return flow

    @staticmethod
    def get_google_auth_url() -> tuple[str, str]:
        """
        Generates the Google OAuth2 authorization URL and returns
        (url, state_payload).
        Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.
        """
        flow = SocialAuth._build_google_flow()
        flow.code_verifier = secrets.token_urlsafe(64)
        state_payload = _encode_state_payload({
            "nonce": os.urandom(12).hex(),
            "code_verifier": flow.code_verifier,
        })
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            code_challenge_method="S256",
            state=state_payload,
        )
        return auth_url, state

    @staticmethod
    def parse_google_state(state: str) -> dict:
        return _decode_state_payload(state)

    @staticmethod
    def get_google_user(code: str, state: str | None = None, code_verifier: str | None = None) -> dict:
        """
        Exchanges the authorization code for user info.
        """
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        flow = SocialAuth._build_google_flow(state=state, code_verifier=code_verifier)
        flow.fetch_token(code=code)
        
        from google.oauth2 import id_token
        from google.auth.transport import requests
        
        credentials = flow.credentials
        info = id_token.verify_oauth2_token(credentials.id_token, requests.Request(), client_id)
        
        return {
            "sub": info["sub"],
            "email": info["email"],
            "name": info.get("name", "Social User"),
            "picture": info.get("picture")
        }

    @staticmethod
    def send_otp(phone: str) -> str:
        """
        Sends a 6-digit OTP using Twilio.
        """
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_phone = os.getenv("TWILIO_PHONE_NUMBER")
        
        if not all([account_sid, auth_token, from_phone]):
            print("[AUTH ERROR] Missing Twilio credentials in .env")
            return "ERROR"

        otp = str(random.randint(100000, 999999))
        client = TwilioClient(account_sid, auth_token)
        
        try:
            client.messages.create(
                body=f"Your AI Cloud Agent verification code is: {otp}",
                from_=from_phone,
                to=phone
            )
            return otp
        except Exception as e:
            print(f"[TWILIO ERROR] {str(e)}")
            return "ERROR"

def get_user_by_google_id(google_id: str):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
    conn.close()
    return user

def get_user_by_phone(phone: str):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE phone_number = ?", (phone,)).fetchone()
    conn.close()
    return user

def link_google_account(username: str, google_id: str, email: str):
    conn = get_connection()
    conn.execute("UPDATE users SET google_id = ?, email = ?, auth_method = 'google' WHERE username = ?", 
                 (google_id, email, username))
    conn.commit()
    conn.close()

def link_phone_account(username: str, phone: str):
    conn = get_connection()
    conn.execute("UPDATE users SET phone_number = ?, auth_method = 'phone' WHERE username = ?", 
                 (phone, username))
    conn.commit()
    conn.close()
