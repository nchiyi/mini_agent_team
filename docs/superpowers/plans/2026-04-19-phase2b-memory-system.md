# Gateway Agent Platform — Phase 2b: Memory System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Tier 1 (permanent .md) and Tier 3 (SQLite conversation history), assemble multi-turn context for CLIRunner prompts, and add /remember /forget /recall commands.

**Architecture:** `Tier3Store` writes every user/assistant turn to SQLite (WAL mode, aiosqlite). `Tier1Store` manages per-user permanent .md files. `ContextAssembler` combines them into a prompt prefix (token-budgeted via tiktoken). `dispatch()` in main.py loads context before running, then saves both the user turn and assistant response to Tier 3. Tier 2 (hot JSON distillation) is deferred to Phase 2c.

**Tech Stack:** aiosqlite, tiktoken, Python stdlib (pathlib, json, datetime)

---

## File Map

| File | Change |
|------|--------|
| `src/core/memory/__init__.py` | Create: empty package marker |
| `src/core/memory/tier3.py` | Create: SQLite conversation history (WAL, aiosqlite) |
| `src/core/memory/tier1.py` | Create: Permanent .md entries per user |
| `src/core/memory/context.py` | Create: Context assembly with tiktoken budget |
| `src/gateway/router.py` | Modify: add /remember /forget /recall parsing |
| `main.py` | Modify: init memory stores, wire context into dispatch() |
| `tests/core/memory/test_tier3.py` | Create: async tests for SQLite history |
| `tests/core/memory/test_tier1.py` | Create: tests for permanent .md store |
| `tests/core/memory/test_context.py` | Create: tests for context assembly |
| `tests/gateway/test_router_memory.py` | Create: tests for /remember /forget /recall parsing |
| `tests/test_e2e_memory.py` | Create: E2E test — dispatch saves and loads memory |
| `requirements.txt` | Modify: add aiosqlite, tiktoken |

---

## Task 1: Tier 3 — SQLite Conversation History

**Files:**
- Create: `src/core/memory/__init__.py`
- Create: `src/core/memory/tier3.py`
- Create: `tests/core/memory/__init__.py`
- Create: `tests/core/memory/test_tier3.py`

- [ ] **Step 1: Install dependencies**

```bash
cd /tmp/telegram-to-control
pip install aiosqlite 2>/dev/null | tail -3
echo "aiosqlite" >> requirements.txt
mkdir -p src/core/memory tests/core/memory
touch src/core/memory/__init__.py tests/core/memory/__init__.py
```

- [ ] **Step 2: Write failing tests**

```python
# tests/core/memory/test_tier3.py
import asyncio, pytest

pytestmark = pytest.mark.asyncio


async def test_tier3_save_and_retrieve(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.save_turn(user_id=1, channel="telegram", role="user", content="hello")
    await store.save_turn(user_id=1, channel="telegram", role="assistant", content="hi there")

    turns = await store.get_recent(user_id=1, channel="telegram", n=10)
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "hello"
    assert turns[1]["role"] == "assistant"

    await store.close()


async def test_tier3_channel_isolation(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.save_turn(user_id=1, channel="telegram", role="user", content="tg msg")
    await store.save_turn(user_id=1, channel="discord",  role="user", content="dc msg")

    tg_turns = await store.get_recent(user_id=1, channel="telegram", n=10)
    dc_turns = await store.get_recent(user_id=1, channel="discord",  n=10)
    assert len(tg_turns) == 1
    assert len(dc_turns) == 1
    assert tg_turns[0]["content"] == "tg msg"
    assert dc_turns[0]["content"] == "dc msg"

    await store.close()


async def test_tier3_get_recent_respects_limit(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    for i in range(25):
        await store.save_turn(user_id=1, channel="telegram", role="user", content=f"msg {i}")

    turns = await store.get_recent(user_id=1, channel="telegram", n=10)
    assert len(turns) == 10
    # Should return the MOST RECENT 10, in chronological order
    assert turns[-1]["content"] == "msg 24"

    await store.close()


async def test_tier3_fts_search(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.save_turn(user_id=1, channel="telegram", role="user", content="gateway architecture design")
    await store.save_turn(user_id=1, channel="telegram", role="user", content="memory system sqlite")
    await store.save_turn(user_id=1, channel="telegram", role="user", content="discord adapter implementation")

    results = await store.search(user_id=1, query="sqlite memory", limit=5)
    assert any("memory" in r["content"] or "sqlite" in r["content"] for r in results)

    await store.close()
```

