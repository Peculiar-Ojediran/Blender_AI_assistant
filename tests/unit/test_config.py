from pathlib import Path

import pytest

from extension.config import (
    environment_value_source,
    read_environment_file,
    resolve_environment_value,
)


def test_environment_file_reads_unquoted_and_quoted_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# local secrets\nOPENAI_API_KEY='test-key'\nEMPTY=\nINVALID\n",
        encoding="utf-8",
    )

    assert read_environment_file(env_path) == {
        "OPENAI_API_KEY": "test-key",
        "EMPTY": "",
    }


def test_process_environment_takes_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")

    assert resolve_environment_value("OPENAI_API_KEY", env_path=env_path) == "process-key"
    assert environment_value_source("OPENAI_API_KEY", env_path=env_path) == "Environment"


def test_local_file_is_used_when_process_value_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert resolve_environment_value("OPENAI_API_KEY", env_path=env_path) == "file-key"
    assert environment_value_source("OPENAI_API_KEY", env_path=env_path) == "Local .env"
