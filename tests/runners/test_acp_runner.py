# tests/runners/test_acp_runner.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_conn(chunks: list[str], session_id: str = "sess-1"):
    """Return a mock ACPConnection that yields the given text chunks."""
    conn = MagicMock()
    conn.initialize = AsyncMock(return_value={"protocolVersion": 1, "agentCapabilities": {}})
    conn.new_session = AsyncMock(return_value=session_id)
    conn.close = AsyncMock()

    async def fake_prompt(session_id, text):
        for chunk in chunks:
            yield chunk

    conn.prompt = fake_prompt
    return conn


@pytest.mark.asyncio
async def test_acp_runner_initializes_once():
    from src.runners.acp_runner import ACPRunner

    runner = ACPRunner(name="claude", command="claude-agent-acp", args=[],
                       timeout_seconds=30, context_token_budget=4000)

    mock_conn = _make_mock_conn(["Hello!"])

    with patch("src.runners.acp_runner.ACPConnection", return_value=mock_conn), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.returncode = None
        mock_spawn.return_value = mock_proc

        chunks1 = []
        async for c in runner.run("hello", user_id=1, channel="tg", cwd="/tmp"):
            chunks1.append(c)

        init_count = mock_conn.initialize.call_count
        spawn_count = mock_spawn.call_count

        # Second call to same runner should NOT re-initialize
        chunks2 = []
        async for c in runner.run("hello again", user_id=1, channel="tg", cwd="/tmp"):
            chunks2.append(c)

    assert mock_conn.initialize.call_count == init_count  # no second init
    assert mock_spawn.call_count == spawn_count           # no second spawn
    assert "Hello!" in "".join(chunks1)


@pytest.mark.asyncio
async def test_acp_runner_reuses_session_for_same_user():
    from src.runners.acp_runner import ACPRunner

    runner = ACPRunner(name="claude", command="claude-agent-acp", args=[],
                       timeout_seconds=30, context_token_budget=4000)

    mock_conn = _make_mock_conn(["response"], session_id="sess-reuse")

    with patch("src.runners.acp_runner.ACPConnection", return_value=mock_conn), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.returncode = None
        mock_spawn.return_value = mock_proc

        async for _ in runner.run("msg1", user_id=42, channel="tg", cwd="/tmp"):
            pass
        async for _ in runner.run("msg2", user_id=42, channel="tg", cwd="/tmp"):
            pass

    # new_session called once (reused after that)
    assert mock_conn.new_session.call_count == 1


@pytest.mark.asyncio
async def test_acp_runner_creates_new_session_for_new_user():
    from src.runners.acp_runner import ACPRunner

    runner = ACPRunner(name="claude", command="claude-agent-acp", args=[],
                       timeout_seconds=30, context_token_budget=4000)

    mock_conn = _make_mock_conn(["ok"])

    with patch("src.runners.acp_runner.ACPConnection", return_value=mock_conn), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.returncode = None
        mock_spawn.return_value = mock_proc

        async for _ in runner.run("msg", user_id=1, channel="tg", cwd="/tmp"):
            pass
        async for _ in runner.run("msg", user_id=2, channel="tg", cwd="/tmp"):
            pass

    # Two different users → two sessions
    assert mock_conn.new_session.call_count == 2


@pytest.mark.asyncio
async def test_acp_runner_timeout_raises():
    from src.runners.acp_runner import ACPRunner

    runner = ACPRunner(name="claude", command="claude-agent-acp", args=[],
                       timeout_seconds=1, context_token_budget=4000)

    async def slow_prompt(session_id, text):
        await asyncio.sleep(999)
        yield "never"

    mock_conn = _make_mock_conn([])
    mock_conn.prompt = slow_prompt

    with patch("src.runners.acp_runner.ACPConnection", return_value=mock_conn), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.returncode = None
        mock_spawn.return_value = mock_proc

        with pytest.raises(TimeoutError):
            async for _ in runner.run("slow", user_id=1, channel="tg", cwd="/tmp"):
                pass


async def _consume(gen):
    async for _ in gen:
        pass


@pytest.mark.asyncio
async def test_acp_runner_no_duplicate_sessions_concurrent():
    from src.runners.acp_runner import ACPRunner

    runner = ACPRunner(name="claude", command="claude-agent-acp", args=[],
                       timeout_seconds=30, context_token_budget=4000)

    new_session_count = 0
    original_new_session = None

    mock_conn = _make_mock_conn(["ok"])

    original_new_session_fn = mock_conn.new_session

    async def counting_new_session(cwd):
        nonlocal new_session_count
        new_session_count += 1
        return await original_new_session_fn(cwd=cwd)

    mock_conn.new_session = counting_new_session

    with patch("src.runners.acp_runner.ACPConnection", return_value=mock_conn), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.returncode = None
        mock_spawn.return_value = mock_proc

        # Concurrent calls for same user
        await asyncio.gather(
            _consume(runner.run("msg1", user_id=99, channel="tg", cwd="/tmp")),
            _consume(runner.run("msg2", user_id=99, channel="tg", cwd="/tmp")),
        )

    assert new_session_count == 1, f"Expected 1 session, got {new_session_count}"
