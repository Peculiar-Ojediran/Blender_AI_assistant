"""Static declarations for non-live candidate search screen test coverage."""


def planned_candidate_screen_test_surfaces() -> tuple[str, ...]:
    return (
        "disabled_preference",
        "mocked_search",
        "mocked_inspection",
        "listing_candidate_block",
        "import_plan_handoff",
        "panel_registration",
    )
