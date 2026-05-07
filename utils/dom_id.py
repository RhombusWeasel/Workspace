"""DOM id utilities — generate valid Textual widget IDs from data.

Textual DOM ids must contain only letters, numbers, underscores, or
hyphens, and must not begin with a number.  These helpers convert
paths and other data into safe IDs.
"""

from __future__ import annotations

import hashlib
import os


def path_to_id(prefix: str, path: str) -> str:
    """Convert an absolute path to a valid Textual DOM id.

    Uses basename + short SHA-256 hash for uniqueness while staying
    readable.

    Parameters
    ----------
    prefix:
        A short prefix for the ID (e.g. ``"fb"`` for file browser,
        ``"fv"`` for file view).
    path:
        The absolute path to convert.

    Returns
    -------
    str
        A valid Textual DOM id like ``"fb-main_py-9e5a60"``.
    """
    name = os.path.basename(path) or "root"
    h = hashlib.sha256(path.encode()).hexdigest()[:6]
    # Sanitize: replace dots and spaces with underscores
    safe = name.replace(".", "_").replace(" ", "_")
    return f"{prefix}-{safe}-{h}"