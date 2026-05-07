"""Tests for core.config."""

import json
import os
import tempfile

import pytest

from core.config import Config


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _read_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


class TestInit:
    def test_empty_paths_creates_empty_config(self):
        cfg = Config([])
        assert cfg.get("anything") is None

    def test_single_file_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "base.json")
            _write_json(base, {"a": 1})
            cfg = Config([base])
            assert cfg.get("a") == 1


class TestMerge:
    def test_later_file_overrides_earlier(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.json")
            b = os.path.join(tmp, "b.json")
            _write_json(a, {"x": 1, "y": 2})
            _write_json(b, {"y": 99, "z": 3})
            cfg = Config([a, b])
            assert cfg.get("x") == 1
            assert cfg.get("y") == 99
            assert cfg.get("z") == 3

    def test_deep_merge_nested_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.json")
            b = os.path.join(tmp, "b.json")
            _write_json(a, {"db": {"host": "localhost", "port": 5432}})
            _write_json(b, {"db": {"port": 9999}})
            cfg = Config([a, b])
            assert cfg.get("db.host") == "localhost"
            assert cfg.get("db.port") == 9999


class TestGetSet:
    def test_get_returns_none_for_missing_key(self):
        cfg = Config([])
        assert cfg.get("nonexistent") is None

    def test_get_returns_default_for_missing_key(self):
        cfg = Config([])
        assert cfg.get("missing", "fallback") == "fallback"

    def test_get_nested_dot_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cfg.json")
            _write_json(path, {"a": {"b": {"c": 42}}})
            cfg = Config([path])
            assert cfg.get("a.b.c") == 42

    def test_set_creates_nested_structure(self):
        cfg = Config([])
        cfg.set("a.b.c", "hello")
        assert cfg.get("a.b.c") == "hello"

    def test_set_overwrites_existing(self):
        cfg = Config([])
        cfg.set("x", 1)
        cfg.set("x", 2)
        assert cfg.get("x") == 2


class TestDefaults:
    def test_defaults_fill_missing_keys(self):
        cfg = Config([])
        cfg.defaults({"a": 1, "b": 2})
        cfg.apply_defaults()
        assert cfg.get("a") == 1
        assert cfg.get("b") == 2

    def test_defaults_do_not_override_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cfg.json")
            _write_json(path, {"a": 99})
            cfg = Config([path])
            cfg.defaults({"a": 1, "b": 2})
            cfg.apply_defaults()
            assert cfg.get("a") == 99
            assert cfg.get("b") == 2

    def test_defaults_merge_deeply(self):
        cfg = Config([])
        cfg.set("db.host", "prod.example.com")
        cfg.defaults({"db": {"host": "localhost", "port": 5432}})
        cfg.apply_defaults()
        assert cfg.get("db.host") == "prod.example.com"
        assert cfg.get("db.port") == 5432

    def test_multiple_defaults_calls_accumulate(self):
        cfg = Config([])
        cfg.defaults({"a": 1})
        cfg.defaults({"b": 2})
        cfg.apply_defaults()
        assert cfg.get("a") == 1
        assert cfg.get("b") == 2

    def test_later_defaults_override_earlier(self):
        cfg = Config([])
        cfg.defaults({"x": "first"})
        cfg.defaults({"x": "second"})
        cfg.apply_defaults()
        assert cfg.get("x") == "second"


class TestModuleDefaults:
    """Tests for module-level register_defaults() / get_registered_defaults()."""

    def test_register_defaults_empty_by_default(self):
        from core.config import get_registered_defaults, reset_registered_defaults
        reset_registered_defaults()
        assert get_registered_defaults() == {}

    def test_register_defaults_accumulates(self):
        from core.config import (
            get_registered_defaults,
            register_defaults,
            reset_registered_defaults,
        )
        reset_registered_defaults()
        register_defaults({"session": {"provider": "ollama"}})
        register_defaults({"session": {"model": "llama3"}})
        defaults = get_registered_defaults()
        assert defaults["session"]["provider"] == "ollama"
        assert defaults["session"]["model"] == "llama3"

    def test_register_defaults_later_overrides_earlier(self):
        from core.config import (
            get_registered_defaults,
            register_defaults,
            reset_registered_defaults,
        )
        reset_registered_defaults()
        register_defaults({"x": "first"})
        register_defaults({"x": "second"})
        assert get_registered_defaults()["x"] == "second"

    def test_get_registered_defaults_returns_deep_copy(self):
        from core.config import (
            get_registered_defaults,
            register_defaults,
            reset_registered_defaults,
        )
        reset_registered_defaults()
        register_defaults({"a": {"b": 1}})
        copy1 = get_registered_defaults()
        copy2 = get_registered_defaults()
        copy1["a"]["b"] = 999
        assert copy2["a"]["b"] == 1  # second copy unaffected

    def test_reset_registered_defaults_clears_all(self):
        from core.config import (
            get_registered_defaults,
            register_defaults,
            reset_registered_defaults,
        )
        register_defaults({"a": 1})
        reset_registered_defaults()
        assert get_registered_defaults() == {}


class TestSave:
    def test_save_writes_to_last_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.json")
            b = os.path.join(tmp, "b.json")
            _write_json(a, {"x": 1})
            _write_json(b, {"y": 2})

            cfg = Config([a, b])
            cfg.set("z", 3)
            cfg.save()

            saved = _read_json(b)
            assert saved["z"] == 3

    def test_save_only_writes_diff_against_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.json")
            b = os.path.join(tmp, "b.json")
            _write_json(a, {"session": {"provider": "ollama", "model": "llama3"}})
            _write_json(b, {"session": {"provider": "openai"}})

            cfg = Config([a, b])
            cfg.save()

            saved = _read_json(b)
            assert saved == {"session": {"provider": "openai"}}

    def test_save_handles_no_last_path(self):
        cfg = Config([])
        cfg.set("x", 1)
        cfg.save()  # should not raise

    def test_save_writes_only_changed_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.json")
            b = os.path.join(tmp, "b.json")
            _write_json(a, {"unchanged": 1, "changed": "old"})
            _write_json(b, {})  # empty target

            cfg = Config([a, b])
            cfg.set("changed", "new")
            cfg.save()

            saved = _read_json(b)
            assert "unchanged" not in saved
            assert saved["changed"] == "new"
