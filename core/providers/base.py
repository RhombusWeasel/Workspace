"""Provider base class and shared dataclasses.

Defines the contract that every LLM provider must satisfy, plus the
normalised response types that insulate the rest of Workspace from
provider-specific details.

The :class:`BaseProvider` base class applies **automatic redaction** to
every message before it leaves the process.  Subclasses implement
:meth:`_do_chat` and :meth:`_do_stream_chat` and never handle raw
(un-redacted) messages directly — the base class scrubs them first.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any, AsyncIterator

from core.config import register_defaults

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token counts for a single turn."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    context_length: int | None = None
    """Maximum context window size in tokens, if known."""


@dataclass
class ToolCall:
    """A single tool-call request emitted by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class StreamChunk:
    """One chunk of a streaming response."""

    content: str
    done: bool = False
    usage: TokenUsage | None = None
    thinking: str | None = None
    """Reasoning / chain-of-thought emitted by the model (DeepSeek-R1, Qwen, etc.)."""
    tool_calls: list[ToolCall] | None = None
    """Tool calls emitted in this chunk (typically on the final ``done`` chunk)."""
    tool_results: dict[str, str] | None = None
    """Tool execution results — maps tool call ID to result string.

    Yielded by the agent after executing tool calls so the UI can display
    the output alongside the call arguments."""


@dataclass
class Message:
    """A chat message with role and content.

    For assistant messages that make tool calls, set ``tool_calls``.
    For tool-result messages, set ``name`` to the tool name (maps to
    Ollama's ``tool_name`` field).
    """

    role: str
    content: str
    tool_calls: list[ToolCall] | None = None
    name: str | None = None


@dataclass
class ChatResponse:
    """A complete (non-streaming) response from a provider."""

    content: str
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] | None = None
    thinking: str | None = None
    """Reasoning / chain-of-thought emitted by the model (DeepSeek-R1, Qwen, etc.)."""


# ---------------------------------------------------------------------------
# Redaction constants and helper
# ---------------------------------------------------------------------------

REDACTED: str = "REDACTED"
"""The replacement string for all sensitive matches."""

register_defaults({
    "redaction": {
        "enabled": True,
        "patterns": [],
    }
})


def _build_redactor(vault: Any, config: Any) -> _Redactor:
    """Build a redactor from the current vault and config state.

    Reads secrets from the vault (if unlocked) and compiles quoted-string
    regex patterns for each one.  Returns a disabled redactor if the
    vault is locked or unavailable.
    """
    enabled = config.get("redaction.enabled", True)
    pattern_strings: list[str] = config.get("redaction.patterns", []) or []

    patterns: list[re.Pattern[str]] = []
    for pattern_str in pattern_strings:
        if not pattern_str or not pattern_str.strip():
            # Skip empty/blank patterns — an empty-string regex matches
            # at every position, which would catastrophically expand text.
            continue
        try:
            patterns.append(re.compile(pattern_str))
        except re.error as exc:
            print(
                f"Warning: skipping invalid redaction pattern "
                f"{pattern_str!r}: {exc}",
                file=sys.stderr,
            )

    secrets: list[str] = []
    if vault is not None and not vault.is_locked():
        try:
            for name in vault.list_credentials():
                cred = vault.get_credential(name)
                if cred is not None:
                    _, password = cred
                    if password:
                        secrets.append(password)
        except RuntimeError:
            pass  # Vault became locked mid-read.
        try:
            for name in vault.list_secure_notes():
                note = vault.get_secure_note(name)
                if note is not None:
                    secrets.append(note)
        except RuntimeError:
            pass  # Vault became locked mid-read.

    # Sort is handled by _Redactor.__init__.

    return _Redactor(secrets=secrets, patterns=patterns, enabled=enabled)