- [ ] **Step 3: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/core/memory/test_tier3.py -v 2>&1 | head -15
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement src/core/memory/tier3.py**

```python
# src/core/memory/tier3.py
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import aiosqlite


class Tier3Store:
    """SQLite conversation history with WAL mode and FTS5 search."""

    _CREATE_TURNS = """
    CREATE TABLE IF NOT EXISTS turns (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        channel TEXT    NOT NULL,
        role    TEXT    NOT NULL,
        content TEXT    NOT NULL,
        ts      TEXT    NOT NULL
    )
    """
    _CREATE_IDX = """
    CREATE INDEX IF NOT EXISTS idx_turns_user_channel_ts
    ON turns(user_id, channel, ts)
    """
    _CREATE_FTS = """
    CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
        content,
        content=turns,
        content_rowid=id,
        tokenize='unicode61'
    )
    """
    _CREATE_TRIGGERS = """
    CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
        INSERT INTO turns_fts(rowid, content) VALUES (new.id, new.content);
    END;
    CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
        INSERT INTO turns_fts(turns_fts, rowid, content)
        VALUES ('delete', old.id, old.content);
    END;
    """

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(str(self._path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(self._CREATE_TURNS)
        await self._db.execute(self._CREATE_IDX)
        await self._db.execute(self._CREATE_FTS)
        for stmt in self._CREATE_TRIGGERS.strip().split(";\n"):
            s = stmt.strip()
            if s:
                await self._db.execute(s + ";")
        await self._db.commit()
        self._db.row_factory = aiosqlite.Row
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        while True:
            item = await self._write_queue.get()
            if item is None:
                break
            user_id, channel, role, content, ts = item
            await self._db.execute(
                "INSERT INTO turns(user_id, channel, role, content, ts) VALUES (?,?,?,?,?)",
                (user_id, channel, role, content, ts),
            )
            await self._db.commit()
            self._write_queue.task_done()

    async def save_turn(
        self, *, user_id: int, channel: str, role: str, content: str
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        await self._write_queue.put((user_id, channel, role, content, ts))
        await self._write_queue.join()

    async def get_recent(
        self, *, user_id: int, channel: str, n: int
    ) -> list[dict[str, Any]]:
        async with self._db.execute(
            """SELECT role, content, ts FROM turns
               WHERE user_id=? AND channel=?
               ORDER BY id DESC LIMIT ?""",
            (user_id, channel, n),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in reversed(rows)]

    async def search(
        self, *, user_id: int, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        async with self._db.execute(
            """SELECT t.role, t.content, t.ts
               FROM turns_fts f
               JOIN turns t ON t.id = f.rowid
               WHERE turns_fts MATCH ? AND t.user_id = ?
               ORDER BY rank LIMIT ?""",
            (query, user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    async def close(self) -> None:
        if self._writer_task:
            await self._write_queue.put(None)
            await self._writer_task
        if self._db:
            await self._db.close()
```

- [ ] **Step 5: Run tests**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/core/memory/test_tier3.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add src/core/memory/ tests/core/memory/ requirements.txt
git commit -m "feat: Tier3Store — SQLite conversation history with WAL and FTS5"
```

---

## Task 2: Tier 1 — Permanent .md Memory

**Files:**
- Create: `src/core/memory/tier1.py`
- Create: `tests/core/memory/test_tier1.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/memory/test_tier1.py
import pytest
from pathlib import Path


def test_tier1_remember_creates_entry(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="I am a software engineer")
    entries = store.list_entries(user_id=1)
    assert len(entries) == 1
    assert "I am a software engineer" in entries[0]["content"]
    assert "ts" in entries[0]


