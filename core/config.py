"""Layered JSON configuration with dot-path access and diff-based saving.

Config loads multiple JSON files in order and deep-merges them.  Later files
override earlier ones.  When saving, only keys that differ from the baseline
(merge of all files except the last) are written — keeping config files clean.

Modules can register defaults via ``config.defaults({...})`` at import time;
``apply_defaults()`` fills missing keys without touching user-set values.
"""

import json
import os
from copy import deepcopy
from typing import Any


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
    # Dot-path access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value at dotted *key*, or *default* if not found."""
        parts = key.split(".")
        node: Any = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        """Set *value* at dotted *key*, creating intermediate dicts as needed."""
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

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
