"""Session persistence — save and restore workspace state across app restarts.

A session captures the pane tree layout, open tabs with their persistent
state, the focused pane, and sidebar visibility.  On startup, if a
session file exists, the workspace is restored to that layout.

Tab types register themselves via :func:`register_tab_type` with a
:class:`TabTypeHandler` that knows how to serialise and deserialise
their state.  This keeps session.py agnostic about any particular tab
type — each skill owns its own (de)serialisation logic.

Session file location: ``{working_directory}/.agents/session.json``
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from core.pane_tree import (
    Pane,
    get_leaves,
    pane_tree_from_dict,
    pane_tree_to_dict,
)

if TYPE_CHECKING:
    from textual.widget import Widget

    from context import AppContext
    from ui.workspace.tabs import TabState

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tab type handler registry
# ---------------------------------------------------------------------------

# Each tab type (chat, terminal, file_editor, welcome) registers a handler
# that knows how to serialise/deserialise its TabState to/from a plain dict.
# The content_factory key is also stored so the session can look up the
# right factory function when restoring.

_TAB_TYPE_REGISTRY: dict[str, "TabTypeHandler"] = {}


@dataclass
class TabTypeHandler:
    """Handler for serialising/deserialising one kind of tab state.

    Attributes:
        tab_type:
            Unique string key for this tab type (e.g. ``"chat"``).
        serialise:
            Extract persistent data from a :class:`TabState` as a
            JSON-serialisable dict.
        deserialise:
            Reconstruct a :class:`TabState` from a dict.  Receives
            the :class:`AppContext` so it can look up DB records, etc.
        content_factory:
            Callable that creates a widget from the restored state.
        make_label:
            Callable that produces a tab label from the restored state.
            If ``None``, the label from the session file is used.
    """

    tab_type: str
    serialise: Callable[[TabState], dict]
    deserialise: Callable[[dict, AppContext], TabState]
    content_factory: Callable[[TabState], Widget | None]
    make_label: Callable[[TabState], str] | None = None


def register_tab_type(handler: TabTypeHandler) -> None:
    """Register a tab type handler for session serialisation."""
    if handler.tab_type in _TAB_TYPE_REGISTRY:
        log.warning("Overriding session handler for tab type %r", handler.tab_type)
    _TAB_TYPE_REGISTRY[handler.tab_type] = handler


def get_tab_type_handler(tab_type: str) -> TabTypeHandler | None:
    """Look up a registered tab type handler by name."""
    return _TAB_TYPE_REGISTRY.get(tab_type)


# ---------------------------------------------------------------------------
# Session data model
# ---------------------------------------------------------------------------

SESSION_VERSION = 1
"""Version of the session file schema.  Incremented when the format changes."""

SESSION_FILENAME = "session.json"
"""Filename for the session file (stored in ``{wd}/.agents/``)."""


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Saves and restores workspace session state.

    The session file is a JSON document at ``{working_directory}/.agents/session.json``
    that captures:

    * Pane tree layout (splits, leaf IDs)
    * Open tabs in each leaf (type, label, persistent state)
    * Which pane has focus
    * Sidebar visibility (left and right)

    Usage::

        mgr = SessionManager(session_path, ctx)

        # On mount — restore if a session exists
        if mgr.has_session:
            mgr.restore(workspace, left_sidebar, right_sidebar)

        # On unmount — save current state
        mgr.save(workspace, left_sidebar, right_sidebar)
    """

    def __init__(self, session_path: str, ctx: AppContext):
        self.session_path = session_path
        self.ctx = ctx

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def has_session(self) -> bool:
        """Whether a session file exists on disk."""
        return os.path.isfile(self.session_path)

    def save(
        self,
        workspace: Any,
        left_sidebar_hidden: bool,
        right_sidebar_hidden: bool,
    ) -> None:
        """Capture current workspace state and write to disk.

        Parameters
        ----------
        workspace:
            The :class:`~ui.workspace.workspace.Workspace` widget.
        left_sidebar_hidden:
            Whether the left sidebar is currently hidden.
        right_sidebar_hidden:
            Whether the right sidebar is currently hidden.
        """
        try:
            data = self._capture(workspace, left_sidebar_hidden, right_sidebar_hidden)
            self._write(data)
            log.debug("Session saved to %s", self.session_path)
        except Exception:
            log.exception("Failed to save session to %s", self.session_path)

    def restore(
        self,
        workspace: Any,
        left_sidebar: Any,
        right_sidebar: Any,
    ) -> bool:
        """Restore workspace state from disk.

        Parameters
        ----------
        workspace:
            The :class:`~ui.workspace.workspace.Workspace` widget.
        left_sidebar:
            The left :class:`~ui.sidebar.sidebar.SidebarContainer`.
        right_sidebar:
            The right :class:`~ui.sidebar.sidebar.SidebarContainer`.

        Returns:
            ``True`` if the session was successfully restored,
            ``False`` if no session file exists or restoration failed.
        """
        if not self.has_session:
            return False

        try:
            data = self._read()
            self._apply(workspace, left_sidebar, right_sidebar, data)
            log.info("Session restored from %s", self.session_path)
            return True
        except Exception:
            log.exception("Failed to restore session from %s", self.session_path)
            return False

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _capture(
        self,
        workspace: Any,
        left_sidebar_hidden: bool,
        right_sidebar_hidden: bool,
    ) -> dict:
        """Build the session data dict from the current workspace state."""
        from ui.workspace.tabs import WorkspaceTabs

        # Pane tree structure
        tree_dict = pane_tree_to_dict(workspace.tree)

        # Focused pane
        focused_id = workspace.focused_id

        # Tab state for each leaf — use the workspace's own save mechanism
        # which already knows how to walk all panes and collect tab state.
        leaf_ids = [l.id for l in get_leaves(workspace.tree)]

        saved_states = workspace._save_pane_tab_states()
        log.debug("_capture: saved_states keys=%s, tabs_per_pane=%s",
            list(saved_states.keys()),
            {k: len(v.tabs) for k, v in saved_states.items()})

        tabs_by_pane: dict[str, list[dict]] = {}
        for leaf_id in leaf_ids:
            if leaf_id not in saved_states:
                tabs_by_pane[leaf_id] = []
                continue

            saved = saved_states[leaf_id]
            tabs_by_pane[leaf_id] = self._serialise_saved_tabs(saved)

        return {
            "version": SESSION_VERSION,
            "focused_pane_id": focused_id,
            "sidebar": {
                "left_hidden": left_sidebar_hidden,
                "right_hidden": right_sidebar_hidden,
            },
            "pane_tree": tree_dict,
            "tabs_by_pane": tabs_by_pane,
        }

    def _serialise_saved_tabs(self, saved_state: Any) -> list[dict]:
        """Serialise a SavedTabState to a list of JSON-safe dicts."""
        result: list[dict] = []
        for saved_tab in saved_state.tabs:
            state = saved_tab.state
            if state is None:
                continue

            # Look up handler by TabState subclass name
            handler = self._find_handler(state)
            if handler is None:
                log.warning("No session handler for tab state type %r, skipping", type(state).__name__)
                continue

            try:
                tab_data = handler.serialise(state)
            except Exception:
                log.exception("Failed to serialise tab state of type %r", type(state).__name__)
                continue

            log.debug("_serialise_saved_tabs: serialised tab %r (type=%s)", saved_tab.id, handler.tab_type)
            result.append({
                "tab_type": handler.tab_type,
                "tab_data": tab_data,
                "label": saved_tab.label,
                "tab_id": saved_tab.id,
            })

        return result

    def _serialise_tabs(self, tabs_widget: Any) -> list[dict]:
        """Serialise all tabs in a WorkspaceTabs widget."""
        from ui.workspace.tabs import WorkspaceTabs

        saved = tabs_widget.save_state()
        log.debug("_serialise_tabs: %d tabs saved from WorkspaceTabs", len(saved.tabs))
        return self._serialise_saved_tabs(saved)

    def _find_handler(self, state: TabState) -> TabTypeHandler | None:
        """Look up a TabTypeHandler for a TabState instance.

        Converts the state's class name to a snake_case tab type key.
        E.g. ``ChatTabState`` → ``"chat"``, ``TerminalState`` → ``"terminal"``,
        ``FileEditorState`` → ``"file_editor"``, ``TabState`` → ``""`` (base class).
        """
        state_class_name = type(state).__name__
        # ChatTabState → "chat", TerminalState → "terminal", FileEditorState → "file_editor"
        # Strip "Tab" and "State" suffixes, then convert CamelCase to snake_case
        name = state_class_name
        if name.endswith("State"):
            name = name[: -len("State")]
        if name.endswith("Tab"):
            name = name[: -len("Tab")]
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
        return _TAB_TYPE_REGISTRY.get(snake)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _apply(
        self,
        workspace: Any,
        left_sidebar: Any,
        right_sidebar: Any,
        data: dict,
    ) -> None:
        """Apply session data to the workspace."""
        # Restore pane tree
        tree_dict = data.get("pane_tree")
        if tree_dict is None:
            raise ValueError("Session data missing 'pane_tree'")

        new_tree = pane_tree_from_dict(tree_dict)

        # Restore sidebar visibility
        sidebar_data = data.get("sidebar", {})
        left_hidden = sidebar_data.get("left_hidden", False)
        right_hidden = sidebar_data.get("right_hidden", True)

        if left_hidden and not left_sidebar.is_hidden:
            left_sidebar.hide()
        elif not left_hidden and left_sidebar.is_hidden:
            left_sidebar.show()

        if right_hidden and not right_sidebar.is_hidden:
            right_sidebar.hide()
        elif not right_hidden and right_sidebar.is_hidden:
            right_sidebar.show()

        # Restore focused pane
        focused_id = data.get("focused_pane_id")
        if focused_id is None:
            focused_id = get_leaves(new_tree)[0].id if get_leaves(new_tree) else "main"

        # We need to update the workspace tree and recompose, then restore tabs.
        # This is done in two phases:
        #   1. Set the tree and focused ID, then recompose the DOM
        #   2. After recomposition, populate each leaf's WorkspaceTabs

        # Phase 1: Update the tree and trigger recomposition
        workspace._tree = new_tree
        workspace.focused_id = focused_id

        # We'll need to defer tab restoration until after recomposition
        tabs_by_pane = data.get("tabs_by_pane", {})

        # Schedule the recomposition and tab restoration
        async def _do_restore() -> None:
            # Recompose the workspace to build the DOM for the new tree
            await workspace.recompose()

            # Phase 2: Restore tabs into each leaf's WorkspaceTabs
            from ui.workspace.tabs import WorkspaceTabs

            leaves = get_leaves(workspace._tree)

            for leaf in leaves:
                pane_id = leaf.id
                tab_list = tabs_by_pane.get(pane_id, [])
                if not tab_list:
                    continue

                try:
                    container = workspace.app.query_one(f"#pane-{pane_id}")
                    tabs_widget = container.query_one(WorkspaceTabs)
                except Exception:
                    log.warning("Could not find WorkspaceTabs for pane %s during session restore", pane_id)
                    continue

                # Open all tabs in a batch so that only the active tab's
                # content is mounted.  Without batching, each open_tab call
                # triggers _refresh(), which mounts that tab's content
                # asynchronously — if the next open_tab runs before the
                # mount completes, _refresh_content can't hide the previous
                # tab (is_mounted is still False), so both content widgets
                # end up visible at the same time.
                tabs_widget.begin_batch()
                try:
                    for tab_info in tab_list:
                        tab_type = tab_info["tab_type"]
                        tab_data = tab_info.get("tab_data", {})
                        label = tab_info.get("label", "")
                        tab_id = tab_info.get("tab_id", "")

                        handler = get_tab_type_handler(tab_type)
                        if handler is None:
                            log.warning("No handler for tab type %r during restore, skipping", tab_type)
                            continue

                        try:
                            state = handler.deserialise(tab_data, self.ctx)
                        except Exception:
                            log.exception("Failed to deserialise tab of type %r", tab_type)
                            continue

                        # Skip tabs where deserialise returns None (e.g. file gone)
                        if state is None:
                            log.info("Skipping tab of type %r (deserialiser returned None)", tab_type)
                            continue

                        # Determine label
                        if handler.make_label is not None:
                            try:
                                label = handler.make_label(state)
                            except Exception:
                                pass  # Fall back to saved label

                        content_factory = handler.content_factory

                        tabs_widget.open_tab(
                            tab_id,
                            label,
                            state=state,
                            content_factory=content_factory,
                        )
                finally:
                    tabs_widget.end_batch()

            # Update focus styles
            workspace._update_focus_styles()

        workspace.run_worker(_do_restore())

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _write(self, data: dict) -> None:
        """Write session data to disk as JSON."""
        dirname = os.path.dirname(self.session_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(self.session_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _read(self) -> dict:
        """Read session data from disk."""
        with open(self.session_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        version = data.get("version")
        if version != SESSION_VERSION:
            raise ValueError(
                f"Session file version {version!r} does not match "
                f"expected version {SESSION_VERSION!r}"
            )

        return data