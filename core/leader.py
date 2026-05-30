"""Leader registry — chord-tree for the ``Ctrl+Space`` leader menu.

The leader menu is a keyboard-driven modal that lets users chain key
presses to reach nested actions.  This module defines the in-memory
tree, functions to register chords, and a singleton ``LeaderRegistry``
instance.

Chords are registered as paths (e.g. ``["w", "s", "h"]``) that create
intermediate ``LeaderNode`` nodes automatically.  Conflicts (action where
a submenu exists, or vice versa) are caught at registration time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class LeaderNode:
    """A single node in the chord tree.

    Parameters
    ----------
    label:
        Display string shown in the UI.  Empty for auto-created
        intermediate nodes that haven't been explicitly labelled.
    children:
        Map of single-char key → child node.
    handler:
        Callable invoked when the user completes this chord.  ``None``
        for intermediate (submenu) nodes.
    is_submenu:
        ``True`` when this node was explicitly created via
        ``register_submenu()`` and should not be converted to a
        leaf action.
    event_type:
        If set, the leader overlay posts a :class:`WorkspaceEvent`
        of this type when the leaf is reached (bypassing
        ``handler``).
    """

    label: str = ""
    children: dict[str, LeaderNode] = field(default_factory=dict)
    handler: Callable[[], Any] | None = None
    is_submenu: bool = False
    event_type: str | None = None


# ---------------------------------------------------------------------------
# LeaderRegistry
# ---------------------------------------------------------------------------


class LeaderRegistry:
    """In-memory tree of leader chords.

    Use ``register_action()`` and ``register_submenu()`` to build the
    tree; ``find_node()`` and ``get_root()`` to query it.
    """

    def __init__(self) -> None:
        self._root = LeaderNode()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_action(
        self,
        keys: list[str],
        label: str,
        handler: Callable[[], Any] | None = None,
        labels: dict[str, str] | None = None,
        event_type: str | None = None,
    ) -> None:
        """Register a chord action at a leaf path.

        Parameters
        ----------
        keys:
            Sequence of single-character keys from the root (e.g.
            ``["w", "s", "h"]`` for ``Ctrl+Space w s h``).
        label:
            Display string for the terminal (leaf) node.
        handler:
            Callable invoked when the user completes this chord.
        labels:
            Optional human-readable labels for intermediate nodes
            created along the path.  Keys not in this dict get an
            empty label.
        event_type:
            If set, the leader overlay posts a :class:`WorkspaceEvent`
            of this type when the leaf is reached (instead of
            calling ``handler``).
        """
        labels = labels or {}
        node = self._root
        for i, key in enumerate(keys):
            is_last = (i == len(keys) - 1)
            if key in node.children:
                child = node.children[key]
                if is_last:
                    # We're adding a leaf — it must not already have a
                    # handler, children, or be an explicit submenu.
                    if child.handler is not None:
                        raise ValueError(
                            f"Key path {keys!r} already has an action "
                            f"registered at '{key}'."
                        )
                    if child.children:
                        raise ValueError(
                            f"Key path {keys!r} conflicts with existing "
                            f"submenu at '{key}' (node has children)."
                        )
                    if child.is_submenu:
                        raise ValueError(
                            f"Key path {keys!r} conflicts: '{key}' is "
                            f"already a submenu and cannot be an action."
                        )
                    child.label = label
                    child.handler = handler
                    child.event_type = event_type
                else:
                    # Intermediate — must not already be a leaf action.
                    if child.handler is not None:
                        raise ValueError(
                            f"Key path {keys!r} conflicts with existing "
                            f"action at '{key}'."
                        )
                    # Optionally update the label.
                    if key in labels:
                        child.label = labels[key]
            else:
                if is_last:
                    node.children[key] = LeaderNode(
                        label=label, handler=handler, event_type=event_type
                    )
                else:
                    node.children[key] = LeaderNode(
                        label=labels.get(key, "")
                    )
            node = node.children[key]

    def register_submenu(self, keys: list[str], label: str) -> None:
        """Ensure a labelled submenu node exists at *keys*.

        If the node already exists and doesn't have a handler, its label
        is updated and ``is_submenu`` is set.  If the node is already a
        leaf action, ``ValueError`` is raised.
        """
        node = self._root
        for i, key in enumerate(keys):
            if key in node.children:
                child = node.children[key]
                # Check for conflict: we can't label an action as a submenu.
                if child.handler is not None:
                    raise ValueError(
                        f"Key path {keys!r} conflicts with existing "
                        f"action at '{key}'."
                    )
                # Update label if we're at the target node.
                if i == len(keys) - 1:
                    child.label = label
                    child.is_submenu = True
            else:
                # Last key gets the label; intermediates get empty.
                child_label = label if i == len(keys) - 1 else ""
                node.children[key] = LeaderNode(
                    label=child_label,
                    is_submenu=(i == len(keys) - 1),
                )

            node = node.children[key]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_root(self) -> LeaderNode:
        """Return the root node of the chord tree."""
        return self._root

    def find_node(self, keys: list[str]) -> LeaderNode | None:
        """Walk *keys* from the root; return the resulting node or ``None``."""
        node = self._root
        for key in keys:
            if key not in node.children:
                return None
            node = node.children[key]
        return node

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all chords (test isolation)."""
        self._root = LeaderNode()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

leader = LeaderRegistry()


# ---------------------------------------------------------------------------
# Convenience functions that operate on the singleton
# ---------------------------------------------------------------------------


def register_action(
    keys: list[str],
    label: str,
    handler: Callable[[], Any] | None = None,
    labels: dict[str, str] | None = None,
    event_type: str | None = None,
) -> None:
    """Register a chord action on the module-level singleton."""
    leader.register_action(keys, label, handler, labels, event_type)


def register_submenu(keys: list[str], label: str) -> None:
    """Register a submenu label on the module-level singleton."""
    leader.register_submenu(keys, label)


def find_node(keys: list[str]) -> LeaderNode | None:
    """Walk *keys* on the singleton and return the node or ``None``."""
    return leader.find_node(keys)


def reset_leader() -> None:
    """Reset the singleton's chord tree."""
    leader.reset()
