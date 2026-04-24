import pytest
from pathlib import Path
from unittest.mock import patch
from src.setup.deploy import (
    write_config_toml, write_env_file, write_systemd_unit,
    write_docker_compose, create_data_dirs,
)


def test_write_config_toml_creates_file(tmp_path):
    path = str(tmp_path / "config/config.toml")
    write_config_toml(path, {"default_runner": "claude", "runners": ["claude"]})
    assert Path(path).exists()


def test_write_config_toml_contains_default_runner(tmp_path):
    path = str(tmp_path / "config.toml")
    write_config_toml(path, {"default_runner": "codex", "runners": ["codex"]})
    content = Path(path).read_text()
    assert 'default_runner = "codex"' in content


def test_write_config_toml_includes_runner_sections(tmp_path):
    path = str(tmp_path / "config.toml")
    write_config_toml(path, {"default_runner": "claude", "runners": ["claude", "gemini"]})
    content = Path(path).read_text()
    assert "[runners.claude]" in content
    assert "[runners.gemini]" in content
    assert "[runners.codex]" not in content


def test_write_config_toml_uses_auto_approve_defaults(tmp_path):
    path = str(tmp_path / "config.toml")
    write_config_toml(path, {"default_runner": "claude", "runners": ["codex", "gemini"]})
    content = Path(path).read_text()
    assert 'args = ["exec", "--full-auto", "--skip-git-repo-check"]' in content
    assert 'args = ["--approval-mode", "yolo"]' in content


def test_write_env_file_creates_file(tmp_path):
    path = str(tmp_path / "secrets/.env")
    write_env_file(path, {"TELEGRAM_BOT_TOKEN": "abc"})
    assert Path(path).exists()


def test_write_env_file_content(tmp_path):
    path = str(tmp_path / ".env")
    write_env_file(path, {"TELEGRAM_BOT_TOKEN": "tok123", "ALLOWED_USER_IDS": "456,789"})
    content = Path(path).read_text()
    assert 'TELEGRAM_BOT_TOKEN="tok123"' in content
    assert 'ALLOWED_USER_IDS="456,789"' in content


def test_write_systemd_unit_content(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        write_systemd_unit("/opt/gateway")
    unit_path = tmp_path / ".config/systemd/user/gateway-agent.service"
    assert unit_path.exists()
    content = unit_path.read_text()
    assert "WorkingDirectory=/opt/gateway" in content
    assert "ExecStart=/opt/gateway/venv/bin/python3 main.py" in content
    assert "Restart=always" in content


def test_write_docker_compose_content(tmp_path):
    write_docker_compose(str(tmp_path))
    compose = (tmp_path / "docker-compose.yml").read_text()
    assert "gateway:" in compose
    assert "./data:/app/data" in compose
    assert "restart: unless-stopped" in compose


def test_write_docker_compose_creates_dockerfile_if_missing(tmp_path):
    write_docker_compose(str(tmp_path))
    assert (tmp_path / "Dockerfile").exists()


def test_write_docker_compose_does_not_overwrite_existing_dockerfile(tmp_path):
    existing = "FROM custom-base\n"
    (tmp_path / "Dockerfile").write_text(existing)
    write_docker_compose(str(tmp_path))
    assert (tmp_path / "Dockerfile").read_text() == existing


def test_create_data_dirs(tmp_path):
    create_data_dirs(str(tmp_path))
    for subdir in ["data/memory/hot", "data/memory/cold/permanent",
                   "data/memory/cold/session", "data/db", "data/audit"]:
        assert (tmp_path / subdir).is_dir()


def test_create_data_dirs_idempotent(tmp_path):
    create_data_dirs(str(tmp_path))
    create_data_dirs(str(tmp_path))  # must not raise