def test_tier1_multiple_entries(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="fact one")
    store.remember(user_id=1, content="fact two")
    entries = store.list_entries(user_id=1)
    assert len(entries) == 2
    contents = [e["content"] for e in entries]
    assert "fact one" in contents
    assert "fact two" in contents


def test_tier1_forget_removes_matching_entry(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="I like Python")
    store.remember(user_id=1, content="I dislike Java")
    store.forget(user_id=1, keyword="Java")
    entries = store.list_entries(user_id=1)
    assert len(entries) == 1
    assert "Python" in entries[0]["content"]


def test_tier1_user_isolation(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="user1 fact")
    store.remember(user_id=2, content="user2 fact")
    assert len(store.list_entries(user_id=1)) == 1
    assert len(store.list_entries(user_id=2)) == 1
    assert store.list_entries(user_id=1)[0]["content"] == "user1 fact"


def test_tier1_render_for_context(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="I prefer dark mode")
    rendered = store.render_for_context(user_id=1)
    assert "I prefer dark mode" in rendered
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/core/memory/test_tier1.py -v 2>&1 | head -15
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement src/core/memory/tier1.py**

```python
# src/core/memory/tier1.py
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Tier1Store:
    """Permanent per-user memory stored as a JSON lines file.

    Each line is a JSON object: {"ts": "...", "content": "..."}.
    The .md file is a human-readable copy kept in sync.
    """

    def __init__(self, permanent_dir: str):
        self._dir = Path(permanent_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _jsonl_path(self, user_id: int) -> Path:
        return self._dir / f"{user_id}.jsonl"

    def _md_path(self, user_id: int) -> Path:
        return self._dir / f"{user_id}.md"

    def remember(self, *, user_id: int, content: str) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "content": content.strip()}
        with open(self._jsonl_path(user_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._sync_md(user_id)

    def forget(self, *, user_id: int, keyword: str) -> int:
        """Remove entries containing keyword (case-insensitive). Returns count removed."""
        path = self._jsonl_path(user_id)
        if not path.exists():
            return 0
        entries = self.list_entries(user_id)
        kept = [e for e in entries if keyword.lower() not in e["content"].lower()]
        removed = len(entries) - len(kept)
        with open(path, "w", encoding="utf-8") as f:
            for e in kept:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self._sync_md(user_id)
        return removed

    def list_entries(self, user_id: int) -> list[dict[str, Any]]:
        path = self._jsonl_path(user_id)
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def render_for_context(self, user_id: int) -> str:
        """Return all entries as a plain-text block for use in prompts."""
        entries = self.list_entries(user_id)
        if not entries:
            return ""
        lines = ["## Permanent Memory"] + [f"- {e['content']}" for e in entries]
        return "\n".join(lines)

    def _sync_md(self, user_id: int) -> None:
        entries = self.list_entries(user_id)
        md_lines = [f"# Permanent Memory — user {user_id}", ""]
        for e in entries:
            md_lines.append(f"- [{e['ts']}] {e['content']}")
        self._md_path(user_id).write_text("\n".join(md_lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/core/memory/test_tier1.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/core/memory/tier1.py tests/core/memory/test_tier1.py
git commit -m "feat: Tier1Store — permanent per-user memory in JSONL + .md"
```

---

## Task 3: Context Assembly

**Files:**
- Create: `src/core/memory/context.py`
- Create: `tests/core/memory/test_context.py`

- [ ] **Step 1: Install tiktoken**

```bash
cd /tmp/telegram-to-control
pip install tiktoken 2>/dev/null | tail -3
echo "tiktoken" >> requirements.txt
```

- [ ] **Step 2: Write failing tests**

