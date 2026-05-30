"""Message redaction — replaces sensitive content before sending to LLMs.

.. deprecated::
    The redaction logic now lives in :mod:`core.providers.base` as part
    of the :class:`~core.providers.base.BaseProvider` base class.  Every
    provider automatically redacts messages before sending them.  This
    module remains for backward compatibility and re-exports the public
    API.

The :class:`~core.providers.base.BaseProvider._redact` method builds a
redactor from the vault and config on every call, applying it to all
messages before they reach the provider-specific implementation.
"""

from __future__ import annotations

# Re-export public API from the canonical location.
from core.providers.base import REDACTED, _Redactor as Redactor  # noqa: F401


# ---------------------------------------------------------------------------
# Backward-compatible factory functions
# ---------------------------------------------------------------------------

import re
import sys
from typing import Any

from core.config import register_defaults
from core.providers.base import Message


def create_redactor(vault: Any, config: Any) -> Redactor:
    """Create a :class:`Redactor` from the current vault and config state.

    .. deprecated::
        Redaction is now handled automatically by
        :class:`~core.providers.base.BaseProvider`.  Use the provider's
        built-in redaction instead of creating a standalone Redactor.
    """
    enabled = config.get("redaction.enabled", True)
    pattern_strings: list[str] = config.get("redaction.patterns", []) or []

    patterns: list[re.Pattern[str]] = []
    for pattern_str in pattern_strings:
        try:
            patterns.append(re.compile(pattern_str))
        except re.error as exc:
            print(
                f"Warning: skipping invalid redaction pattern "
                f"{pattern_str!r}: {exc}",
                file=sys.stderr,
            )

    secrets: list[str] = []
    if not vault.is_locked():
        try:
            for name in vault.list_credentials():
                cred = vault.get_credential(name)
                if cred is not None:
                    _, password = cred
                    if password:
                        secrets.append(password)
        except RuntimeError:
            pass

        try:
            for name in vault.list_secure_notes():
                note = vault.get_secure_note(name)
                if note is not None:
                    secrets.append(note)
        except RuntimeError:
            pass

    return Redactor(secrets=secrets, patterns=patterns, enabled=enabled)


def create_redactor_from_cache(
    secrets: list[str],
    config: Any,
) -> Redactor:
    """Create a :class:`Redactor` using pre-cached secrets and config.

    .. deprecated::
        Redaction is now handled automatically by
        :class:`~core.providers.base.BaseProvider`.  Use the provider's
        built-in redaction instead of creating a standalone Redactor.
    """
    enabled = config.get("redaction.enabled", True)
    pattern_strings: list[str] = config.get("redaction.patterns", []) or []

    patterns: list[re.Pattern[str]] = []
    for pattern_str in pattern_strings:
        try:
            patterns.append(re.compile(pattern_str))
        except re.error as exc:
            print(
                f"Warning: skipping invalid redaction pattern "
                f"{pattern_str!r}: {exc}",
                file=sys.stderr,
            )

    return Redactor(secrets=secrets, patterns=patterns, enabled=enabled)