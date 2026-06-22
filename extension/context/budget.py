"""Deterministically apply summary and detailed-object context budgets."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObjectBudgetResult:
    summary_ids: tuple[str, ...]
    detailed_ids: tuple[str, ...]
    omitted_summaries: int
    omitted_details: int


def apply_object_budget(
    scoped_ids: tuple[str, ...],
    *,
    active_id: str | None,
    selected_ids: frozenset[str],
    detailed_limit: int,
    summary_limit: int,
) -> ObjectBudgetResult:
    if detailed_limit < 1 or summary_limit < 1:
        raise ValueError("Context budgets must be positive.")
    if detailed_limit > summary_limit:
        raise ValueError("The detailed limit cannot exceed the summary limit.")

    unique_ids = tuple(dict.fromkeys(scoped_ids))
    priority: list[str] = []
    if active_id in unique_ids:
        priority.append(active_id)
    priority.extend(
        target_id
        for target_id in unique_ids
        if target_id in selected_ids and target_id not in priority
    )
    priority.extend(target_id for target_id in unique_ids if target_id not in priority)

    summary_ids = tuple(priority[:summary_limit])
    detailed_ids = tuple(summary_ids[:detailed_limit])
    return ObjectBudgetResult(
        summary_ids=summary_ids,
        detailed_ids=detailed_ids,
        omitted_summaries=max(0, len(unique_ids) - len(summary_ids)),
        omitted_details=max(0, len(summary_ids) - len(detailed_ids)),
    )
