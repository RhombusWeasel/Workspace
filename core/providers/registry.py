"""Provider registry — manages named LLM provider instances.

Provider instances are defined in config under ``providers.instances``
as a mapping of name → config dict.  Each config dict requires a ``type``
key (e.g. ``"ollama"``, ``"openai"``) plus provider-specific settings
like ``base_url`` and ``model``.

The registry lazily creates provider instances on first access and
caches them for the session.  Provider *types* are registered via
:meth:`register_type` — typically called at import time by each
provider module (e.g. ``ollama.py`` registers ``"ollama"``).

Example config::

    {
      "providers": {
        "instances": {
          "ollama-local": {
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "model": "deepseek-r1:14b"
          },
          "ollama-cloud": {
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "model": "deepseek-v4-pro:cloud"
          },
          "openai-main": {
            "type": "openai",
            "model": "gpt-4o"
          }
        }
      },
      "session": {
        "default_provider": "ollama-cloud"
      }
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.config import register_defaults

if TYPE_CHECKING:
    from core.config import Config
    from core.providers.base import BaseProvider
    from core.vault import VaultManager

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

register_defaults(
    {
        "providers": {
            "instances": {
                "ollama": {
                    "type": "ollama",
                },
            },
        },
        "session": {
            "default_provider": "ollama",
            "max_tool_calls": 10,
            "yolo_mode": False,
        },
    }
)


# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


class ProviderRegistry:
    """Registry of named LLM provider instances.

    Provider instances are created lazily from config on first access
    and cached for the session lifetime.  Provider *types* (the mapping
    of type name → class) are registered explicitly via
    :meth:`register_type`.

    Parameters
    ----------
    config:
        The global :class:`~core.config.Config` instance.
    vault:
        The :class:`~core.vault.VaultManager` for API key resolution
        and message redaction.
    """

    def __init__(self, config: Config, vault: VaultManager | None = None) -> None:
        self._config = config
        self._vault = vault
        self._types: dict[str, type] = {}
        self._instances: dict[str, BaseProvider] = {}

    # ------------------------------------------------------------------
    # Type registration
    # ------------------------------------------------------------------

    def register_type(self, type_name: str, cls: type) -> None:
        """Register a provider class for a type name.

        Called at import time by provider modules so that the registry
        can instantiate the right class when config references a type.

        Example::

            registry.register_type("ollama", OllamaProvider)
        """
        self._types[type_name] = cls

    def list_types(self) -> list[str]:
        """Return sorted list of registered provider type names."""
        return sorted(self._types.keys())

    # ------------------------------------------------------------------
    # Instance access
    # ------------------------------------------------------------------

    def get(self, name: str) -> BaseProvider:
        """Return a named provider instance, creating it lazily if needed.

        Raises ``ValueError`` if the instance name is not defined in
        config or the provider type is unknown.
        """
        if name in self._instances:
            return self._instances[name]
        return self._create(name)

    def get_default(self) -> BaseProvider:
        """Return the default provider instance.

        Reads ``session.default_provider`` from config to determine
        the instance name.  Falls back to ``"ollama"`` if not set.
        """
        name = self._config.get("session.default_provider", "ollama")
        return self.get(name)

    def list_instances(self) -> list[str]:
        """Return sorted list of configured provider instance names."""
        instances = self._config.get("providers.instances", {})
        return sorted(instances.keys()) if isinstance(instances, dict) else []

    def has_instance(self, name: str) -> bool:
        """Return ``True`` if a provider instance with *name* is configured."""
        instances = self._config.get("providers.instances", {})
        return name in instances if isinstance(instances, dict) else False

    # ------------------------------------------------------------------
    # Instance creation
    # ------------------------------------------------------------------

    def _create(self, name: str) -> BaseProvider:
        """Create a provider instance from config.

        Reads the instance definition from ``providers.instances.<name>``,
        looks up the ``type`` to find the registered class, and constructs
        it with the global config, vault, and any extra keys from the
        instance definition as keyword arguments (excluding ``type``).

        The provider class receives:
        - ``config`` — the global Config instance
        - ``vault`` — the VaultManager
        - Any remaining keys from the instance definition as kwargs
        """
        instances = self._config.get("providers.instances", {})
        if not isinstance(instances, dict) or name not in instances:
            raise ValueError(
                f"Provider instance '{name}' not found in config. "
                f"Available instances: {self.list_instances()}"
            )

        instance_config = instances[name]
        if not isinstance(instance_config, dict):
            raise ValueError(
                f"Provider instance '{name}' config must be a dict, "
                f"got {type(instance_config).__name__}"
            )

        type_name = instance_config.get("type", "ollama")
        if type_name not in self._types:
            available = ", ".join(self.list_types()) or "(none registered)"
            raise ValueError(
                f"Unknown provider type '{type_name}' for instance '{name}'. "
                f"Registered types: {available}"
            )

        cls = self._types[type_name]

        # Build kwargs from the instance definition, excluding 'type'.
        # The provider class receives config= and vault= explicitly,
        # plus any extra keys (model, base_url, etc.) as overrides.
        extra_kwargs = {
            k: v for k, v in instance_config.items() if k != "type"
        }

        try:
            instance = cls(config=self._config, vault=self._vault, **extra_kwargs)
        except TypeError as exc:
            raise ValueError(
                f"Failed to create provider instance '{name}' "
                f"(type={type_name!r}): {exc}"
            ) from exc

        self._instances[name] = instance
        return instance

    # ------------------------------------------------------------------
    # Testing helpers
    # ------------------------------------------------------------------

    def _reset(self) -> None:
        """Clear all cached instances and registered types.

        Used in test fixtures to ensure isolation between test runs.
        """
        self._instances.clear()
        self._types.clear()