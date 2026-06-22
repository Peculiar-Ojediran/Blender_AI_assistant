"""Extension-wide configuration and local development environment loading."""

import os
from pathlib import Path

PROJECT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def resolve_environment_value(name: str, *, env_path: Path = PROJECT_ENV_PATH) -> str:
    """Use the process environment first, then a local gitignored .env file."""

    process_value = os.environ.get(name, "").strip()
    if process_value:
        return process_value
    return read_environment_file(env_path).get(name, "").strip()


def environment_value_source(name: str, *, env_path: Path = PROJECT_ENV_PATH) -> str:
    if os.environ.get(name, "").strip():
        return "Environment"
    if read_environment_file(env_path).get(name, "").strip():
        return "Local .env"
    return "Missing"


def read_environment_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE entries without interpolation or environment mutation."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return {}

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values
