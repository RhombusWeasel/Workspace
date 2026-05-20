"""Layered JSON configuration with dot-path access and diff-based saving.

Config loads multiple JSON files in order and deep-merges them.  Later files
override earlier ones.  When saving, only keys that differ from the baseline
(merge of all files except the last) are written — keeping config files clean.

Modules can register defaults via ``config.defaults({...})`` at import time;
``apply_defaults()`` fills missing keys without touching user-set values.
"""

import json
import os
import re
from copy import deepcopy
from typing import Any

# ---------------------------------------------------------------------------
# Module-level defaults registry
# ---------------------------------------------------------------------------

_registered_defaults: dict[str, Any] = {}


def register_defaults(d: dict) -> None:
    """Register default config values at the module level.

    Modules call this at import time to declare their config defaults.
    Accumulated defaults are applied during bootstrap via
    ``config.defaults()`` + ``config.apply_defaults()``.
    """
    _deep_merge(_registered_defaults, d)


def get_registered_defaults() -> dict:
    """Return a deep copy of all accumulated module-level defaults."""
    return deepcopy(_registered_defaults)


def reset_registered_defaults() -> None:
    """Clear all accumulated module-level defaults (for test isolation)."""
    _registered_defaults.clear()


def _deep_merge(dst: dict, src: dict) -> dict:
    """Merge *src* into *dst* in-place.  *src* wins on conflict.

    Both dict values at the same key are recursively merged.
    """
    for key, value in src.items():
        if key in dst and isinstance(dst[key], dict) and isinstance(value, dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = deepcopy(value)
    return dst


def _deep_merge_missing(dst: dict, src: dict) -> dict:
    """Like _deep_merge but only fills keys not already present in *dst*."""
    for key, value in src.items():
        if key not in dst:
            dst[key] = deepcopy(value)
        elif isinstance(dst[key], dict) and isinstance(value, dict):
            _deep_merge_missing(dst[key], value)
    return dst


def _diff(merged: dict, baseline: dict) -> dict:
    """Return a dict containing only keys where *merged* differs from *baseline*."""
    result: dict[str, Any] = {}
    for key, value in merged.items():
        if key not in baseline:
            result[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(baseline[key], dict):
            sub = _diff(value, baseline[key])
            if sub:
                result[key] = sub
        elif value != baseline[key]:
            result[key] = deepcopy(value)
    return result


class Config:
    """Layered JSON config with dot-path access and diff-based saving."""

    def __init__(self, paths: list[str]) -> None:
        self._paths = list(paths)
        self._data: dict[str, Any] = {}
        self._baseline: dict[str, Any] = {}
        self._defaults: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load and merge all JSON files.  Baseline = merge of all except last."""
        if not self._paths:
            return

        for i, path in enumerate(self._paths):
            if not os.path.isfile(path):
                continue
            with open(path) as f:
                try:
                    blob = json.load(f)
                except json.JSONDecodeError:
                    continue
                if not isinstance(blob, dict):
                    continue
                _deep_merge(self._data, blob)

            if i < len(self._paths) - 1:
                _deep_merge(self._baseline, blob)

    # ------------------------------------------------------------------
    # Path parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_path(key: str) -> list[tuple[str, int | None]]:
        """Parse a dot-path with optional ``[N]`` list indices.

        Returns a list of ``(segment, index)`` tuples:
        - ``("connections", None)`` — dict key
        - ``("connections", 0)`` — dict key + list index

        Examples::

            _parse_path("db.connections")
            # → [("db", None), ("connections", None)]

            _parse_path("db.connections[0].name")
            # → [("db", None), ("connections", 0), ("name", None)]
        """
        segments: list[tuple[str, int | None]] = []
        for part in key.split("."):
            m = re.match(r"^(.+?)\[(\d+)\]$", part)
            if m:
                segments.append((m.group(1), int(m.group(2))))
            else:
                segments.append((part, None))
        return segments

    # ------------------------------------------------------------------
    # Dot-path access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value at dotted *key*, or *default* if not found.

        Supports ``[N]`` notation for list indexing, e.g.
        ``"db.connections[0].name"``.
        """
        segments = self._parse_path(key)
        node: Any = self._data
        for seg_key, index in segments:
            # Navigate into dict by key
            if not isinstance(node, dict) or seg_key not in node:
                return default
            node = node[seg_key]
            # If an index is present, navigate into the list
            if index is not None:
                if not isinstance(node, list) or index >= len(node):
                    return default
                node = node[index]
        return node

    def set(self, key: str, value: Any) -> None:
        """Set *value* at dotted *key*, creating intermediate dicts as needed.

        Supports ``[N]`` notation for list indexing.
        The list and all intermediate dicts must already exist —
        this method will not create new list entries.
        For dict segments that don't exist, they are created automatically.
        """
        segments = self._parse_path(key)
        node: Any = self._data
        for seg_key, index in segments[:-1]:
            # Create missing intermediate dicts, but never overwrite
            # existing values (e.g. a list) with an empty dict.
            if seg_key not in node:
                node[seg_key] = {}
            node = node[seg_key]
            if index is not None:
                if not isinstance(node, list) or index >= len(node):
                    raise IndexError(
                        f"List index {index} out of range for "
                        f"path segment '{seg_key}[{index}]'"
                    )
                node = node[index]
        # Set the final value
        last_key, last_index = segments[-1]
        if last_index is not None:
            # Setting into a list — the list must already exist
            if last_key not in node:
                node[last_key] = []
            target = node[last_key]
            if not isinstance(target, list) or last_index >= len(target):
                raise IndexError(
                    f"List index {last_index} out of range for "
                    f"path segment '{last_key}[{last_index}]'"
                )
            target[last_index] = value
        else:
            node[last_key] = value

    # ------------------------------------------------------------------
    # Registered defaults
    # ------------------------------------------------------------------

    def defaults(self, d: dict) -> None:
        """Register default values (accumulated across calls).

        Call :meth:`apply_defaults` to fill them into the config.
        """
        _deep_merge(self._defaults, d)

    def apply_defaults(self) -> None:
        """Fill missing keys from accumulated defaults."""
        _deep_merge_missing(self._data, self._defaults)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Write changed keys (vs baseline) to the last config file.

        Does nothing if there is no writable path.
        """
        if not self._paths:
            return
        target = self._paths[-1]
        changed = _diff(self._data, self._baseline)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            json.dump(changed, f, indent=2)
