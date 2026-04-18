import json, pytest
from pathlib import Path


def test_audit_writes_entry(tmp_path):
    from src.runners.audit import AuditLog
    log = AuditLog(audit_dir=str(tmp_path), max_entries=1000)
    log.write(user_id=123, channel="telegram", runner="claude", prompt="hello", cwd="/home")

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["user_id"] == 123
    assert entry["runner"] == "claude"
    assert entry["prompt"] == "hello"
    assert "ts" in entry


def test_audit_multiple_entries(tmp_path):
    from src.runners.audit import AuditLog
    log = AuditLog(audit_dir=str(tmp_path), max_entries=1000)
    for i in range(3):
        log.write(user_id=i, channel="telegram", runner="claude", prompt=f"msg {i}", cwd="/")

    files = list(tmp_path.glob("*.jsonl"))
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 3


def test_audit_creates_dir_if_missing(tmp_path):
    from src.runners.audit import AuditLog
    nested = tmp_path / "a" / "b" / "audit"
    log = AuditLog(audit_dir=str(nested), max_entries=1000)
    log.write(user_id=1, channel="telegram", runner="claude", prompt="x", cwd="/")
    assert nested.exists()
