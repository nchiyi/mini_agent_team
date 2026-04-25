# src/runners/acp_protocol.py
"""
ACP (Agent Client Protocol) JSON-RPC 2.0 over ndjson stdin/stdout.

Protocol spec: https://agentclientprotocol.com
Method names from @agentclientprotocol/sdk schema/index.js v0.20.0
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator, Any

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = 1


class ACPConnection:
    """
    Bidirectional JSON-RPC 2.0 connection to an ACP agent subprocess.

    The agent (claude-agent-acp / codex-acp / gemini --acp) writes JSON lines
    to stdout; we read them and dispatch:
      - Responses (has "id" + "result"/"error")  → resolve pending Future
      - session/update notifications              → push to per-session Queue
      - session/request_permission requests       → auto-approve immediately
      - fs/read_text_file, fs/write_text_file     → serve from local filesystem
    """

    def __init__(self, proc: asyncio.subprocess.Process, cwd: str = ".") -> None:
        self._proc = proc
        self._cwd = cwd
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._buffered_responses: dict[int, dict] = {}  # id → msg, for early arrivals
        self._session_queues: dict[str, asyncio.Queue] = {}
        self._buffered_updates: dict[str, list[dict]] = {}  # sessionId → [params], for early arrivals
        self._reader_task: asyncio.Task | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._proc.returncode is None:
            self._proc.kill()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("ACP subprocess did not exit after kill; abandoning")

    # ── Public API ─────────────────────────────────────────────────────────

    async def initialize(self) -> dict:
        return await self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True},
            },
        })

    async def new_session(self, cwd: str, mcp_servers: list | None = None) -> str:
        result = await self._request("session/new", {
            "cwd": cwd,
            "mcpServers": mcp_servers or [],
        })
        return result["sessionId"]

    async def prompt(self, session_id: str, text: str) -> AsyncIterator[str]:
        """Send a prompt and yield text chunks as they stream in."""
        queue: asyncio.Queue = asyncio.Queue()
        self._session_queues[session_id] = queue
        # Drain any session/updates that arrived before we registered the queue
        for early in self._buffered_updates.pop(session_id, []):
            await queue.put(early)
        try:
            prompt_task = asyncio.create_task(
                self._request("session/prompt", {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": text}],
                })
            )
            while not prompt_task.done():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.05)
                    text_chunk = self._extract_text(item)
                    if text_chunk:
                        yield text_chunk
                except asyncio.TimeoutError:
                    continue

            # Drain any remaining updates buffered before prompt_task finished
            while not queue.empty():
                item = queue.get_nowait()
                text_chunk = self._extract_text(item)
                if text_chunk:
                    yield text_chunk

            await prompt_task  # propagate errors
        finally:
            self._session_queues.pop(session_id, None)

    # ── Internal: send / receive ───────────────────────────────────────────

    async def _request(self, method: str, params: dict) -> Any:
        req_id = self._next_id
        self._next_id += 1
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        await self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        # Check if the response already arrived before we started awaiting
        if req_id in self._buffered_responses:
            msg = self._buffered_responses.pop(req_id)
            self._pending.pop(req_id, None)
            if "error" in msg:
                future.set_exception(Exception(str(msg["error"])))
            else:
                future.set_result(msg["result"])
        # Check if the reader task is already dead (subprocess exited before registering our future)
        if not future.done() and self._reader_task is not None and self._reader_task.done():
            self._pending.pop(req_id, None)
            future.set_exception(Exception("ACP subprocess terminated unexpectedly"))
        return await future

    async def _respond(self, req_id: int, result: dict) -> None:
        await self._write({"jsonrpc": "2.0", "id": req_id, "result": result})

    def is_alive(self) -> bool:
        return self._reader_task is not None and not self._reader_task.done()

    async def _write(self, msg: dict) -> None:
        line = json.dumps(msg) + "\n"
        try:
            self._proc.stdin.write(line.encode())
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            raise Exception("ACP subprocess terminated unexpectedly") from e

    async def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        try:
            while True:
                try:
                    line = await self._proc.stdout.readline()
                    if not line:
                        break
                    raw = line.decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    msg = json.loads(raw)
                    await self._dispatch(msg)
                except asyncio.CancelledError:
                    break
                except json.JSONDecodeError:
                    logger.warning("ACP: non-JSON line ignored: %r", raw)
                    continue
                except Exception as e:
                    logger.error("ACP read loop fatal: %s", e, exc_info=True)
                    break
        finally:
            err = Exception("ACP subprocess terminated unexpectedly")
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(err)
            self._pending.clear()

    async def _dispatch(self, msg: dict) -> None:
        msg_id = msg.get("id")
        method = msg.get("method")

        # ── Response to one of our requests ──────────────────────────────
        if "result" in msg or "error" in msg:
            if msg_id is not None:
                if msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if "error" in msg:
                        future.set_exception(Exception(str(msg["error"])))
                    else:
                        future.set_result(msg["result"])
                else:
                    # Future not registered yet — buffer for when _request picks it up
                    self._buffered_responses[msg_id] = msg
            return

        # ── Push notification: streaming text / tool status ───────────────
        if method == "session/update":
            params = msg.get("params", {})
            sid = params.get("sessionId", "")
            if sid in self._session_queues:
                await self._session_queues[sid].put(params)
            else:
                # Queue not registered yet — buffer for when prompt() picks it up
                self._buffered_updates.setdefault(sid, []).append(params)
            return

        # ── Permission request: auto-approve the first "allow" option ─────
        if method == "session/request_permission" and msg_id is not None:
            options = msg.get("params", {}).get("options", [])
            allow_opt = next(
                (o for o in options if o.get("kind") == "allow"),
                options[0] if options else None,
            )
            if allow_opt:
                await self._respond(msg_id, {
                    "outcome": {"outcome": "selected", "optionId": allow_opt["optionId"]}
                })
            return

        # ── File system requests from agent ───────────────────────────────
        if method == "fs/read_text_file" and msg_id is not None:
            path = msg.get("params", {}).get("path", "")
            content = self._read_local_file(path)
            await self._respond(msg_id, {"content": content})
            return

        if method == "fs/write_text_file" and msg_id is not None:
            params = msg.get("params", {})
            try:
                self._write_local_file(params.get("path", ""), params.get("content", ""))
                await self._respond(msg_id, {})
            except Exception as e:
                await self._write({
                    "jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32603, "message": str(e)},
                })
            return

        # ── Unknown agent request ─────────────────────────────────────────
        if msg_id is not None:
            await self._write({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(update_params: dict) -> str:
        update = update_params.get("update", {})
        session_update = update.get("sessionUpdate")

        # Agent text response chunks
        if session_update == "agent_message_chunk":
            content = update.get("content", {})
            if content.get("type") == "text":
                return content.get("text", "")

        # Tool call completed — yield the raw tool output so callers can see
        # it even when the agent doesn't echo it in a follow-up text chunk.
        if session_update == "tool_call_update" and update.get("status") == "completed":
            raw = update.get("rawOutput", "")
            if raw:
                text_out = raw if isinstance(raw, str) else "\n".join(str(x) for x in raw)
                return text_out + "\n"

        return ""

    def _read_local_file(self, path: str) -> str:
        try:
            p = Path(path) if Path(path).is_absolute() else Path(self._cwd) / path
            return p.read_text(encoding="utf-8", errors="replace")[:50_000]
        except Exception as e:
            return f"[error reading {path}: {e}]"

    def _write_local_file(self, path: str, content: str) -> None:
        p = Path(path) if Path(path).is_absolute() else Path(self._cwd) / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
