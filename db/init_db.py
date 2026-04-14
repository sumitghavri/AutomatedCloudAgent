"""
db/init_db.py
-------------
Initializes the SQLite database schema on first run.
Creates the `users` table if it doesn't already exist.

Run directly to reset/init:
    python db/init_db.py
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def get_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # allows dict-style access to rows
    return conn


def init_db():
    """Creates tables if they do not exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            password_hash   TEXT    NOT NULL,

            -- AWS credentials stored encrypted with Fernet
            aws_access_key_enc  TEXT,
            aws_secret_key_enc  TEXT,
            kdf_salt            TEXT,
            aws_region          TEXT    DEFAULT 'ap-south-1',

            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- Schema Migrations ---
    # Safely add new columns if they don't exist yet
    new_columns = [
        "docker_username TEXT",
        "docker_pat_enc TEXT",
        "azure_client_id_enc TEXT",
        "azure_tenant_id_enc TEXT",
        "azure_subscription_id_enc TEXT",
        "azure_client_secret_enc TEXT",
        "github_token_enc TEXT",
        "google_id TEXT",
        "phone_number TEXT",
        "email TEXT",
        "auth_method TEXT DEFAULT 'password'"
    ]
    
    for col_def in new_columns:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
        except sqlite3.OperationalError as e:
            # OperationalError occurs if the column already exists
            pass

    # --- Chats Table ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL,
            title           TEXT    DEFAULT 'New Deployment',
            history_json    TEXT    DEFAULT '[]',
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username)
        )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized & migrated at: {DB_PATH}")


if __name__ == "__main__":
    init_db()
