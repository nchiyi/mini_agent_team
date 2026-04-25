#!/usr/bin/env python3
"""
驗證 claude-agent-acp 是否支援 cache_control content block。

做法：
  1. 啟動 claude-agent-acp，建立 session
  2. 送兩次帶有相同 role_prefix 的 prompt
  3. 攔截 session/prompt 的 response，看有沒有 usage.cache_read_input_tokens > 0

用法：
  python3 scripts/check_prompt_cache.py
  python3 scripts/check_prompt_cache.py --binary /path/to/claude-agent-acp
"""

import asyncio
import json
import logging
import sys
import argparse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROLE_PREFIX = (
    "[Identity]\n"
    "You are a helpful assistant specialized in software engineering.\n\n"
    "[Rules]\n"
    "- Be concise\n"
    "- Fact-driven\n\n"
    "[Task Brief]\n"
)

_PROTOCOL_VERSION = 1


class CacheCheckConnection:
    def __init__(self, proc):
        self._proc = proc
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._session_queues: dict[str, asyncio.Queue] = {}
        self._reader_task = None
        self._usage_log: list[dict] = []

    def start(self):
        self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self):
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._proc.returncode is None:
            self._proc.kill()
            await asyncio.wait_for(self._proc.wait(), timeout=5.0)

    async def initialize(self):
        return await self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True}},
        })

    async def new_session(self, cwd="."):
        result = await self._request("session/new", {"cwd": cwd, "mcpServers": []})
        return result["sessionId"]

    async def prompt(self, session_id: str, text: str, role_prefix: str = "") -> tuple[str, dict]:
        if role_prefix:
            content = [
                {"type": "text", "text": role_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": text},
            ]
        else:
            content = [{"type": "text", "text": text}]

        queue = asyncio.Queue()
        self._session_queues[session_id] = queue
        chunks = []
        usage = {}

        try:
            task = asyncio.create_task(
                self._request_with_result("session/prompt", {
                    "sessionId": session_id,
                    "prompt": content,
                })
            )
            while not task.done():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.1)
                    update = item.get("update", {})
                    if update.get("sessionUpdate") == "agent_message_chunk":
                        c = update.get("content", {})
                        if c.get("type") == "text":
                            chunks.append(c.get("text", ""))
                except asyncio.TimeoutError:
                    continue
            while not queue.empty():
                item = queue.get_nowait()
                update = item.get("update", {})
                if update.get("sessionUpdate") == "agent_message_chunk":
                    c = update.get("content", {})
                    if c.get("type") == "text":
                        chunks.append(c.get("text", ""))

            result = await task
            # usage might be in result directly or nested
            usage = result.get("usage", result.get("inputTokens", {}))
            if not usage and "cache_read_input_tokens" in result:
                usage = result
        finally:
            self._session_queues.pop(session_id, None)

        return "".join(chunks), usage

    async def _request(self, method, params):
        result, _ = await self._request_with_result_inner(method, params)
        return result

    async def _request_with_result(self, method, params):
        result, raw = await self._request_with_result_inner(method, params)
        return raw  # return full raw result

    async def _request_with_result_inner(self, method, params):
        req_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        await self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        raw = await future
        return raw, raw

    async def _write(self, msg):
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def _read_loop(self):
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(Exception("subprocess terminated"))

    async def _dispatch(self, msg):
        msg_id = msg.get("id")
        method = msg.get("method")

        if "result" in msg or "error" in msg:
            if msg_id is not None and msg_id in self._pending:
                future = self._pending.pop(msg_id)
                if "error" in msg:
                    future.set_exception(Exception(str(msg["error"])))
                else:
                    future.set_result(msg["result"])
            return

        if method == "session/update":
            params = msg.get("params", {})
            sid = params.get("sessionId", "")
            if sid in self._session_queues:
                await self._session_queues[sid].put(params)
            return

        if method == "session/request_permission" and msg_id is not None:
            options = msg.get("params", {}).get("options", [])
            allow = next((o for o in options if o.get("kind") == "allow"), options[0] if options else None)
            if allow:
                await self._write({
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"outcome": {"outcome": "selected", "optionId": allow["optionId"]}}
                })
            return

        if msg_id is not None:
            await self._write({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


async def check(binary: str):
    logger.info("啟動 %s ...", binary)
    proc = await asyncio.create_subprocess_exec(
        binary,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    conn = CacheCheckConnection(proc)
    conn.start()

    try:
        await conn.initialize()
        session_id = await conn.new_session(cwd=".")
        logger.info("session 建立：%s", session_id)

        logger.info("=== 第一次請求（cache MISS，建立 cache）===")
        text1, usage1 = await conn.prompt(
            session_id, "請用一句話說明 Python 的 GIL 是什麼。", role_prefix=ROLE_PREFIX
        )
        logger.info("回應：%s", text1[:100])
        logger.info("usage 原始資料：%s", usage1)

        logger.info("=== 第二次請求（應 cache HIT）===")
        text2, usage2 = await conn.prompt(
            session_id, "請用一句話說明 asyncio 的用途。", role_prefix=ROLE_PREFIX
        )
        logger.info("回應：%s", text2[:100])
        logger.info("usage 原始資料：%s", usage2)

    finally:
        await conn.close()

    print("\n========== 結果 ==========")
    print(f"第一次 usage：{usage1}")
    print(f"第二次 usage：{usage2}")

    cache_read = (usage2 or {}).get("cache_read_input_tokens", 0)
    if cache_read and cache_read > 0:
        print(f"\n✅ cache_control 有效！第二次 cache_read_input_tokens = {cache_read}")
        print("   ACP binary 支援 cache_control，#54 修復完整生效。")
    else:
        print("\n❌ 未偵測到 cache_read_input_tokens。")
        print("   可能原因：")
        print("   1. ACP binary 不支援 cache_control（需改用 SDK 直接呼叫）")
        print("   2. usage 資料在不同欄位（請看上方 usage 原始資料）")
        print("   3. ACP response 沒有回傳 usage（需在 binary 層加 logging）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="claude-agent-acp")
    args = parser.parse_args()

    try:
        asyncio.run(check(args.binary))
    except FileNotFoundError:
        print(f"找不到 binary：{args.binary}")
        print("請確認 claude-agent-acp 在 PATH 中，或用 --binary 指定路徑。")
        sys.exit(1)


if __name__ == "__main__":
    main()
