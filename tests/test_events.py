"""Tests for the Cody event system."""

import pytest

from context import AppContext
from core.events import (
    CodyEvent,
    dispatch,
    register_handler,
    reset_handlers,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure handler registry is clean before every test."""
    reset_handlers()
    yield
    reset_handlers()


# ---------------------------------------------------------------------------
# CodyEvent
# ---------------------------------------------------------------------------


class TestCodyEvent:
    def test_construction_defaults(self):
        event = CodyEvent("chat.send")
        assert event.event_type == "chat.send"
        assert event.data == {}
        assert event.namespace == "cody"

    def test_construction_with_data(self):
        event = CodyEvent("analysis.complete", {"count": 5, "name": "test"})
        assert event.event_type == "analysis.complete"
        assert event.data == {"count": 5, "name": "test"}

    def test_is_textual_message(self):
        event = CodyEvent("test")
        from textual.message import Message

        assert isinstance(event, Message)


# ---------------------------------------------------------------------------
# register_handler decorator
# ---------------------------------------------------------------------------


class TestRegisterHandler:
    def test_decorator_returns_function(self):
        @register_handler("test.event")
        def handler(data, ctx):
            pass

        assert callable(handler)

    def test_handler_is_registered(self):
        calls = []

        @register_handler("test.event")
        def handler(data, ctx):
            calls.append(data)

        ctx = AppContext()
        dispatch(CodyEvent("test.event", {"x": 1}), ctx)
        assert calls == [{"x": 1}]

    def test_multiple_handlers_same_event(self):
        calls = []

        @register_handler("duplicate")
        def first(data, ctx):
            calls.append("first")

        @register_handler("duplicate")
        def second(data, ctx):
            calls.append("second")

        dispatch(CodyEvent("duplicate"), AppContext())
        assert "first" in calls
        assert "second" in calls
        assert len(calls) == 2

    def test_handlers_receive_context(self):
        received_ctx = []

        @register_handler("ctx.test")
        def handler(data, ctx):
            received_ctx.append(ctx)

        ctx = AppContext(working_directory="/home/test")
        dispatch(CodyEvent("ctx.test"), ctx)
        assert received_ctx[0] is ctx
        assert received_ctx[0].working_directory == "/home/test"


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_no_handlers_does_nothing(self):
        """Dispatching an event with no registered handlers should not error."""
        dispatch(CodyEvent("nobody.home"), AppContext())
        # No exception = pass

    def test_handler_not_called_for_different_event(self):
        calls = []

        @register_handler("only.this")
        def handler(data, ctx):
            calls.append(1)

        dispatch(CodyEvent("something.else"), AppContext())
        assert calls == []

    def test_data_passed_through(self):
        results = []

        @register_handler("data.test")
        def handler(data, ctx):
            results.append(data)

        dispatch(CodyEvent("data.test", {"key": "value", "nested": {"a": 1}}), AppContext())
        assert results == [{"key": "value", "nested": {"a": 1}}]

    def test_empty_data(self):
        results = []

        @register_handler("empty.data")
        def handler(data, ctx):
            results.append(data)

        dispatch(CodyEvent("empty.data"), AppContext())
        assert results == [{}]


# ---------------------------------------------------------------------------
# reset_handlers
# ---------------------------------------------------------------------------


class TestResetHandlers:
    def test_reset_clears_all_handlers(self):
        calls = []

        @register_handler("pre.reset")
        def handler(data, ctx):
            calls.append(1)

        # Verify it was registered
        dispatch(CodyEvent("pre.reset"), AppContext())
        assert len(calls) == 1

        # Reset
        reset_handlers()
        calls.clear()

        # Should be empty now
        dispatch(CodyEvent("pre.reset"), AppContext())
        assert calls == []

    def test_reset_then_re_register(self):
        @register_handler("re.register")
        def first(data, ctx):
            pass

        reset_handlers()

        calls = []

        @register_handler("re.register")
        def second(data, ctx):
            calls.append("second")

        dispatch(CodyEvent("re.register"), AppContext())
        assert calls == ["second"]
