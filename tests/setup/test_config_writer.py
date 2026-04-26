"""
Tests for src/setup/config_writer.py — non-destructive config write logic.
"""
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from src.setup.config_writer import write_config_with_diff, write_env_with_diff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _permissions(path: Path) -> int:
    """Return the file permission bits as an integer (e.g. 0o600)."""
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# write_config_with_diff tests
# ---------------------------------------------------------------------------


class TestWriteConfigWithDiff:
    def test_new_file_written_directly(self, tmp_path):
        """If the file does not exist, write directly without prompting."""
        target = tmp_path / "config" / "config.toml"
        content = "[gateway]\ndefault_runner = \"claude\"\n"

        with patch("src.setup.config_writer._prompt_tty") as mock_prompt:
            write_config_with_diff(str(target), content, label="config.toml")

        assert target.exists()
        assert target.read_text() == content
        mock_prompt.assert_not_called()

    def test_identical_content_skipped(self, tmp_path):
        """If content is identical, skip without prompting."""
        target = tmp_path / "config.toml"
        content = "[gateway]\ndefault_runner = \"codex\"\n"
        target.write_text(content)

        with patch("src.setup.config_writer._prompt_tty") as mock_prompt:
            write_config_with_diff(str(target), content, label="config.toml")

        assert target.read_text() == content
        mock_prompt.assert_not_called()

    def test_different_content_keep_does_not_overwrite(self, tmp_path):
        """Different content + user chooses 'k' — file stays unchanged, backup created."""
        target = tmp_path / "config.toml"
        existing = "[gateway]\ndefault_runner = \"claude\"\n"
        new_content = "[gateway]\ndefault_runner = \"codex\"\n"
        target.write_text(existing)

        with patch("src.setup.config_writer._prompt_tty", return_value="k"):
            write_config_with_diff(str(target), new_content, label="config.toml")

        # Original file must be unchanged
        assert target.read_text() == existing
        # A backup must have been created
        backups = list(tmp_path.glob("config.toml.bak.*"))
        assert len(backups) == 1
        assert backups[0].read_text() == existing

    def test_different_content_overwrite_replaces_file(self, tmp_path):
        """Different content + user chooses 'o' — file updated, backup created."""
        target = tmp_path / "config.toml"
        existing = "[gateway]\ndefault_runner = \"claude\"\n"
        new_content = "[gateway]\ndefault_runner = \"gemini\"\n"
        target.write_text(existing)

        with patch("src.setup.config_writer._prompt_tty", return_value="o"):
            write_config_with_diff(str(target), new_content, label="config.toml")

        assert target.read_text() == new_content
        backups = list(tmp_path.glob("config.toml.bak.*"))
        assert len(backups) == 1
        assert backups[0].read_text() == existing

    def test_parent_dirs_created_automatically(self, tmp_path):
        """Parent directories are created if they don't exist."""
        target = tmp_path / "nested" / "deep" / "config.toml"
        content = "[gateway]\n"

        with patch("src.setup.config_writer._prompt_tty"):
            write_config_with_diff(str(target), content)

        assert target.exists()

    def test_invalid_choice_loops_until_valid(self, tmp_path):
        """An invalid prompt answer is rejected; subsequent valid answer is used."""
        target = tmp_path / "config.toml"
        existing = "old content\n"
        new_content = "new content\n"
        target.write_text(existing)

        # First call returns junk, second returns 'k'
        with patch(
            "src.setup.config_writer._prompt_tty",
            side_effect=["x", "k"],
        ):
            write_config_with_diff(str(target), new_content)

        # 'k' → keep existing
        assert target.read_text() == existing

    def test_diff_truncated_to_40_lines(self, tmp_path, capsys):
        """Long diffs are truncated to 40 lines in the output."""
        target = tmp_path / "config.toml"
        existing = "\n".join(f"key_{i} = {i}" for i in range(50)) + "\n"
        new_content = "\n".join(f"key_{i} = {i * 2}" for i in range(50)) + "\n"
        target.write_text(existing)

        with patch("src.setup.config_writer._prompt_tty", return_value="k"):
            write_config_with_diff(str(target), new_content)

        out = capsys.readouterr().out
        assert "truncated" in out


# ---------------------------------------------------------------------------
# write_env_with_diff tests
# ---------------------------------------------------------------------------


class TestWriteEnvWithDiff:
    def test_new_env_file_written_with_mode_600(self, tmp_path):
        """New .env file is created and chmod'd to 0o600."""
        target = tmp_path / "secrets" / ".env"
        content = 'TELEGRAM_BOT_TOKEN="abc123"\n'

        with patch("src.setup.config_writer._prompt_tty"):
            write_env_with_diff(str(target), content, label=".env")

        assert target.exists()
        assert target.read_text() == content
        assert _permissions(target) == 0o600

    def test_identical_env_still_sets_mode_600(self, tmp_path):
        """Even when content is unchanged, permissions are set to 0o600."""
        target = tmp_path / ".env"
        content = 'TOKEN="xyz"\n'
        target.write_text(content)
        # Set a looser permission first to verify we tighten it
        target.chmod(0o644)

        with patch("src.setup.config_writer._prompt_tty"):
            write_env_with_diff(str(target), content)

        assert _permissions(target) == 0o600

    def test_different_env_keep_preserves_original_and_backup_is_600(self, tmp_path):
        """Different content + keep: original file unchanged, backup at mode 600."""
        target = tmp_path / ".env"
        existing = 'TOKEN="old"\n'
        new_content = 'TOKEN="new"\n'
        target.write_text(existing)

        with patch("src.setup.config_writer._prompt_tty", return_value="k"):
            write_env_with_diff(str(target), new_content, label=".env")

        assert target.read_text() == existing
        backups = list(tmp_path.glob(".env.bak.*"))
        assert len(backups) == 1
        assert _permissions(backups[0]) == 0o600

    def test_different_env_overwrite_sets_mode_600(self, tmp_path):
        """Different content + overwrite: new content written at mode 600."""
        target = tmp_path / ".env"
        target.write_text('TOKEN="old"\n')

        with patch("src.setup.config_writer._prompt_tty", return_value="o"):
            write_env_with_diff(str(target), 'TOKEN="new"\n')

        assert target.read_text() == 'TOKEN="new"\n'
        assert _permissions(target) == 0o600

    def test_no_prompt_for_new_env_file(self, tmp_path):
        """No interactive prompt when the file is new."""
        target = tmp_path / ".env"

        with patch("src.setup.config_writer._prompt_tty") as mock_prompt:
            write_env_with_diff(str(target), 'A="1"\n')

        mock_prompt.assert_not_called()

    def test_no_prompt_for_identical_env_content(self, tmp_path):
        """No interactive prompt when content is identical."""
        target = tmp_path / ".env"
        content = 'A="1"\n'
        target.write_text(content)

        with patch("src.setup.config_writer._prompt_tty") as mock_prompt:
            write_env_with_diff(str(target), content)

        mock_prompt.assert_not_called()
