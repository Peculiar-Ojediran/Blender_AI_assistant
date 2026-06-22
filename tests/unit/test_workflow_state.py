from itertools import pairwise

from extension.workflow.state import (
    BUSY_STATUSES,
    LEGAL_TRANSITIONS,
    PROMPT_EDITABLE_STATUSES,
    WorkflowStatus,
    can_transition,
)


def test_every_workflow_status_has_transition_rules() -> None:
    assert set(LEGAL_TRANSITIONS) == set(WorkflowStatus)


def test_busy_states_do_not_allow_prompt_editing() -> None:
    assert BUSY_STATUSES.isdisjoint(PROMPT_EDITABLE_STATUSES)


def test_expected_approval_flow_transitions_are_legal() -> None:
    flow = (
        WorkflowStatus.IDLE,
        WorkflowStatus.COLLECTING_CONTEXT,
        WorkflowStatus.PLANNING,
        WorkflowStatus.VALIDATING,
        WorkflowStatus.AWAITING_APPROVAL,
        WorkflowStatus.EXECUTING,
        WorkflowStatus.COMPLETE,
        WorkflowStatus.IDLE,
    )

    assert all(can_transition(current, target) for current, target in pairwise(flow))


def test_execution_cannot_start_from_idle() -> None:
    assert not can_transition(WorkflowStatus.IDLE, WorkflowStatus.EXECUTING)
