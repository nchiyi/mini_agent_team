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
        self.db_path = db_path
        self._init_db()
        self.semantic = SemanticMemory(db_path)

    def _init_db(self):
        """Create tables if they don't exist."""
        # Ensure the directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
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
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    estimated_cost REAL DEFAULT 0,
                    timestamp TEXT NOT NULL
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

    def log_usage(self, user_id: int, model: str, prompt_tokens: int, completion_tokens: int, cost: float = 0.0):
        """Record precise token usage for a conversation step."""
        total = prompt_tokens + completion_tokens
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO usage_logs (user_id, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, model, prompt_tokens, completion_tokens, total, cost, datetime.now().isoformat()),
            )
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

        # Phase 3: Also feed to semantic memory if it's substantial
        if role == "user" and len(content) > 10:
             self.semantic.add_fact(content, source="user_input")
        elif role == "assistant" and len(content) > 20:
             self.semantic.add_fact(content, source="bot_response")

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

    def clear_context(self, user_id: int):
        """Clear the conversation history and summary for a user."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM settings WHERE user_id = ? AND key = 'summary'", (user_id,))
            conn.commit()
            
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

    def get_personality(self, user_id: int) -> str:
        """Retrieve the custom personality soul for a user."""
        return self.get_setting(user_id, "personality", "")

    def set_personality(self, user_id: int, text: str):
        """Set the custom personality soul for a user."""
        self.set_setting(user_id, "personality", text)

    def is_onboarded(self, user_id: int) -> bool:
        """Check if user has completed the personality onboarding."""
        return self.get_setting(user_id, "onboarded", "false") == "true"

    def set_onboarded(self, user_id: int, status: bool = True):
        """Mark onboarding as complete."""
        self.set_setting(user_id, "onboarded", "true" if status else "false")

    def get_summary(self, user_id: int) -> str:
        """Get the distilled conversation summary."""
        return self.get_setting(user_id, "summary", "")

    def set_summary(self, user_id: int, text: str):
        """Store a new distilled summary."""
        self.set_setting(user_id, "summary", text)

    def get_message_count(self, user_id: int) -> int:
        """Count messages for a specific user to decide when to distill."""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        return count

    def prune_old_messages(self, user_id: int, keep_last_n: int = 5):
        """Delete old messages, keeping only the most recent ones (after distillation)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM messages WHERE id NOT IN (
                    SELECT id FROM messages WHERE user_id = ?
                    ORDER BY id DESC LIMIT ?
                ) AND user_id = ?
            """, (user_id, keep_last_n, user_id))
            conn.commit()

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


class SemanticMemory:
    """Vector-based memory for efficient context retrieval (Phase 3)."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.index_path = db_path.replace(".db", ".faiss")
        self.meta_path = db_path.replace(".db", ".meta.json")
        self.model = None
        self.index = None
        self.metadata = []  # List of dicts mapping to FAISS IDs
        
        self._initialized = False
        self._unsaved_count = 0  # Track unsaved additions for batch saving

    def _lazy_init(self):
        """Lazy load heavy models and index."""
        if self._initialized:
            return
            
        try:
            import numpy as np
            import faiss
            from sentence_transformers import SentenceTransformer
            
            logger.info("Initializing Semantic Memory (Loading models)...")
            # Using a very light and fast model
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            dim = 384  # Dimension of all-MiniLM-L6-v2
            
            if os.path.exists(self.index_path):
                self.index = faiss.read_index(self.index_path)
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            else:
                self.index = faiss.IndexFlatL2(dim)
                self.metadata = []
                
            self._initialized = True
            logger.info(f"Semantic Memory ready (Loaded {len(self.metadata)} facts)")
        except ImportError:
            logger.warning("FAISS or SentenceTransformers not found. Semantic memory disabled.")
        except Exception as e:
            logger.error(f"Failed to init semantic memory: {e}")

    def add_fact(self, content: str, source: str = "conversation"):
        """Embed and store a new fact."""
        self._lazy_init()
        if not self._initialized: return

        try:
            import numpy as np
            vector = self.model.encode([content])[0].astype('float32')
            self.index.add(np.array([vector]))
            
            self.metadata.append({
                "content": content,
                "source": source,
                "timestamp": datetime.now().isoformat()
            })
            
            # Batch save: only persist every 10 additions to reduce I/O
            self._unsaved_count += 1
            if self._unsaved_count >= 10:
                self.save()
                self._unsaved_count = 0
        except Exception as e:
            logger.error(f"Failed to add fact: {e}")

    def search(self, query: str, top_k: int = 5) -> str:
        """Search for top_k relevant facts."""
        self._lazy_init()
        if not self._initialized or not self.metadata: return ""

        try:
            import numpy as np
            query_vector = self.model.encode([query])[0].astype('float32')
            distances, indices = self.index.search(np.array([query_vector]), top_k)
            
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1 and idx < len(self.metadata):
                    results.append(f"- {self.metadata[idx]['content']}")
            
            if not results: return ""
            return "\n".join(results)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return ""

    def save(self):
        """Persist index and metadata."""
        if not self._initialized: return
        import faiss
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
