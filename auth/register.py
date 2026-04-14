"""
auth/register.py
----------------
Handles user signup and AWS credential encryption.

Encryption approach:
    1. User sets a master password during signup.
    2. A random 16-byte salt is generated.
    3. PBKDF2-HMAC-SHA256 derives a 32-byte key from (master_password + salt).
    4. Fernet symmetric encryption encrypts AWS keys using that derived key.
    5. Only the encrypted ciphertext + salt are stored in SQLite.
    6. The derived key is NEVER stored anywhere.

This means: even if someone steals the database file,
they cannot decrypt credentials without the user's master password.
"""

import os
import base64
import bcrypt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

import boto3
import botocore

from db.init_db import get_connection, init_db


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _generate_salt() -> bytes:
    """Generates a cryptographically random 16-byte salt."""
    return os.urandom(16)


def _derive_fernet_key(master_password: str, salt: bytes) -> bytes:
    """
    Derives a 32-byte Fernet-compatible key from the master password + salt
    using PBKDF2-HMAC-SHA256 with 390,000 iterations (OWASP 2023 recommendation).
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390_000,
        backend=default_backend()
    )
    key_bytes = kdf.derive(master_password.encode("utf-8"))
    # Fernet requires URL-safe base64-encoded 32-byte key
    return base64.urlsafe_b64encode(key_bytes)


def _encrypt(plaintext: str, fernet_key: bytes) -> str:
    """Encrypts a plaintext string. Returns base64 ciphertext as a string."""
    f = Fernet(fernet_key)
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt(ciphertext: str, fernet_key: bytes) -> str:
    """Decrypts a ciphertext string. Returns the original plaintext."""
    f = Fernet(fernet_key)
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# AWS credential validation
# ---------------------------------------------------------------------------

def validate_aws_credentials(access_key: str, secret_key: str, region: str) -> tuple[bool, str]:
    """
    Makes a lightweight STS call to verify AWS credentials are valid.
    Returns (True, account_id) on success or (False, error_message) on failure.
    Cost: $0 — sts:GetCallerIdentity is always free.
    """
    try:
        client = boto3.client(
            "sts",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        identity = client.get_caller_identity()
        return True, identity["Account"]
    except botocore.exceptions.ClientError as e:
        return False, str(e)
    except botocore.exceptions.NoCredentialsError:
        return False, "No credentials provided."
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def username_exists(username: str) -> bool:
    """Checks if a username is already taken."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return row is not None


def register_user(
    username: str,
    master_password: str
) -> tuple[bool, str]:
    """
    Registers a new user by only asking for username and master password.
    Other credentials (AWS, Docker, Azure) can be added later in settings.
    """

    # -- 0. Ensure DB exists
    init_db()

    # -- 1. Check username availability
    if username_exists(username):
        return False, "Username already taken. Please choose another."

    # -- 2. Hash master password with bcrypt
    pw_hash = bcrypt.hashpw(
        master_password.encode("utf-8"),
        bcrypt.gensalt(rounds=12)
    ).decode("utf-8")

    # -- 3. Generate salt (for future credential encryptions)
    salt = _generate_salt()
    salt_hex = salt.hex()

    # -- 4. Write to database
    try:
        conn = get_connection()
        conn.execute("""
            INSERT INTO users
                (username, password_hash, kdf_salt)
            VALUES (?, ?, ?)
        """, (username, pw_hash, salt_hex))
        conn.commit()
        conn.close()
        return True, f"Account created successfully for {username}!"
    except Exception as e:
        return False, f"Database error: {str(e)}"


def update_credentials(
    username: str,
    master_password: str,
    updates: dict
) -> tuple[bool, str]:
    """
    Updates a user's cloud credentials.
    Requires the master password to derive the encryption key.
    
    `updates` is a dict that may contain:
    - aws_access_key
    - aws_secret_key
    - aws_region
    - docker_username
    - docker_pat
    - azure_client_id
    - azure_tenant_id
    - azure_subscription_id
    - azure_client_secret
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()

    if row is None:
        conn.close()
        return False, "User not found."

    # Verify master password
    password_match = bcrypt.checkpw(
        master_password.encode("utf-8"),
        row["password_hash"].encode("utf-8")
    )
    if not password_match:
        conn.close()
        return False, "Incorrect master password."

    salt = bytes.fromhex(row["kdf_salt"])
    fernet_key = _derive_fernet_key(master_password, salt)

    # Validate AWS credentials if presented
    if updates.get("aws_access_key") and updates.get("aws_secret_key"):
        aws_region = updates.get("aws_region", row["aws_region"] or "ap-south-1")
        valid, result = validate_aws_credentials(
            updates["aws_access_key"], updates["aws_secret_key"], aws_region
        )
        if not valid:
            conn.close()
            return False, f"AWS credentials validation failed: {result}"
        updates["aws_region"] = aws_region

    query_parts = []
    params = []

    # Map keys from plain updates dict to DB columns
    column_maps = {
        "aws_access_key": "aws_access_key_enc",
        "aws_secret_key": "aws_secret_key_enc",
        "docker_username": "docker_username",      # Plain text docker username is usually fine
        "docker_pat": "docker_pat_enc",
        "azure_client_id": "azure_client_id_enc",
        "azure_tenant_id": "azure_tenant_id_enc",
        "azure_subscription_id": "azure_subscription_id_enc",
        "azure_client_secret": "azure_client_secret_enc",
        "github_token": "github_token_enc"
    }

    for key, value in updates.items():
        if not value:
            continue
            
        if key == "aws_region":
            query_parts.append("aws_region = ?")
            params.append(value)
        elif key == "docker_username":
            query_parts.append("docker_username = ?")
            params.append(value)
        elif key in column_maps:
            enc_col = column_maps[key]
            # Encrypt the value
            enc_val = _encrypt(value, fernet_key)
            query_parts.append(f"{enc_col} = ?")
            params.append(enc_val)

    if not query_parts:
        conn.close()
        return False, "No valid credentials provided to update."

    params.append(username)
    update_query = f"UPDATE users SET {', '.join(query_parts)} WHERE username = ?"

    try:
        conn.execute(update_query, tuple(params))
        conn.commit()
        conn.close()
        return True, "Credentials updated successfully."
    except Exception as e:
        conn.close()
        return False, f"Database update error: {str(e)}"

