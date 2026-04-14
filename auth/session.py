"""
auth/session.py
---------------
Handles login, session state, and in-memory credential decryption.

Key principle:
    Decrypted AWS credentials only ever live in st.session_state (RAM).
    They are NEVER written to disk after decryption.
    When the browser tab closes, they are gone.
"""

import bcrypt
from db.init_db import get_connection
from auth.register import _derive_fernet_key, _decrypt


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login_user(username: str, master_password: str) -> tuple[bool, str, dict]:
    """
    Authenticates a user and decrypts their AWS credentials into memory.

    Returns:
        (True, "ok", session_data_dict)   on success
        (False, "error message", {})       on failure

    session_data_dict contains:
        {
            "username": str,
            "aws_access_key": str,   ← decrypted, in memory only
            "aws_secret_key": str,   ← decrypted, in memory only
            "aws_region": str,
            "logged_in": True
        }
    """

    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    # -- 1. User not found
    if row is None:
        return False, "Username not found.", {}

    # -- 2. Verify master password against bcrypt hash
    password_match = bcrypt.checkpw(
        master_password.encode("utf-8"),
        row["password_hash"].encode("utf-8")
    )
    if not password_match:
        return False, "Incorrect password.", {}

    # -- 3. Re-derive Fernet key from password + stored salt
    salt = bytes.fromhex(row["kdf_salt"])
    fernet_key = _derive_fernet_key(master_password, salt)

    # -- 4. Decrypt AWS credentials (into memory only) if present
    aws_access_key = None
    aws_secret_key = None
    docker_pat = None
    azure_client_id = None
    azure_tenant_id = None
    azure_subscription_id = None
    azure_client_secret = None
    github_token = None

    row_dict = dict(row)

    try:
        if row_dict.get("aws_access_key_enc"):
            aws_access_key = _decrypt(row_dict["aws_access_key_enc"], fernet_key)
        if row_dict.get("aws_secret_key_enc"):
            aws_secret_key = _decrypt(row_dict["aws_secret_key_enc"], fernet_key)
        if row_dict.get("docker_pat_enc"):
            docker_pat = _decrypt(row_dict["docker_pat_enc"], fernet_key)
        if row_dict.get("azure_client_id_enc"):
            azure_client_id = _decrypt(row_dict["azure_client_id_enc"], fernet_key)
        if row_dict.get("azure_tenant_id_enc"):
            azure_tenant_id = _decrypt(row_dict["azure_tenant_id_enc"], fernet_key)
        if row_dict.get("azure_subscription_id_enc"):
            azure_subscription_id = _decrypt(row_dict["azure_subscription_id_enc"], fernet_key)
        if row_dict.get("azure_client_secret_enc"):
            azure_client_secret = _decrypt(row_dict["azure_client_secret_enc"], fernet_key)
        if row_dict.get("github_token_enc"):
            github_token = _decrypt(row_dict["github_token_enc"], fernet_key)
    except Exception as e:
        return False, f"Decryption failed. ({str(e)})", {}

    session_data = {
        "logged_in": True,
        "username": row_dict["username"],
        "aws_access_key": aws_access_key,
        "aws_secret_key": aws_secret_key,
        "aws_region": row_dict.get("aws_region", "ap-south-1"),
        "docker_username": row_dict.get("docker_username"),
        "docker_pat": docker_pat,
        "azure_client_id": azure_client_id,
        "azure_tenant_id": azure_tenant_id,
        "azure_subscription_id": azure_subscription_id,
        "azure_client_secret": azure_client_secret,
        "github_token": github_token,
    }

    return True, "Login successful.", session_data


def login_user_social(method: str, identifier: str, metadata: dict = None) -> tuple[bool, str, dict]:
    """
    Handles social login (Google or Phone).
    If the user doesn't exist, it creates a skeleton account.
    """
    conn = get_connection()
    if method == "google":
        row = conn.execute("SELECT * FROM users WHERE google_id = ?", (identifier,)).fetchone()
    elif method == "phone":
        row = conn.execute("SELECT * FROM users WHERE phone_number = ?", (identifier,)).fetchone()
    else:
        conn.close()
        return False, "Invalid auth method.", {}

    if row is None:
        # Auto-register new social user
        username = metadata.get("name", f"user_{identifier[:6]}")
        # Ensure unique username
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            username = f"{username}_{random.randint(100,999)}"
        
        # We still need a salt for future credential encryption
        import os
        salt_hex = os.urandom(16).hex()
        
        try:
            if method == "google":
                conn.execute("INSERT INTO users (username, google_id, email, auth_method, password_hash, kdf_salt) VALUES (?, ?, ?, ?, 'SOCIAL_LOGIN', ?)", 
                             (username, identifier, metadata.get("email"), "google", salt_hex))
            else:
                conn.execute("INSERT INTO users (username, phone_number, auth_method, password_hash, kdf_salt) VALUES (?, ?, ?, 'SOCIAL_LOGIN', ?)", 
                             (username, identifier, "phone", salt_hex))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        except Exception as e:
            conn.close()
            return False, f"Social signup failed: {str(e)}", {}

    conn.close()
    row_dict = dict(row)

    # Note: Social users have no master password yet, so credentials cannot be decrypted here.
    # They stay None until the user provides a master password in settings.
    session_data = {
        "logged_in": True,
        "username": row_dict["username"],
        "auth_method": row_dict["auth_method"],
        "aws_access_key": None,
        "aws_secret_key": None,
        "aws_region": row_dict.get("aws_region", "ap-south-1")
    }
    return True, "Social login successful.", session_data


import random  # Required for social username generation


# ---------------------------------------------------------------------------
# Session state helpers (for Streamlit)
# ---------------------------------------------------------------------------

def init_session_state(st):
    """
    Initializes all session state keys on first load.
    Call this at the very top of app.py.
    """
    defaults = {
        "logged_in": False,
        "username": None,
        "aws_access_key": None,
        "aws_secret_key": None,
        "aws_region": None,
        "docker_username": None,
        "docker_pat": None,
        "azure_client_id": None,
        "azure_tenant_id": None,
        "azure_subscription_id": None,
        "azure_client_secret": None,
        "github_token": None,
        "chat_history": [],
        "current_chat_id": None,
        "sidebar_open": True,
        "current_page": "login",   # "login" | "signup" | "agent"
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def set_session(st, session_data: dict):
    """Writes decrypted session data into Streamlit session state."""
    for key, value in session_data.items():
        st.session_state[key] = value


def clear_session(st):
    """Logs the user out by wiping all session state keys."""
    keys_to_clear = [
        "logged_in", "username",
        "aws_access_key", "aws_secret_key", "aws_region",
        "docker_username", "docker_pat",
        "azure_client_id", "azure_tenant_id", "azure_subscription_id", "azure_client_secret",
        "github_token", "chat_history", "current_chat_id"
    ]
    for key in keys_to_clear:
        st.session_state[key] = None
    st.session_state["logged_in"] = False
    st.session_state["current_page"] = "login"


def is_logged_in(st) -> bool:
    """Returns True if there is an active authenticated session."""
    return st.session_state.get("logged_in", False)


def get_aws_credentials(st) -> dict:
    """
    Returns the current session's AWS credentials.
    Only call this after confirming is_logged_in().
    """
    return {
        "aws_access_key_id":     st.session_state.get("aws_access_key"),
        "aws_secret_access_key": st.session_state.get("aws_secret_key"),
        "region_name":           st.session_state.get("aws_region"),
    }