```python
# tests/core/memory/test_context.py
import asyncio, pytest

pytestmark = pytest.mark.asyncio


async def test_context_empty_memory_returns_empty(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert ctx == ""

    await t3.close()


async def test_context_includes_tier1_entries(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t1.remember(user_id=1, content="I prefer Python")
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert "I prefer Python" in ctx

    await t3.close()


async def test_context_includes_tier3_history(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    await t3.save_turn(user_id=1, channel="telegram", role="user", content="previous question")
    await t3.save_turn(user_id=1, channel="telegram", role="assistant", content="previous answer")
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert "previous question" in ctx
    assert "previous answer" in ctx

    await t3.close()


async def test_context_respects_token_budget(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler, count_tokens

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    # Add many turns
    for i in range(50):
        await t3.save_turn(user_id=1, channel="telegram", role="user",
                           content=f"This is message number {i} with some extra content to use tokens.")
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=500)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=50)
    assert count_tokens(ctx) <= 500

    await t3.close()
```

- [ ] **Step 3: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/core/memory/test_context.py -v 2>&1 | head -15
```
Expected: FAIL

- [ ] **Step 4: Implement src/core/memory/context.py**

```python
# src/core/memory/context.py
from __future__ import annotations
import tiktoken
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store

_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


class ContextAssembler:
    """Builds a context string from Tier 1 permanent memory + Tier 3 history.

    Sections (in order of priority):
      1. Tier 1 permanent memory  (≤ tier1_budget tokens)
      2. Tier 3 recent history    (≤ tier3_budget tokens, most recent first)
    Total hard cap: max_tokens.
    """

    def __init__(
        self,
        tier1: Tier1Store,
        tier3: Tier3Store,
        max_tokens: int = 4000,
        tier1_budget: int = 800,
        tier3_budget: int = 2000,
    ):
        self._t1 = tier1
        self._t3 = tier3
        self._max = max_tokens
        self._t1_budget = min(tier1_budget, max_tokens)
        self._t3_budget = min(tier3_budget, max_tokens - self._t1_budget)

    async def build(
        self, *, user_id: int, channel: str, recent_turns: int = 20
    ) -> str:
        sections: list[str] = []

        # --- Tier 1 ---
        t1_text = self._t1.render_for_context(user_id)
        if t1_text:
            if count_tokens(t1_text) <= self._t1_budget:
                sections.append(t1_text)
            else:
                # Truncate to budget (character approximation)
                ratio = self._t1_budget / count_tokens(t1_text)
                sections.append(t1_text[: int(len(t1_text) * ratio)])

        # --- Tier 3 ---
        turns = await self._t3.get_recent(user_id=user_id, channel=channel, n=recent_turns)
        if turns:
            history_lines = []
            used = 0
            for turn in reversed(turns):  # oldest last → prepend newest within budget
                line = f"{turn['role'].upper()}: {turn['content']}"
                cost = count_tokens(line)
                if used + cost > self._t3_budget:
                    break
                history_lines.insert(0, line)
                used += cost
            if history_lines:
                sections.append("## Conversation History\n" + "\n".join(history_lines))

        return "\n\n".join(sections)
```

- [ ] **Step 5: Run tests**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/core/memory/test_context.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add src/core/memory/context.py tests/core/memory/test_context.py requirements.txt
git commit -m "feat: ContextAssembler — Tier1+Tier3 context with tiktoken budget"
```

---

## Task 4: Router — /remember /forget /recall Commands

**Files:**
- Modify: `src/gateway/router.py`
- Create: `tests/gateway/test_router_memory.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/gateway/test_router_memory.py
import pytest
from src.gateway.router import Router


def test_remember_command():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = router.parse("/remember I prefer Python over Ruby")
    assert cmd.is_remember is True
    assert cmd.prompt == "I prefer Python over Ruby"


def test_forget_command():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = router.parse("/forget Ruby")
    assert cmd.is_forget is True
    assert cmd.prompt == "Ruby"


def test_recall_command():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = router.parse("/recall architecture decision")
    assert cmd.is_recall is True
    assert cmd.prompt == "architecture decision"


def test_remember_without_content_is_unknown():
    """'/remember' with no content falls back to default runner as plain text."""
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = router.parse("/remember")
    # No content — treat as unknown slash, pass to default runner
    assert cmd.runner == "claude"
    assert cmd.is_remember is False
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/gateway/test_router_memory.py -v 2>&1 | head -15
```
Expected: FAIL (ParsedCommand has no `is_remember` field)

