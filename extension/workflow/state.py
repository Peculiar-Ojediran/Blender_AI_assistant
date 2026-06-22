"""Workflow states and legal transitions used by the Blender UI."""

from enum import StrEnum


class WorkflowStatus(StrEnum):
    CONFIGURATION_REQUIRED = "configuration_required"
    IDLE = "idle"
    COLLECTING_CONTEXT = "collecting_context"
    PLANNING = "planning"
    VALIDATING = "validating"
    NEEDS_CLARIFICATION = "needs_clarification"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELED = "canceled"


BUSY_STATUSES = frozenset(
    {
        WorkflowStatus.COLLECTING_CONTEXT,
        WorkflowStatus.PLANNING,
        WorkflowStatus.VALIDATING,
        WorkflowStatus.EXECUTING,
    }
)

PROMPT_EDITABLE_STATUSES = frozenset(
    {
        WorkflowStatus.CONFIGURATION_REQUIRED,
        WorkflowStatus.IDLE,
        WorkflowStatus.NEEDS_CLARIFICATION,
        WorkflowStatus.COMPLETE,
        WorkflowStatus.ERROR,
        WorkflowStatus.CANCELED,
    }
)

LEGAL_TRANSITIONS = {
    WorkflowStatus.CONFIGURATION_REQUIRED: frozenset(
        {WorkflowStatus.IDLE, WorkflowStatus.ERROR}
    ),
    WorkflowStatus.IDLE: frozenset(
        {WorkflowStatus.CONFIGURATION_REQUIRED, WorkflowStatus.COLLECTING_CONTEXT}
    ),
    WorkflowStatus.COLLECTING_CONTEXT: frozenset(
        {WorkflowStatus.PLANNING, WorkflowStatus.CANCELED, WorkflowStatus.ERROR}
    ),
    WorkflowStatus.PLANNING: frozenset(
        {WorkflowStatus.VALIDATING, WorkflowStatus.CANCELED, WorkflowStatus.ERROR}
    ),
    WorkflowStatus.VALIDATING: frozenset(
        {
            WorkflowStatus.NEEDS_CLARIFICATION,
            WorkflowStatus.AWAITING_APPROVAL,
            WorkflowStatus.CANCELED,
            WorkflowStatus.ERROR,
        }
    ),
    WorkflowStatus.NEEDS_CLARIFICATION: frozenset(
        {
            WorkflowStatus.COLLECTING_CONTEXT,
            WorkflowStatus.PLANNING,
            WorkflowStatus.IDLE,
            WorkflowStatus.CANCELED,
        }
    ),
    WorkflowStatus.AWAITING_APPROVAL: frozenset(
        {WorkflowStatus.EXECUTING, WorkflowStatus.IDLE, WorkflowStatus.CANCELED}
    ),
    WorkflowStatus.EXECUTING: frozenset(
        {WorkflowStatus.COMPLETE, WorkflowStatus.CANCELED, WorkflowStatus.ERROR}
    ),
    WorkflowStatus.COMPLETE: frozenset(
        {WorkflowStatus.IDLE, WorkflowStatus.COLLECTING_CONTEXT}
    ),
    WorkflowStatus.ERROR: frozenset(
        {
            WorkflowStatus.IDLE,
            WorkflowStatus.COLLECTING_CONTEXT,
            WorkflowStatus.CONFIGURATION_REQUIRED,
        }
    ),
    WorkflowStatus.CANCELED: frozenset(
        {WorkflowStatus.IDLE, WorkflowStatus.COLLECTING_CONTEXT}
    ),
}


def can_transition(current: WorkflowStatus, target: WorkflowStatus) -> bool:
    return current == target or target in LEGAL_TRANSITIONS[current]
