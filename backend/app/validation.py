"""Shared validation helpers used by admin routes and MCP server."""


def get_invalid_categories(db, categories: list[str]) -> list[str]:
    """Return category names not in the admin-configured allowed list.

    Returns an empty list when:
    - *categories* is empty
    - No ``config/categories`` document exists yet
    - The allowed list in that document is empty

    In all of those cases every category is considered valid.
    """
    if not categories:
        return []
    doc = db.collection("config").document("categories").get()
    if not doc.exists:
        return []
    allowed: set[str] = set(doc.to_dict().get("list", []))
    if not allowed:
        return []
    return [c for c in categories if c not in allowed]
