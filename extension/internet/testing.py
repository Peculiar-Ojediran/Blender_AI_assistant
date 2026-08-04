"""Static declarations for planned internet-discovery test coverage."""


def planned_non_live_test_surfaces() -> tuple[str, ...]:
    return (
        "url_policy",
        "redirects",
        "size_limits",
        "empty_files",
        "mocked_openai_discovery",
        "candidate_review",
        "import_handoff",
    )
