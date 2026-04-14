import sqlite3
import json
from db.init_db import get_connection

def get_user_chats(username: str) -> list:
    """Returns a list of all chats for a given user, ordered by most recent."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, updated_at FROM chats WHERE username = ? ORDER BY updated_at DESC", 
        (username,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_chat_history(chat_id: int) -> list:
    """Returns the chat history dict list for a specific chat ID."""
    conn = get_connection()
    row = conn.execute("SELECT history_json FROM chats WHERE id = ?", (chat_id,)).fetchone()
    conn.close()
    
    if row and row["history_json"]:
        return json.loads(row["history_json"])
    return []

def create_chat(username: str, title: str, history: list) -> int:
    """Creates a new chat and returns its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chats (username, title, history_json) VALUES (?, ?, ?)",
        (username, title, json.dumps(history))
    )
    chat_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return chat_id

def update_chat(chat_id: int, history: list, title: str = None):
    """Updates an existing chat's history and optionally its title."""
    conn = get_connection()
    if title:
        conn.execute(
            "UPDATE chats SET history_json = ?, title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(history), title, chat_id)
        )
    else:
        conn.execute(
            "UPDATE chats SET history_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(history), chat_id)
        )
    conn.commit()
    conn.close()

def delete_chat(chat_id: int):
    """Deletes a chat."""
    conn = get_connection()
    conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()
