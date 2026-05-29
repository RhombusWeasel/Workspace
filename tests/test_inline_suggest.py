"""Tests for core.inline_suggest — inline suggestion engine."""

import asyncio
import pytest

from core.inline_suggest import _clean_completion, get_inline_suggestion
from core.providers.base import BaseProvider, ChatResponse, Message


# ---------------------------------------------------------------------------
# _clean_completion
# ---------------------------------------------------------------------------


class TestCleanCompletion:
    """Test _clean_completion strips fences, preambles, and duplicated prefixes."""

    def test_raw_completion(self):
        """Clean output passes through."""
        assert _clean_completion("foo()", "") == "foo()"

    def test_strips_code_fences(self):
        """Markdown code fences are removed."""
        assert _clean_completion("```python\nfoo()\n```", "") == "foo()"

    def test_strips_code_fences_no_lang(self):
        """Code fences without language tag are removed."""
        assert _clean_completion("```\nfoo()\n```", "") == "foo()"

    def test_strips_preamble_here_is(self):
        """'Here is the completion:' preamble is stripped."""
        assert _clean_completion("Here is the completion: foo()", "") == "foo()"

    def test_strips_preamble_completion(self):
        """'Completion:' preamble is stripped."""
        assert _clean_completion("Completion: foo()", "") == "foo()"

    def test_strips_preamble_result(self):
        """'Result:' preamble is stripped."""
        assert _clean_completion("Result: foo()", "") == "foo()"

    def test_strips_duplicated_prefix(self):
        """If output repeats text before cursor, the prefix is stripped."""
        assert _clean_completion("def foo()", "def f") == "oo()"

    def test_no_stripping_when_prefix_empty(self):
        """Empty prefix means no deduplication."""
        assert _clean_completion("foo()", "") == "foo()"

    def test_no_stripping_when_prefix_not_matched(self):
        """Output that doesn't start with the prefix is kept as-is."""
        assert _clean_completion("bar()", "def f") == "bar()"

    def test_multiline_output_first_line_only(self):
        """Default max_lines=8 allows multi-line output."""
        result = _clean_completion("foo()\nbar()", "")
        assert result == "foo()\nbar()"

    def test_multiline_with_max_lines(self):
        """max_lines truncates the output."""
        result = _clean_completion("line1\nline2\nline3\nline4", "", max_lines=2)
        assert result == "line1\nline2"

    def test_empty_lines_skipped(self):
        """Leading empty lines are skipped, trailing ones removed."""
        assert _clean_completion("\n\nfoo()", "") == "foo()"

    def test_empty_output(self):
        """Empty string returns empty string."""
        assert _clean_completion("", "") == ""

    def test_whitespace_only(self):
        """Whitespace-only output returns empty string."""
        assert _clean_completion("   \n   ", "") == ""

    def test_trailing_whitespace_stripped(self):
        """Trailing whitespace on result lines is stripped."""
        assert _clean_completion("foo()   ", "") == "foo()"

    def test_multiline_code_fence(self):
        """Multi-line code inside fences is preserved."""
        result = _clean_completion("```python\nfoo()\nbar()\n```", "")
        assert result == "foo()\nbar()"

    def test_multiline_duplicated_prefix(self):
        """First line deduplication works with multi-line output."""
        result = _clean_completion("def foo()\n    return 42", "def f")
        assert result == "oo()\n    return 42"

    def test_max_lines_zero_means_no_limit(self):
        """max_lines=0 means no line limit."""
        lines = "\n".join(f"line{i}" for i in range(20))
        result = _clean_completion(lines, "", max_lines=0)
        assert len(result.split("\n")) == 20

    def test_internal_blank_lines_preserved(self):
        """Blank lines between content lines are kept."""
        result = _clean_completion("foo()\n\nbar()", "")
        assert result == "foo()\n\nbar()"

    def test_trailing_blank_lines_removed(self):
        """Trailing blank lines are stripped."""
        result = _clean_completion("foo()\n\n", "")
        assert result == "foo()"


