"""Errors raised while collecting Blender scene context."""


class ContextThreadError(RuntimeError):
    """Raised when Blender scene data is read outside the main thread."""


class ContextBudgetError(ValueError):
    """Raised when context cannot fit within the configured payload ceiling."""
