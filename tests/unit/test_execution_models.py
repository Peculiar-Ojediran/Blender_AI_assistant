from extension.operations import ChangeKind, ChangeRecord, ExecutionResult


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
