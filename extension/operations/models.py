"""Typed records for validated controlled-operation plans."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PlanStatus(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"


class OperationType(StrEnum):
    CREATE_PRIMITIVE = "CREATE_PRIMITIVE"
    DELETE_OBJECTS = "DELETE_OBJECTS"
    DUPLICATE_OBJECTS = "DUPLICATE_OBJECTS"
    SET_TRANSFORM = "SET_TRANSFORM"
    CREATE_MATERIAL = "CREATE_MATERIAL"
    ASSIGN_MATERIAL = "ASSIGN_MATERIAL"
    ADD_LIGHT = "ADD_LIGHT"
    ADD_CAMERA = "ADD_CAMERA"
    RENAME_OBJECTS = "RENAME_OBJECTS"
    MOVE_TO_COLLECTION = "MOVE_TO_COLLECTION"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class Operation:
    operation_id: str
    type: OperationType
    payload: Mapping[str, Any]

    @property
    def target_ids(self) -> tuple[str, ...]:
        raw_targets = self.payload.get("target_ids")
        if isinstance(raw_targets, tuple):
            return tuple(value for value in raw_targets if isinstance(value, str))

        renames = self.payload.get("renames")
        if isinstance(renames, tuple):
            return tuple(
                rename["target_id"]
                for rename in renames
                if isinstance(rename, Mapping) and isinstance(rename.get("target_id"), str)
            )

        return ()


@dataclass(frozen=True, slots=True)
class OperationPlan:
    snapshot_id: str
    status: PlanStatus
    intent_summary: str
    assumptions: tuple[str, ...]
    questions: tuple[str, ...]
    operations: tuple[Operation, ...]


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel
    requires_confirmation: bool
    reasons: tuple[str, ...]
    affected_object_count: int
