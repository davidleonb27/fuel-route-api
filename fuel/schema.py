def hide_slashless_aliases(endpoints):
    """drf-spectacular hook: document only the canonical trailing-slash URLs."""
    return [endpoint for endpoint in endpoints if endpoint[0].endswith("/")]