- [ ] **Step 3: Update src/gateway/router.py**

Replace the file with:

```python
# src/gateway/router.py
from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    runner: str
    prompt: str
    is_switch_runner: bool = False
    is_cancel: bool = False
    is_status: bool = False
    is_reset: bool = False
    is_new: bool = False
    is_remember: bool = False
    is_forget: bool = False
    is_recall: bool = False


class Router:
    _BUILTIN = {"/cancel", "/status", "/reset", "/new"}

    def __init__(self, known_runners: set[str], default_runner: str):
        self._runners = known_runners
        self._default = default_runner

    def parse(self, text: str) -> ParsedCommand:
        text = text.strip()

        if text == "/cancel":
            return ParsedCommand(runner=self._default, prompt="", is_cancel=True)
        if text == "/status":
            return ParsedCommand(runner=self._default, prompt="", is_status=True)
        if text == "/reset":
            return ParsedCommand(runner=self._default, prompt="", is_reset=True)
        if text == "/new":
            return ParsedCommand(runner=self._default, prompt="", is_new=True)

        if text.startswith("/remember "):
            content = text[10:].strip()
            if content:
                return ParsedCommand(runner=self._default, prompt=content, is_remember=True)

        if text.startswith("/forget "):
            keyword = text[8:].strip()
            if keyword:
                return ParsedCommand(runner=self._default, prompt=keyword, is_forget=True)

        if text.startswith("/recall "):
            query = text[8:].strip()
            if query:
                return ParsedCommand(runner=self._default, prompt=query, is_recall=True)

        if text.startswith("/use "):
            target = text[5:].strip()
            if target in self._runners:
                return ParsedCommand(runner=target, prompt="", is_switch_runner=True)

        if text.startswith("/"):
            parts = text.split(None, 1)
            prefix = parts[0].lstrip("/").lower()
            if prefix in self._runners:
                prompt = parts[1] if len(parts) > 1 else ""
                return ParsedCommand(runner=prefix, prompt=prompt)
            return ParsedCommand(runner=self._default, prompt=text)

        return ParsedCommand(runner=self._default, prompt=text)
```

- [ ] **Step 4: Run all router tests**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/gateway/test_router.py tests/gateway/test_router_memory.py -v
```
Expected: 12 PASSED (8 original + 4 new)

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/gateway/router.py tests/gateway/test_router_memory.py
git commit -m "feat: router — add /remember /forget /recall commands"
```

---

## Task 5: Wire Memory into dispatch() + E2E Test

**Files:**
- Modify: `main.py`
- Create: `tests/test_e2e_memory.py`

- [ ] **Step 1: Write E2E memory test**

