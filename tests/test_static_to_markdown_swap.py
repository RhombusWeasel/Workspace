"""Tests for the Static → Markdown swap after streaming ends.

Regression tests for the bug where the last response section in a
streaming turn stayed as a Static widget instead of being swapped
to Markdown when the stream ended.

Covers:
- batch_finalize_turns does DOM swap for already-mounted sections
- refresh_from_sections swaps last response to Markdown on finalize
- Thinking sections stay Static after finalize
- Content-changed sections get swapped during finalize
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Markdown, Static

from skills.chat.chat_display import (
    AssistantTurn,
    ChatDisplay,
    Section,
    UserMessage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sections(chat_id: str, turns: list[dict]) -> list[dict]:
    """Build flat section dicts from a list of turn dicts."""
    sections = []
    sec_idx = 0
    for turn in turns:
        tid = turn["turn_id"]
        for msg in turn["messages"]:
            sec_idx += 1
            sections.append({
                "turn_id": tid,
                "content_type": msg["content_type"],
                "content": msg["content"],
                "status": msg.get("status", "complete"),
                "section_id": msg.get("section_id", f"sec-{sec_idx}"),
                "id": sec_idx,
            })
    return sections


class _ChatApp(App):
    """Minimal app that mounts a ChatDisplay for testing."""

    CSS = """
    ChatDisplay { height: 20; }
    """

    def __init__(self):
        super().__init__()
        self.chat_display = ChatDisplay()

    def compose(self) -> ComposeResult:
        yield self.chat_display


# ---------------------------------------------------------------------------
# Tests — batch_finalize_turns DOM swap
# ---------------------------------------------------------------------------


class TestBatchFinalizeDOMSwap:
    """Test that batch_finalize_turns swaps Static → Markdown
    for sections that are already mounted in the DOM (post-streaming case),
    not just for pre-composition batch mode.
    """

    @pytest.mark.asyncio
    async def test_already_mounted_response_swaps_to_markdown(self):
        """A response section that's already in the DOM should be swapped
        from Static to Markdown by batch_finalize_turns."""
        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            # Simulate streaming: add section as Static (not batch mode)
            display.begin_assistant_turn(turn_id="t1")
            section_id = display.add_section("response")
            await display.update_section(section_id, "Hello **world**")
            await pilot.pause()

            # Verify the section is currently Static
            section = display._section_map.get(section_id)
            assert section is not None, "Section should exist in map"
            widget = display._section_widgets.get(section_id)
            assert isinstance(widget, Static), (
                f"Pre-finalize widget should be Static, got {type(widget).__name__}"
            )

            # Save references before finalize clears tracking dicts
            old_widget_id = widget.id

            # Now finalize — simulating what refresh_from_sections(finalize=True) does
            display.begin_batch()
            # Repopulate tracking dicts for batch_finalize_turns
            display._section_widgets[section_id] = widget
            display._section_texts[section_id] = "Hello **world**"
            display._section_types[section_id] = "response"

            display.batch_finalize_turns()
            display.end_batch()
            await pilot.pause()

            # The old Static widget should no longer be in the DOM
            # (replaced by a Markdown widget)
            md_widgets = list(display.query(Markdown))
            static_widgets = list(
                s for s in display.query(Static)
                if not isinstance(s, Markdown) and s.id == old_widget_id
            )
            assert len(md_widgets) >= 1, "Expected at least one Markdown widget in DOM"
            assert len(static_widgets) == 0, (
                "Old Static widget should have been removed from DOM"
            )

    @pytest.mark.asyncio
    async def test_thinking_section_stays_static_after_finalize(self):
        """Thinking sections should remain Static after finalize."""
        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            # Simulate streaming: add thinking section as Static
            display.begin_assistant_turn(turn_id="t1")
            section_id = display.add_section("thinking")
            await display.update_section(section_id, "Hmm, let me think...")
            await pilot.pause()

            widget = display._section_widgets.get(section_id)
            assert isinstance(widget, Static), (
                f"Thinking section should start as Static, got {type(widget).__name__}"
            )

            # Finalize
            display.begin_batch()
            display._section_widgets[section_id] = widget
            display._section_texts[section_id] = "Hmm, let me think..."
            display._section_types[section_id] = "thinking"

            display.batch_finalize_turns()
            display.end_batch()
            await pilot.pause()

            # Thinking section should still be Static in the DOM
            section = display._section_map.get(section_id)
            assert section is not None
            content_widget = section._content_widget
            assert isinstance(content_widget, Static), (
                f"Thinking section should stay Static after finalize, "
                f"got {type(content_widget).__name__}"
            )

    @pytest.mark.asyncio
    async def test_empty_response_section_not_swapped(self):
        """An empty response section should not be swapped to Markdown
        (no content to render)."""
        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            display.begin_assistant_turn(turn_id="t1")
            section_id = display.add_section("response")
            # Don't call update_section — content stays empty
            await pilot.pause()

            widget = display._section_widgets.get(section_id)
            assert isinstance(widget, Static)

            display.begin_batch()
            display._section_widgets[section_id] = widget
            display._section_texts[section_id] = ""  # empty
            display._section_types[section_id] = "response"

            display.batch_finalize_turns()
            display.end_batch()
            await pilot.pause()

            # Empty section should remain Static (no text to render as Markdown)
            section = display._section_map.get(section_id)
            assert section is not None
            content_widget = section._content_widget
            assert isinstance(content_widget, Static), (
                "Empty section should stay Static, not swapped to Markdown"
            )


# ---------------------------------------------------------------------------
# Tests — refresh_from_sections finalize swap
# ---------------------------------------------------------------------------


class TestRefreshFromSectionsFinalizeSwap:
    """Test that refresh_from_sections(finalize=True) correctly swaps
    the last response section from Static to Markdown, even when
    the content changed between the last streaming poll and the
    finalize call.
    """

    @pytest.mark.asyncio
    async def test_finalize_swaps_last_response_to_markdown(self):
        """After streaming ends, the last response section should be
        swapped to Markdown when refresh_from_sections(finalize=True)
        is called."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "response", "content": "Hi **there**!"},
                ],
            },
        ])

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            # Simulate streaming: first call with streaming status
            streaming_sections = []
            for sec in sections:
                s = dict(sec)
                if s["content_type"] == "response":
                    s["status"] = "streaming"
                streaming_sections.append(s)

            await display.refresh_from_sections(streaming_sections, finalize=False)
            await pilot.pause()

            # Verify response section is Static during streaming
            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 1
            assert isinstance(response_sections[0]._content_widget, Static), (
                "Response section should be Static during streaming"
            )

            # Now finalize with complete status
            await display.refresh_from_sections(sections, finalize=True)
            await pilot.pause()

            # After finalize, response section should be Markdown
            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 1
            assert isinstance(response_sections[0]._content_widget, Markdown), (
                f"Response section should be Markdown after finalize, "
                f"got {type(response_sections[0]._content_widget).__name__}"
            )

    @pytest.mark.asyncio
    async def test_finalize_swaps_response_with_content_change(self):
        """When the last response section's content changes between
        the streaming poll and the finalize call, it should still be
        swapped to Markdown."""
        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            # Step 1: Streaming poll — response is streaming with initial content
            sections_poll = _make_sections("chat-1", [
                {
                    "turn_id": "t1",
                    "messages": [
                        {"content_type": "user", "content": "Hello"},
                        {"content_type": "response", "content": "Hi", "status": "streaming"},
                    ],
                },
            ])
            await display.refresh_from_sections(sections_poll, finalize=False)
            await pilot.pause()

            # Response should be Static during streaming
            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 1
            assert isinstance(response_sections[0]._content_widget, Static), (
                "Response should be Static during streaming"
            )

            # Step 2: Stream ends, content grew, status now complete
            sections_final = _make_sections("chat-1", [
                {
                    "turn_id": "t1",
                    "messages": [
                        {"content_type": "user", "content": "Hello"},
                        {"content_type": "response", "content": "Hi **there**! Updated.", "status": "complete"},
                    ],
                },
            ])
            await display.refresh_from_sections(sections_final, finalize=True)
            await pilot.pause()

            # Response should now be Markdown
            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 1, (
                f"Expected 1 response section, got {len(response_sections)}"
            )
            assert isinstance(response_sections[0]._content_widget, Markdown), (
                f"Response section with changed content should be Markdown "
                f"after finalize, got "
                f"{type(response_sections[0]._content_widget).__name__}"
            )

    @pytest.mark.asyncio
    async def test_finalize_keeps_thinking_as_static(self):
        """Thinking sections should stay Static even after finalize."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "thinking", "content": "Hmm..."},
                    {"content_type": "response", "content": "Hi!"},
                ],
            },
        ])

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            await display.refresh_from_sections(sections, finalize=True)
            await pilot.pause()

            all_sections = list(display.query(Section))
            thinking_sections = [
                s for s in all_sections
                if s.section_id.startswith("thinking-")
            ]
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]

            assert len(thinking_sections) == 1
            assert len(response_sections) == 1

            # Thinking should be Static
            assert isinstance(thinking_sections[0]._content_widget, Static), (
                f"Thinking section should stay Static, got "
                f"{type(thinking_sections[0]._content_widget).__name__}"
            )
            # Response should be Markdown
            assert isinstance(response_sections[0]._content_widget, Markdown), (
                f"Response section should be Markdown, got "
                f"{type(response_sections[0]._content_widget).__name__}"
            )

    @pytest.mark.asyncio
    async def test_streaming_then_finalize_last_section(self):
        """Simulate the full streaming flow: streaming poll → stream ends
        → finalize. The last response section should end up as Markdown."""
        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            # Step 1: Initial streaming poll (response still streaming)
            sections_poll_1 = _make_sections("chat-1", [
                {
                    "turn_id": "t1",
                    "messages": [
                        {"content_type": "user", "content": "Hello"},
                        {"content_type": "response", "content": "Hi", "status": "streaming"},
                    ],
                },
            ])
            await display.refresh_from_sections(sections_poll_1, finalize=False)
            await pilot.pause()

            # Response should be Static during streaming
            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 1
            assert isinstance(response_sections[0]._content_widget, Static), (
                "During streaming, response should be Static"
            )

            # Step 2: Stream ends, content grew, status now complete
            sections_final = _make_sections("chat-1", [
                {
                    "turn_id": "t1",
                    "messages": [
                        {"content_type": "user", "content": "Hello"},
                        {"content_type": "response", "content": "Hi **there**! How are you?", "status": "complete"},
                    ],
                },
            ])
            await display.refresh_from_sections(sections_final, finalize=True)
            await pilot.pause()

            # Response should now be Markdown
            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 1
            assert isinstance(response_sections[0]._content_widget, Markdown), (
                f"After finalize, response should be Markdown, got "
                f"{type(response_sections[0]._content_widget).__name__}"
            )

    @pytest.mark.asyncio
    async def test_multi_section_finalize_all_swapped(self):
        """All response sections should be swapped to Markdown
        after finalize, not just the last one."""
        sections = _make_sections("chat-1", [
            {
                "turn_id": "t1",
                "messages": [
                    {"content_type": "user", "content": "Hello"},
                    {"content_type": "response", "content": "First part."},
                    {"content_type": "response", "content": "Second part."},
                ],
            },
        ])

        async with _ChatApp().run_test() as pilot:
            display = pilot.app.chat_display

            await display.refresh_from_sections(sections, finalize=True)
            await pilot.pause()

            all_sections = list(display.query(Section))
            response_sections = [
                s for s in all_sections
                if s.section_id.startswith("response-")
            ]
            assert len(response_sections) == 2, (
                f"Expected 2 response sections, got {len(response_sections)}"
            )
            for s in response_sections:
                assert isinstance(s._content_widget, Markdown), (
                    f"Response section {s.section_id} should be Markdown, "
                    f"got {type(s._content_widget).__name__}"
                )