class _Redactor:
    """Internal redactor used by :class:`BaseProvider`.

    Replaces vault secrets and config regex patterns with ``REDACTED``
    in message content and tool call arguments before they are sent to
    the LLM.

    **Secret matching** uses quoted-string matching: a secret is only
    redacted when it appears as the *complete content* between matching
    quote delimiters.  Supported quote styles are single quotes
    (``'secret'``), double quotes (``"secret"``), and backticks
    (```secret```).  This avoids false positives where a secret string
    like ``"admin"`` would incorrectly match a variable name like
    ``get_admin_user`` or a word in prose.

    Example matches::

        password = "my-secret"      # → password = "REDACTED"
        api_key = 'sk-abc123'       # → api_key = 'REDACTED'
        token: `ghp_xyz789`         # → token: `REDACTED`

    Example non-matches::

        get_admin_user()            # not in quotes
        "use my-secret to auth"     # not the entire quoted string
        the admin panel              # prose, not in quotes
    """

    def __init__(
        self,
        secrets: list[str],
        patterns: list[re.Pattern[str]],
        enabled: bool = True,
    ) -> None:
        # Pre-compile a quoted-string regex for each secret.
        # A secret matches only when it is the entire content between
        # matching quote delimiters: 'secret', "secret", or `secret`.
        # The regex uses a backreference (\1) to ensure the opening
        # and closing quotes match.
        self._secret_patterns: list[re.Pattern[str]] = []
        for secret in secrets:
            if not secret:
                continue
            escaped = re.escape(secret)
            # Group 1: opening quote (' | " | `)
            # Group 2: the secret content
            # \1: closing quote must match the opening quote
            pattern = re.compile(rf"(['\"`])({escaped})\1")
            self._secret_patterns.append(pattern)

        # Filter out empty/blank patterns — an empty-string regex matches
        # at every position, which would insert REDACTED between every
        # character and catastrophically expand the text.
        self._patterns = [
            p for p in patterns
            if p.pattern  # skip compile("") / compile(blank)
        ]
        self._enabled = enabled

    def redact_text(self, text: str) -> str:
        if not self._enabled:
            return text
        # Replace quoted secrets: 'secret' → 'REDACTED', "secret" → "REDACTED"
        # Each pattern captures (quote)(secret_content)(matching_quote).
        # We replace only group 2 (the secret content) with REDACTED,
        # preserving the original quote characters.
        for pattern in self._secret_patterns:
            text = pattern.sub(rf'\1{REDACTED}\1', text)
        for pattern in self._patterns:
            text = pattern.sub(REDACTED, text)
        return text

    def redact_message(self, message: Message) -> Message:
        if not self._enabled:
            return message
        content = self.redact_text(message.content)
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.name,
                    arguments=self._redact_value(tc.arguments),
                )
                for tc in message.tool_calls
            ]
        return Message(
            role=message.role,
            content=content,
            tool_calls=tool_calls,
            name=message.name,
        )

    def redact_messages(self, messages: list[Message]) -> list[Message]:
        return [self.redact_message(m) for m in messages]

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {k: self._redact_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        return value


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------


class BaseProvider:
    """Base class for all LLM providers.

    Automatically redacts messages before sending them to the LLM.
    Subclasses implement :meth:`_do_chat` and :meth:`_do_stream_chat`
    to perform the actual provider-specific API call.  They receive
    **already-redacted** messages and never see raw secrets.

    Parameters
    ----------
    vault:
        A :class:`~core.vault.VaultManager` instance for reading
        secrets to redact.  ``None`` disables vault-based redaction
        (but config regex patterns still apply if config is provided).
    config:
        A :class:`~core.config.Config` instance for reading redaction
        config (enabled flag, regex patterns).  ``None`` disables
        all redaction.
    """

    def __init__(
        self,
        vault: Any = None,
        config: Any = None,
    ) -> None:
        self._vault = vault
        self._config = config
        # Cached secrets from the vault.  Once the vault is unlocked,
        # passwords and notes are captured here so that redaction
        # continues to work even if the vault is later re-locked
        # mid-session.
        self._cached_secrets: list[str] = []

    # ------------------------------------------------------------------
    # Redaction (automatic)
    # ------------------------------------------------------------------

    def _redact(self, messages: list[Message]) -> list[Message]:
        """Redact messages before sending to the LLM.

        Builds a fresh redactor from the vault and config each time,
        capturing new secrets when the vault is unlocked and using
        cached secrets when it is locked.
        """
        if self._config is None:
            return messages

        # When the vault is unlocked, refresh the secrets cache.
        if self._vault is not None and not self._vault.is_locked():
            secrets: list[str] = []
            try:
                for name in self._vault.list_credentials():
                    cred = self._vault.get_credential(name)
                    if cred is not None:
                        _, password = cred
                        if password:
                            secrets.append(password)
            except RuntimeError:
                pass  # Vault became locked mid-read — keep cache.
            try:
                for name in self._vault.list_secure_notes():
                    note = self._vault.get_secure_note(name)
                    if note is not None:
                        secrets.append(note)
            except RuntimeError:
                pass  # Vault became locked mid-read — keep cache.
            self._cached_secrets = secrets

        enabled = self._config.get("redaction.enabled", True)
        pattern_strings: list[str] = self._config.get("redaction.patterns", []) or []

        patterns: list[re.Pattern[str]] = []
        for pattern_str in pattern_strings:
            if not pattern_str or not pattern_str.strip():
                continue  # Skip empty/blank patterns — would catastrophically expand text.
            try:
                patterns.append(re.compile(pattern_str))
            except re.error:
                pass  # Invalid patterns already warned at startup.

        # Sort is handled by _Redactor.__init__.

        redactor = _Redactor(
            secrets=self._cached_secrets,
            patterns=patterns,
            enabled=enabled,
        )
        return redactor.redact_messages(messages)

    # ------------------------------------------------------------------
    # Public API (redacts automatically, then delegates)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Send a chat request and return the complete response.

        Messages are **automatically redacted** before being sent
        to the provider-specific implementation.
        """
        redacted = self._redact(messages)
        return await self._do_chat(redacted, model, tools)

    async def stream_chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Send a chat request and stream the response as chunks.

        Messages are **automatically redacted** before being sent
        to the provider-specific implementation.
        """
        redacted = self._redact(messages)
        async for chunk in self._do_stream_chat(redacted, model, tools):
            yield chunk

    # ------------------------------------------------------------------
    # Subclass interface (receives already-redacted messages)
    # ------------------------------------------------------------------

    async def _do_chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Perform the provider-specific chat request.

        Subclasses must override this method.  *messages* have already
        been redacted by the base class.
        """
        raise NotImplementedError

    async def _do_stream_chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Perform the provider-specific streaming chat request.

        Subclasses must override this method.  *messages* have already
        been redacted by the base class.
        """
        raise NotImplementedError
        # Make this an async generator so `async for` works on the
        # NotImplementedError path.
        yield  # type: ignore[misc]  # pragma: no cover