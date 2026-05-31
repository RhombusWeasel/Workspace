"""Tests for the provider registry — ProviderRegistry, lazy creation, type registration."""

import sys
import types
import pytest
from core.config import Config
from core.providers.registry import ProviderRegistry

# The ollama library may not be installed in test environments.
# Mock it if missing so OllamaProvider can be imported.
if "ollama" not in sys.modules:
    _mock_ollama = types.ModuleType("ollama")
    _mock_ollama.AsyncClient = type("AsyncClient", (), {})
    sys.modules["ollama"] = _mock_ollama

from core.providers.ollama import OllamaProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config(tmp_path):
    """Create a Config with provider instance definitions."""
    from core.config import register_defaults, get_registered_defaults

    cfg = Config([])
    # Set up provider instances directly
    cfg._data = {
        "providers": {
            "instances": {
                "ollama-local": {
                    "type": "ollama",
                    "base_url": "http://localhost:11434",
                    "model": "deepseek-r1:14b",
                },
                "ollama-cloud": {
                    "type": "ollama",
                    "model": "deepseek-v4-pro:cloud",
                },
            },
        },
        "session": {
            "default_provider": "ollama-local",
            "model": "fallback-model",
        },
        "ollama": {
            "base_url": "http://localhost:11434",
        },
    }
    return cfg


@pytest.fixture
def registry(config):
    """Create a ProviderRegistry with the ollama type registered."""
    reg = ProviderRegistry(config=config, vault=None)
    reg.register_type("ollama", OllamaProvider)
    return reg


# ---------------------------------------------------------------------------
# Type registration
# ---------------------------------------------------------------------------


class TestTypeRegistration:
    def test_register_type(self, registry):
        assert "ollama" in registry.list_types()

    def test_list_types_sorted(self, registry):
        registry.register_type("zed", type("ZedProvider", (), {}))
        assert registry.list_types() == ["ollama", "zed"]

    def test_list_types_empty(self, tmp_path):
        cfg = Config([])
        cfg._data = {}
        reg = ProviderRegistry(config=cfg, vault=None)
        assert reg.list_types() == []


# ---------------------------------------------------------------------------
# Instance access
# ---------------------------------------------------------------------------


class TestInstanceAccess:
    def test_get_creates_instance_lazily(self, registry):
        provider = registry.get("ollama-local")
        assert isinstance(provider, OllamaProvider)
        assert provider.model == "deepseek-r1:14b"
        assert provider.base_url == "http://localhost:11434"

    def test_get_caches_instance(self, registry):
        p1 = registry.get("ollama-local")
        p2 = registry.get("ollama-local")
        assert p1 is p2  # same object

    def test_get_cloud_instance(self, registry):
        provider = registry.get("ollama-cloud")
        assert provider.model == "deepseek-v4-pro:cloud"

    def test_get_default(self, registry):
        provider = registry.get_default()
        assert isinstance(provider, OllamaProvider)
        assert provider.model == "deepseek-r1:14b"

    def test_get_nonexistent_raises(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.get("nonexistent")

    def test_get_unknown_type_raises(self, config):
        """Config references a type that hasn't been registered."""
        config._data["providers"]["instances"]["bad"] = {"type": "unknown_type"}
        reg = ProviderRegistry(config=config, vault=None)
        with pytest.raises(ValueError, match="Unknown provider type"):
            reg.get("bad")


# ---------------------------------------------------------------------------
# Instance listing
# ---------------------------------------------------------------------------


class TestInstanceListing:
    def test_list_instances(self, registry):
        instances = registry.list_instances()
        assert "ollama-local" in instances
        assert "ollama-cloud" in instances

    def test_has_instance(self, registry):
        assert registry.has_instance("ollama-local") is True
        assert registry.has_instance("nonexistent") is False

    def test_list_instances_empty(self, tmp_path):
        cfg = Config([])
        cfg._data = {}
        reg = ProviderRegistry(config=cfg, vault=None)
        assert reg.list_instances() == []


# ---------------------------------------------------------------------------
# Reset (testing helper)
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_caches(self, registry):
        registry.get("ollama-local")
        registry._reset()
        # After reset, the ollama type is gone too
        assert registry.list_types() == []
        # Re-register and try again
        registry.register_type("ollama", OllamaProvider)
        # This is a new instance (not the same object)
        p = registry.get("ollama-local")
        assert isinstance(p, OllamaProvider)

    def test_provider_kwargs_passed_through(self, registry):
        """Extra keys from config (model, base_url) are passed as kwargs."""
        provider = registry.get("ollama-local")
        assert provider.base_url == "http://localhost:11434"
        assert provider.model == "deepseek-r1:14b"

    def test_provider_uses_global_config_fallback(self, config):
        """When instance config omits base_url, provider falls back to global config."""
        # Remove base_url from instance config
        config._data["providers"]["instances"]["minimal"] = {
            "type": "ollama",
        }
        reg = ProviderRegistry(config=config, vault=None)
        reg.register_type("ollama", OllamaProvider)
        provider = reg.get("minimal")
        # Should fall back to config.ollama.base_url
        assert provider.base_url == "http://localhost:11434"