"""
Memory — SQLite-based conversation history and context storage.
"""
import sqlite3
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "memory.db")


class Memory:
    """SQLite-backed memory for conversation history and settings."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    name TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    added_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def add_message(self, user_id: int, role: str, content: str):
        """Store a message in history."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, role, content, datetime.now().isoformat()),
            )
            # Keep only last 100 messages per user
            conn.execute("""
                DELETE FROM messages WHERE id NOT IN (
                    SELECT id FROM messages WHERE user_id = ?
                    ORDER BY id DESC LIMIT 100
                ) AND user_id = ?
            """, (user_id, user_id))
            conn.commit()

    def get_context(self, user_id: int, limit: int = 10) -> str:
        """Get recent conversation context for a user."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()

        if not rows:
            return ""

        lines = []
        for role, content in reversed(rows):
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {content}")
        return "\n".join(lines)

    # Settings
    def set_setting(self, user_id: int, key: str, value: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (user_id, key, value) VALUES (?, ?, ?)",
                (user_id, key, value),
            )
            conn.commit()

    def get_setting(self, user_id: int, key: str, default: str = "") -> str:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE user_id = ? AND key = ?",
                (user_id, key),
            ).fetchone()
        return row[0] if row else default

    # Projects
    def add_project(self, name: str, path: str, description: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projects (name, path, description, added_at) VALUES (?, ?, ?, ?)",
                (name, path, description, datetime.now().isoformat()),
            )
            conn.commit()

    def remove_project(self, name: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM projects WHERE name = ?", (name,))
            conn.commit()

    def get_projects(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT name, path, description FROM projects ORDER BY name"
            ).fetchall()
        return [{"name": r[0], "path": r[1], "description": r[2]} for r in rows]

    def get_project_path(self, name: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT path FROM projects WHERE name = ?", (name,)
            ).fetchone()
        return row[0] if row else None