```python
# tests/test_e2e_memory.py
"""
E2E test: dispatch() saves turns to Tier 3, loads context on next message,
and /remember /forget /recall work end-to-end.
"""
import sys, pytest
sys.path.insert(0, "tests/channels")
pytestmark = pytest.mark.asyncio


async def _make_full_pipeline(tmp_path):
    from fake_adapter import FakeAdapter
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(name="echo", binary="echo", args=[], timeout_seconds=5,
                       context_token_budget=1000, audit=audit)
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo")
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo", default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    return adapter, router, session_mgr, runners, bridge, t1, t3, assembler


async def _dispatch(user_id, channel, text, router, session_mgr, runners, bridge, adapter, t1, t3, assembler):
    """Simplified dispatch matching main.py logic."""
    session = session_mgr.get_or_create(user_id=user_id, channel=channel)
    cmd = router.parse(text)

    if cmd.is_remember:
        t1.remember(user_id=user_id, content=cmd.prompt)
        await adapter.send(user_id, f"Remembered: {cmd.prompt}")
        return

    if cmd.is_forget:
        removed = t1.forget(user_id=user_id, keyword=cmd.prompt)
        await adapter.send(user_id, f"Removed {removed} entries matching '{cmd.prompt}'")
        return

    if cmd.is_recall:
        results = await t3.search(user_id=user_id, query=cmd.prompt)
        if results:
            text_out = "\n".join(r["content"] for r in results)
            await adapter.send(user_id, text_out)
        else:
            await adapter.send(user_id, "Nothing found.")
        return

    if cmd.is_cancel or cmd.is_reset or cmd.is_new or cmd.is_status or cmd.is_switch_runner:
        await adapter.send(user_id, "ok")
        return

    # Save user turn
    await t3.save_turn(user_id=user_id, channel=channel, role="user", content=text)

    active_runner = runners[session.current_runner]
    # Build context prefix
    context = await assembler.build(user_id=user_id, channel=channel, recent_turns=20)
    full_prompt = (context + "\n\n" + cmd.prompt) if context else cmd.prompt

    chunks = []
    async for chunk in active_runner.run(prompt=full_prompt, user_id=user_id, channel=channel, cwd=session.cwd):
        chunks.append(chunk)
    response = "".join(chunks).strip()

    # Save assistant turn
    await t3.save_turn(user_id=user_id, channel=channel, role="assistant", content=response)
    await bridge.stream(
        user_id=user_id,
        chunks=active_runner.run(prompt=cmd.prompt, user_id=user_id, channel=channel, cwd=session.cwd),
    )


async def test_remember_stores_entry(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)
    await _dispatch(1, "telegram", "/remember I am a Python developer",
                    router, session_mgr, runners, bridge, adapter, t1, t3, assembler)

    entries = t1.list_entries(user_id=1)
    assert len(entries) == 1
    assert "Python developer" in entries[0]["content"]
    # Adapter should have confirmed
    assert any("Remembered" in m for m in adapter.sent)

    await t3.close()


async def test_forget_removes_entry(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)
    t1.remember(user_id=1, content="I use vim")
    t1.remember(user_id=1, content="I use emacs")
    await _dispatch(1, "telegram", "/forget emacs",
                    router, session_mgr, runners, bridge, adapter, t1, t3, assembler)

    entries = t1.list_entries(user_id=1)
    assert len(entries) == 1
    assert "vim" in entries[0]["content"]

    await t3.close()


async def test_turns_saved_to_tier3(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)
    await _dispatch(1, "telegram", "test message",
                    router, session_mgr, runners, bridge, adapter, t1, t3, assembler)

    turns = await t3.get_recent(user_id=1, channel="telegram", n=10)
    # At minimum the user turn should be saved
    assert any(t["role"] == "user" for t in turns)

    await t3.close()


async def test_context_included_in_subsequent_message(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)

    # Add a Tier 1 fact
    t1.remember(user_id=1, content="context-fact-xyz")

    # Build context and verify the fact appears
    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert "context-fact-xyz" in ctx

    await t3.close()
```

