# tests/runners/test_cli_runner.py
import asyncio, pytest

pytestmark = pytest.mark.asyncio


async def test_cli_runner_echo(tmp_path):
    """Use 'echo' as a stand-in CLI to verify streaming output."""
    from src.runners.cli_runner import CLIRunner
    from src.runners.audit import AuditLog
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)

    runner = CLIRunner(
        name="echo_test",
        binary="echo",
        args=[],
        timeout_seconds=5,
        context_token_budget=1000,
        audit=audit,
    )

    chunks = []
    async for chunk in runner.run(
        prompt="hello world",
        user_id=1,
        channel="test",
        cwd=str(tmp_path),
    ):
        chunks.append(chunk)

    output = "".join(chunks)
    assert "hello world" in output


async def test_cli_runner_timeout(tmp_path):
    """A process that sleeps longer than timeout should raise TimeoutError."""
    from src.runners.cli_runner import CLIRunner
    from src.runners.audit import AuditLog
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)

    runner = CLIRunner(
        name="sleep_test",
        binary="sleep",
        args=[],
        timeout_seconds=1,
        context_token_budget=1000,
        audit=audit,
    )

    with pytest.raises(TimeoutError):
        async for _ in runner.run(
            prompt="10",   # sleep 10 seconds, but timeout is 1
            user_id=1,
            channel="test",
            cwd=str(tmp_path),
        ):
            pass


async def test_cli_runner_non_image_attachment_prepends_text(tmp_path):
    """Non-image attachments are prepended as [attached file: path] in the prompt."""
    from src.runners.cli_runner import CLIRunner
    from src.runners.audit import AuditLog
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)

    # Use 'echo' runner (not claude), so no --image flag path is taken
    runner = CLIRunner(
        name="echo_test",
        binary="echo",
        args=[],
        timeout_seconds=5,
        context_token_budget=1000,
        audit=audit,
    )

    pdf_path = str(tmp_path / "report.pdf")
    chunks = []
    async for chunk in runner.run(
        prompt="summarise this",
        user_id=1,
        channel="test",
        cwd=str(tmp_path),
        attachments=[pdf_path],
    ):
        chunks.append(chunk)

    output = "".join(chunks)
    assert pdf_path in output
    assert "summarise this" in output


async def test_cli_runner_writes_audit(tmp_path):
    from src.runners.cli_runner import CLIRunner
    from src.runners.audit import AuditLog
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)

    runner = CLIRunner(
        name="echo_test",
        binary="echo",
        args=[],
        timeout_seconds=5,
        context_token_budget=1000,
        audit=audit,
    )

    async for _ in runner.run(prompt="test prompt", user_id=42, channel="telegram", cwd="/"):
        pass

    import json
    files = list((tmp_path / "audit").glob("*.jsonl"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text().strip())
    assert entry["user_id"] == 42
    assert entry["runner"] == "echo_test"
