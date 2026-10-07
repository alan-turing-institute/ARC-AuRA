"""
Tool for searching through already cached data. This is useful for finding out if a
given paper has already been cached, and if so, retrieving the cached paper.
"""


def key_for(tool: str, *args) -> str:
    """Generate a key for the cache based on the tool name and arguments.

    Args:
        tool: Name of the tool.
        *args: Arguments to be used in generating the key."""
    return f"{tool}:{':'.join(map(str, args))}"