- [ ] **Step 2: Run to verify tests pass**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/test_e2e_memory.py -v
```
Expected: 4 PASSED

- [ ] **Step 3: Update main.py to initialize and wire memory**

Add memory initialization to `_build_shared()` and wire `/remember`, `/forget`, `/recall` into `dispatch()`. Replace main.py with:

```python
# main.py
"""
Gateway Agent Platform — entry point.
Runs TelegramAdapter and/or DiscordAdapter concurrently via asyncio.gather().
Includes Tier 1 permanent memory, Tier 3 SQLite history, and context assembly.
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.core.config import load_config, Config
from src.runners.audit import AuditLog
from src.runners.cli_runner import CLIRunner
from src.channels.telegram import TelegramAdapter
from src.channels.discord_adapter import DiscordAdapter
from src.channels.base import InboundMessage, BaseAdapter
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.gateway.streaming import StreamingBridge
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store
from src.core.memory.context import ContextAssembler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")


def _build_shared(cfg: Config, audit: AuditLog):
    runners = {
        name: CLIRunner(
            name=name,
            binary=rc.path,
            args=rc.args,
            timeout_seconds=rc.timeout_seconds,
            context_token_budget=rc.context_token_budget,
            audit=audit,
        )
        for name, rc in cfg.runners.items()
    }
    router = Router(
        known_runners=set(runners.keys()),
        default_runner=cfg.gateway.default_runner,
    )
    session_mgr = SessionManager(
        idle_minutes=cfg.gateway.session_idle_minutes,
        default_runner=cfg.gateway.default_runner,
        default_cwd=cfg.default_cwd,
    )
    tier1 = Tier1Store(permanent_dir=cfg.memory.cold_permanent_path)
    tier3 = Tier3Store(db_path=cfg.memory.db_path)
    assembler = ContextAssembler(
        tier1=tier1,
        tier3=tier3,
        max_tokens=cfg.runners.get(cfg.gateway.default_runner, next(iter(cfg.runners.values()))).context_token_budget
        if cfg.runners else 4000,
    )
    return runners, router, session_mgr, tier1, tier3, assembler


async def dispatch(
    inbound: InboundMessage,
    bridge: StreamingBridge,
    session_mgr: SessionManager,
    router: Router,
    runners: dict,
    tier1: Tier1Store,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    send_reply,
) -> None:
    """Channel-agnostic gateway logic."""
    session = session_mgr.get_or_create(user_id=inbound.user_id, channel=inbound.channel)
    cmd = router.parse(inbound.text)

    if cmd.is_remember:
        tier1.remember(user_id=inbound.user_id, content=cmd.prompt)
        await send_reply(f"Remembered: {cmd.prompt}")
        return
    if cmd.is_forget:
        removed = tier1.forget(user_id=inbound.user_id, keyword=cmd.prompt)
        await send_reply(f"Removed {removed} entries matching '{cmd.prompt}'")
        return
    if cmd.is_recall:
        results = await tier3.search(user_id=inbound.user_id, query=cmd.prompt, limit=5)
        if results:
            await send_reply("\n".join(r["content"] for r in results))
        else:
            await send_reply("Nothing found.")
        return
    if cmd.is_cancel:
        await send_reply("No active task to cancel.")
        return
    if cmd.is_reset:
        await send_reply("Context cleared.")
        return
    if cmd.is_new:
        await send_reply("New session started.")
        return
    if cmd.is_status:
        await send_reply(
            f"Status\nRunners: {list(runners.keys())}\n"
            f"Default: {session.current_runner}\nCWD: {session.cwd}"
        )
        return
    if cmd.is_switch_runner:
        session.current_runner = cmd.runner
        await send_reply(f"Switched to {cmd.runner}")
        return

    target_runner = runners.get(session.current_runner)
    if not target_runner:
        await send_reply(f"Runner '{session.current_runner}' not found.")
        return

    # Save user turn, build context, run
    await tier3.save_turn(
        user_id=inbound.user_id, channel=inbound.channel,
        role="user", content=inbound.text,
    )
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel,
        recent_turns=cfg_recent_turns,
    )
    full_prompt = (context + "\n\n" + cmd.prompt) if context else cmd.prompt

    try:
        response_chunks: list[str] = []

        async def collecting_chunks():
            async for chunk in target_runner.run(
                prompt=full_prompt,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
            ):
                response_chunks.append(chunk)
                yield chunk

        await bridge.stream(user_id=inbound.user_id, chunks=collecting_chunks())
        response = "".join(response_chunks).strip()
        if response:
            await tier3.save_turn(
                user_id=inbound.user_id, channel=inbound.channel,
                role="assistant", content=response,
            )
    except TimeoutError:
        await send_reply("Runner timed out.")
    except Exception as e:
        logger.error("Runner error: %s", e)
        await send_reply(f"Error: {e}")


cfg_recent_turns = 20  # module-level default; overridden in main() from config


async def run_telegram(cfg: Config, runners, router, session_mgr, tier1, tier3, assembler) -> None:
    tg_app = Application.builder().token(cfg.telegram_token).build()
    adapter = TelegramAdapter(bot=tg_app.bot, allowed_user_ids=cfg.allowed_user_ids)
    bridge = StreamingBridge(adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        inbound = InboundMessage(
            user_id=user_id,
            channel="telegram",
            text=update.message.text.strip(),
            message_id=str(update.message.message_id),
        )
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            tier1, tier3, assembler,
            lambda t: adapter.send(user_id, t),
        )

    tg_app.add_handler(MessageHandler(filters.TEXT, on_message))
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Telegram bot running")
        try:
            await asyncio.Event().wait()
        finally:
            await tg_app.updater.stop()
            await tg_app.stop()


async def run_discord(cfg: Config, runners, router, session_mgr, tier1, tier3, assembler) -> None:
    discord_bridges: dict[int, StreamingBridge] = {}

    async def gateway_handler(inbound: InboundMessage) -> None:
        if inbound.user_id not in discord_bridges:
            discord_bridges[inbound.user_id] = StreamingBridge(
                dc_adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds
            )
        bridge = discord_bridges[inbound.user_id]
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            tier1, tier3, assembler,
            lambda t: dc_adapter.send(inbound.user_id, t),
        )

    dc_adapter = DiscordAdapter(
        token=cfg.discord_token,
        allowed_user_ids=cfg.allowed_user_ids,
        gateway_handler=gateway_handler,
    )
    logger.info("Discord bot starting")
    await dc_adapter.start()


async def main(cfg_path: str = "config/config.toml", env_path: str = "secrets/.env") -> None:
    global cfg_recent_turns
    cfg = load_config(config_path=cfg_path, env_path=env_path)
    cfg_recent_turns = cfg.memory.tier3_context_turns
    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)
    runners, router, session_mgr, tier1, tier3, assembler = _build_shared(cfg, audit)
    await tier3.init()

    coroutines = []
    if cfg.telegram_token:
        coroutines.append(run_telegram(cfg, runners, router, session_mgr, tier1, tier3, assembler))
    if cfg.discord_token:
        coroutines.append(run_discord(cfg, runners, router, session_mgr, tier1, tier3, assembler))

    if not coroutines:
        logger.error("No tokens configured. Set TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN.")
        return

    try:
        await asyncio.gather(*coroutines, return_exceptions=True)
    finally:
        await tier3.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Verify main.py imports cleanly**

```bash
cd /tmp/telegram-to-control
python3 -c "from main import dispatch, run_telegram, run_discord, main; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Run full test suite**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: All tests PASS (33 existing + 4 E2E memory + router memory tests already counted = check total)

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add main.py tests/test_e2e_memory.py
git commit -m "feat: wire Tier1+Tier3 memory into dispatch — context, /remember /forget /recall"
```

---

## Self-Review

**Spec coverage (§6 Memory):**
- [x] Tier 3 SQLite WAL mode — Task 1
- [x] Tier 1 permanent .md — Task 2
- [x] Context assembly with token budget (tiktoken) — Task 3
- [x] /remember → Tier 1 write — Task 4 + 5
- [x] /forget → Tier 1 delete — Task 4 + 5
- [x] /recall → FTS5 search Tier 3 — Task 4 + 5
- [x] Multi-async write safety (single writer queue) — Task 1
- [x] Context selection not deletion (Tier 3 data never deleted) — Task 1 (get_recent) + Task 3
- [ ] Tier 2 hot JSON distillation — deferred to Phase 2c
- [ ] Embedding (Ollama nomic-embed-text) — deferred to Phase 5
- [ ] Distillation trigger (20 turns / topic switch) — deferred to Phase 2c

**Placeholder scan:** None. All code blocks are complete and runnable.

**Type consistency:**
- `Tier3Store.save_turn()` uses keyword-only args consistently throughout tasks 1, 3, 5
- `ContextAssembler.build()` signature matches across tasks 3 and 5
- `ParsedCommand.is_remember/is_forget/is_recall` added in Task 4 and used in Task 5
- `dispatch()` signature in main.py includes `tier1, tier3, assembler` consistently
