# tests/runners/test_acp_protocol.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_proc(responses: list[dict]):
    """Build a mock subprocess whose stdout yields the given JSON responses."""
    lines = [json.dumps(r).encode() + b"\n" for r in responses]
    idx = 0

    async def fake_readline():
        nonlocal idx
        if idx < len(lines):
            line = lines[idx]
            idx += 1
            return line
        await asyncio.sleep(9999)  # hang until cancelled

    mock_stdout = AsyncMock()
    mock_stdout.readline = fake_readline
    mock_stdin = AsyncMock()
    written = []
    mock_stdin.write = lambda data: written.append(json.loads(data.decode().strip()))
    mock_stdin.drain = AsyncMock()

    proc = MagicMock()
    proc.stdout = mock_stdout
    proc.stdin = mock_stdin
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)
    return proc, written


@pytest.mark.asyncio
async def test_initialize_sends_correct_request():
    from src.runners.acp_protocol import ACPConnection

    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}}
    ])
    conn = ACPConnection(proc)
    conn.start()
    result = await conn.initialize()
    await conn.close()

    assert result["protocolVersion"] == 1
    assert written[0]["method"] == "initialize"
    assert written[0]["params"]["protocolVersion"] == 1


@pytest.mark.asyncio
async def test_new_session_returns_session_id():
    from src.runners.acp_protocol import ACPConnection

    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "sess-abc123"}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()
    session_id = await conn.new_session(cwd="/tmp")
    await conn.close()

    assert session_id == "sess-abc123"
    assert written[1]["method"] == "session/new"
    assert written[1]["params"]["cwd"] == "/tmp"


@pytest.mark.asyncio
async def test_prompt_yields_text_chunks():
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-xyz"
    proc, written = _make_mock_proc([
        # initialize response
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        # session/update notifications (push, no id)
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hello "}}
        }},
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "world!"}}
        }},
        # prompt response (end of turn)
        {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()

    chunks = []
    async for chunk in conn.prompt(session_id=session_id, text="hi"):
        chunks.append(chunk)
    await conn.close()

    assert "".join(chunks) == "Hello world!"


@pytest.mark.asyncio
async def test_permission_request_is_auto_approved():
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-perm"
    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        # Agent requests permission (reverse direction: agent sends request with id)
        {"jsonrpc": "2.0", "id": 99, "method": "session/request_permission", "params": {
            "sessionId": session_id,
            "toolCall": {"title": "bash: ls"},
            "options": [
                {"optionId": "opt-allow", "kind": "allow", "name": "Allow"},
                {"optionId": "opt-deny",  "kind": "deny",  "name": "Deny"},
            ]
        }},
        # Then session/update with text
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "done"}}
        }},
        # Prompt response
        {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()

    chunks = []
    async for chunk in conn.prompt(session_id=session_id, text="run ls"):
        chunks.append(chunk)
    await conn.close()

    # Check that we sent an auto-approve response for the permission request
    perm_response = next(
        (m for m in written if m.get("id") == 99 and "result" in m), None
    )
    assert perm_response is not None
    assert perm_response["result"]["outcome"]["optionId"] == "opt-allow"
    assert "done" in "".join(chunks)


@pytest.mark.asyncio
async def test_prompt_without_role_prefix_sends_single_block():
    """No role_prefix → single content block, no cache_control."""
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-no-cache"
    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()

    async for _ in conn.prompt(session_id=session_id, text="hello"):
        pass
    await conn.close()

    prompt_req = next(m for m in written if m.get("method") == "session/prompt")
    blocks = prompt_req["params"]["prompt"]
    assert len(blocks) == 1
    assert blocks[0]["text"] == "hello"
    assert "cache_control" not in blocks[0]


@pytest.mark.asyncio
async def test_prompt_with_role_prefix_sends_cached_block():
    """role_prefix → first block has cache_control:ephemeral, second has user text."""
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-cache"
    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()

    async for _ in conn.prompt(session_id=session_id, text="do the task", role_prefix="[Identity]\nYou are a dev.\n"):
        pass
    await conn.close()

    prompt_req = next(m for m in written if m.get("method") == "session/prompt")
    blocks = prompt_req["params"]["prompt"]
    assert len(blocks) == 2
    assert blocks[0]["text"] == "[Identity]\nYou are a dev.\n"
    assert blocks[0].get("cache_control") == {"type": "ephemeral"}
    assert blocks[1]["text"] == "do the task"
    assert "cache_control" not in blocks[1]


@pytest.mark.asyncio
async def test_subprocess_death_rejects_pending_futures():
    from src.runners.acp_protocol import ACPConnection

    call_count = 0

    async def fake_readline_eof():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: return the initialize response
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}}).encode() + b"\n"
        # Then immediately return EOF (subprocess died)
        return b""

    mock_stdout = AsyncMock()
    mock_stdout.readline = fake_readline_eof
    mock_stdin = AsyncMock()
    written = []
    mock_stdin.write = lambda data: written.append(json.loads(data.decode().strip()))
    mock_stdin.drain = AsyncMock()

    proc = MagicMock()
    proc.stdout = mock_stdout
    proc.stdin = mock_stdin
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)

    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()

    # Now send a prompt — subprocess is dead, should raise instead of hanging
    with pytest.raises(Exception, match="terminated"):
        async for _ in conn.prompt(session_id="sess-dead", text="hello"):
            pass


@pytest.mark.asyncio
async def test_prompt_with_thinking_budget_includes_thinking_param():
    """When thinking_budget > 0, session/prompt params must include thinking key."""
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-think"
    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": session_id}},
        # session/update with text chunk
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "deep answer"}},
        }},
        # prompt response
        {"jsonrpc": "2.0", "id": 3, "result": {}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()
    await conn.new_session(cwd="/tmp")
    chunks = []
    async for c in conn.prompt(session_id=session_id, text="prove P=NP", thinking_budget=8000):
        chunks.append(c)
    await conn.close()

    prompt_req = next(w for w in written if w.get("method") == "session/prompt")
    assert "thinking" in prompt_req["params"]
    assert prompt_req["params"]["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    assert "".join(chunks) == "deep answer"


@pytest.mark.asyncio
async def test_prompt_thinking_blocks_are_filtered_out():
    """session/update chunks with type=thinking must be silently discarded."""
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-filter"
    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": session_id}},
        # thinking block — must be filtered
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "thinking", "text": "internal thoughts"}},
        }},
        # text block — must be yielded
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "final answer"}},
        }},
        {"jsonrpc": "2.0", "id": 3, "result": {}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()
    await conn.new_session(cwd="/tmp")
    chunks = []
    async for c in conn.prompt(session_id=session_id, text="hello", thinking_budget=8000):
        chunks.append(c)
    await conn.close()

    assert "internal thoughts" not in "".join(chunks)
    assert "final answer" in "".join(chunks)
