"""Verify release archive contents independently of Blender's manifest validator."""

import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

REQUIRED_FILES = {
    "__init__.py",
    "blender_manifest.toml",
    "providers/base.py",
    "providers/openai.py",
    "operations/executor.py",
    "operations/limits.py",
    "safety/policy.py",
    "ui/panels.py",
}
REQUIRED_WHEEL_PREFIXES = (
    "certifi-",
    "charset_normalizer-",
    "fastjsonschema-",
    "idna-",
    "requests-",
    "urllib3-",
)
FORBIDDEN_PARTS = {".env", "__pycache__"}
FORBIDDEN_SUFFIXES = (".pyc", ".pyo")


def verify_archive(archive_path: Path) -> None:
    if not archive_path.is_file():
        raise AssertionError(f"Release archive does not exist: {archive_path}")

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        missing = REQUIRED_FILES - names
        assert not missing, f"Release archive is missing: {sorted(missing)}"

        for name in names:
            path = PurePosixPath(name)
            assert not (set(path.parts) & FORBIDDEN_PARTS), f"Forbidden path: {name}"
            assert not name.endswith(FORBIDDEN_SUFFIXES), f"Forbidden bytecode: {name}"

        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        assert manifest["id"] == "blender_ai_assistant"
        assert manifest["version"] == "0.1.3"
        assert manifest["blender_version_min"] == "5.1.0"
        assert manifest["permissions"]["network"]

        wheel_entries = _string_list(manifest.get("wheels"))
        assert len(wheel_entries) == len(REQUIRED_WHEEL_PREFIXES)
        normalized_wheels = {entry.removeprefix("./") for entry in wheel_entries}
        assert normalized_wheels <= names
        wheel_names = {PurePosixPath(item).name for item in normalized_wheels}
        for prefix in REQUIRED_WHEEL_PREFIXES:
            assert any(name.startswith(prefix) for name in wheel_names), (
                f"Missing bundled wheel with prefix {prefix}"
            )

    print(
        f"Release package verification: PASS ({archive_path.name}, "
        f"{archive_path.stat().st_size} bytes)"
    )


def _string_list(value: Any) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return value


def main() -> None:
    archive_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("dist/blender_ai_assistant-0.1.3.zip")
    )
    verify_archive(archive_path.resolve())


if __name__ == "__main__":
    main()