# ---------------------------------------------------------------------------
# get_inline_suggestion (integration with mock provider)
# ---------------------------------------------------------------------------


class _MockProvider:
    """Minimal mock provider that returns a canned response."""

    def __init__(self, response: ChatResponse):
        self._response = response
        self.calls: list[list[Message]] = []

    async def chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict] | None = None,
    ) -> ChatResponse:
        self.calls.append(messages)
        return self._response

    async def stream_chat(self, messages, model, tools=None):
        yield  # pragma: no cover


@pytest.fixture
def mock_provider():
    """Return a factory for _MockProvider."""

    def _make(content: str):
        return _MockProvider(ChatResponse(content=content))

    return _make


class TestGetInlineSuggestion:
    """Test get_inline_suggestion with a mock provider."""

    @pytest.mark.asyncio
    async def test_simple_completion(self, mock_provider):
        """A simple completion is returned."""
        provider = mock_provider("oo()")
        result = await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="test.py",
            file_content="def foo\n",
            cursor_row=0,
            cursor_col=7,
        )
        assert result == "oo()"

    @pytest.mark.asyncio
    async def test_with_code_fences(self, mock_provider):
        """Code fences in the response are stripped."""
        provider = mock_provider("```python\nfoo()\n```")
        result = await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="test.py",
            file_content="x = \n",
            cursor_row=0,
            cursor_col=4,
        )
        assert result == "foo()"

    @pytest.mark.asyncio
    async def test_duplicated_prefix_stripped(self, mock_provider):
        """Model repeating text before the cursor is stripped."""
        provider = mock_provider("x = foo()")
        result = await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="test.py",
            file_content="x = \n",
            cursor_row=0,
            cursor_col=4,
        )
        assert result == "foo()"

    @pytest.mark.asyncio
    async def test_empty_response(self, mock_provider):
        """Empty LLM response returns None."""
        provider = mock_provider("")
        result = await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="test.py",
            file_content="x = 1\n",
            cursor_row=0,
            cursor_col=5,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_provider_error(self):
        """Provider exceptions return None silently."""

        class _BrokenProvider:
            async def chat(self, messages, model, tools=None):
                raise ConnectionError("boom")

            async def stream_chat(self, messages, model, tools=None):
                yield  # pragma: no cover

        result = await get_inline_suggestion(
            provider=_BrokenProvider(),
            model="test",
            file_path="test.py",
            file_content="x = 1\n",
            cursor_row=0,
            cursor_col=5,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_context_lines_config(self, mock_provider):
        """Context line limits are passed through to gather_context."""
        provider = mock_provider("42")
        result = await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="test.py",
            file_content="x = \n",
            cursor_row=0,
            cursor_col=4,
            context_lines_above=10,
            context_lines_below=5,
        )
        assert result == "42"

    @pytest.mark.asyncio
    async def test_cursor_context_in_prompt(self, mock_provider):
        """The prompt includes the file path and CURSOR marker."""
        provider = mock_provider("bar")
        await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="app.py",
            file_content="foo\n",
            cursor_row=0,
            cursor_col=3,
        )
        user_msg = provider.calls[0][1].content
        assert "app.py" in user_msg
        assert "<CURSOR>" in user_msg

    @pytest.mark.asyncio
    async def test_multiline_completion(self, mock_provider):
        """Multi-line completions are returned with newlines."""
        provider = mock_provider("oo(arg2,\n    arg3):\n    return result")
        result = await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="test.py",
            file_content="def foo(arg1,\n",
            cursor_row=0,
            cursor_col=7,
        )
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_max_suggestion_lines(self, mock_provider):
        """max_suggestion_lines truncates multi-line completions."""
        lines = "\n".join(f"line{i}" for i in range(20))
        provider = mock_provider(lines)
        result = await get_inline_suggestion(
            provider=provider,
            model="test",
            file_path="test.py",
            file_content="x = \n",
            cursor_row=0,
            cursor_col=4,
            max_suggestion_lines=3,
        )
        assert result is not None
        assert len(result.split("\n")) <= 3