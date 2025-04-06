"""Utility functions for modal widgets."""


def _generate_widget_id(prefix: str, base_id: str) -> str:
    """Generates a Textual-safe widget ID with a prefix."""
    # Ensure base_id doesn't have characters invalidating the combined ID
    # (Basic check: usually hyphens in UUIDs are okay if not at start)
    return f"{prefix}-{base_id}"


def _extract_base_id(prefix: str, widget_id: str | None) -> str | None:
    """Extracts the base ID from a widget ID if the prefix matches."""
    expected_prefix = f"{prefix}-"
    if widget_id and widget_id.startswith(expected_prefix):
        return widget_id[len(expected_prefix) :]
    return None
