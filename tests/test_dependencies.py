import fastjsonschema
import pytest
import requests

OPERATION_SCHEMA = {
    "type": "object",
    "properties": {"operation": {"type": "string"}},
    "required": ["operation"],
    "additionalProperties": False,
}


def test_runtime_dependency_versions() -> None:
    assert requests.__version__ == "2.32.3"
    assert fastjsonschema.VERSION == "2.21.1"


def test_schema_validator_accepts_valid_operation() -> None:
    validator = fastjsonschema.compile(OPERATION_SCHEMA)

    assert validator({"operation": "CREATE_PRIMITIVE"}) == {
        "operation": "CREATE_PRIMITIVE"
    }


def test_schema_validator_rejects_unknown_fields() -> None:
    validator = fastjsonschema.compile(OPERATION_SCHEMA)

    with pytest.raises(fastjsonschema.JsonSchemaException):
        validator({"operation": "CREATE_PRIMITIVE", "unsafe_code": "pass"})
