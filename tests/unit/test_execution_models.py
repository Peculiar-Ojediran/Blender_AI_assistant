import sys
from types import ModuleType, SimpleNamespace

import pytest

from extension.operations import ChangeKind, ChangeRecord, ExecutionResult
from extension.operations.executor import _resolve_openai_image_api_key


def test_execution_result_counts_unique_changed_datablocks() -> None:
    result = ExecutionResult(
        operation_count=2,
        completed_operations=2,
        changes=(
            ChangeRecord("move", "obj_0001", "object", "Cube", ChangeKind.UPDATED, "Moved"),
            ChangeRecord(
                "rename",
                "obj_0001",
                "object",
                "Hero Cube",
                ChangeKind.UPDATED,
                "Renamed",
            ),
            ChangeRecord(
                "material",
                "result:material",
                "material",
                "Metal",
                ChangeKind.CREATED,
                "Created",
            ),
        ),
    )

    assert result.changed_count == 2


def test_rolled_back_result_reports_no_remaining_changes() -> None:
    result = ExecutionResult(
        operation_count=2,
        completed_operations=1,
        changes=(),
        rolled_back=True,
    )

    assert result.rolled_back
    assert not result.partial
    assert result.changed_count == 0


def test_openai_image_key_resolver_uses_openai_session_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("extension.operations.executor.resolve_environment_value", lambda _name: "")
    fake_ui_package = ModuleType("extension.ui")
    fake_ui_package.__dict__["__path__"] = []
    fake_preferences_module = ModuleType("extension.ui.preferences")
    preferences = SimpleNamespace(session_api_key=" sk-session ")
    fake_preferences_module.__dict__["get_preferences"] = lambda _context: preferences
    fake_preferences_module.__dict__["resolve_provider_choice"] = (
        lambda _preferences: "OPENAI"
    )
    monkeypatch.setitem(sys.modules, "extension.ui", fake_ui_package)
    monkeypatch.setitem(sys.modules, "extension.ui.preferences", fake_preferences_module)

    assert _resolve_openai_image_api_key(object()) == "sk-session"


def test_openai_image_key_resolver_does_not_reuse_nvidia_session_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("extension.operations.executor.resolve_environment_value", lambda _name: "")
    fake_ui_package = ModuleType("extension.ui")
    fake_ui_package.__dict__["__path__"] = []
    fake_preferences_module = ModuleType("extension.ui.preferences")
    preferences = SimpleNamespace(session_api_key=" nvapi-test ")
    fake_preferences_module.__dict__["get_preferences"] = lambda _context: preferences
    fake_preferences_module.__dict__["resolve_provider_choice"] = (
        lambda _preferences: "NVIDIA"
    )
    monkeypatch.setitem(sys.modules, "extension.ui", fake_ui_package)
    monkeypatch.setitem(sys.modules, "extension.ui.preferences", fake_preferences_module)

    assert _resolve_openai_image_api_key(object()) == ""
