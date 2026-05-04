---
name: cody_docs
description: Cody core-systems documentation — events, config, vault, and architecture
---

# Cody Documentation

Internal documentation for Cody's core systems.  Use these docs when extending
Cody with new features, skills, or UI components.

## Docs

| System | File | What it covers |
|---|---|---|
| Event system | [`docs/events.md`](docs/events.md) | `CodyEvent`, `@register_handler`, `dispatch`, event naming |
| Config management | [`docs/config.md`](docs/config.md) | Layered JSON, dot-path access, diff-save, registered defaults |
| Password vault | [`docs/vault.md`](docs/vault.md) | Fernet encryption, master + local vaults, `VaultManager` |

## Architecture

See the project [`design_document.md`](../../design_document.md) for the
overall architecture, directory layout, migration plan, and resolved design
decisions.
