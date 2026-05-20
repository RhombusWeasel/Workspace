---
name: database
description: Database connection browser, query editor, and multi-provider SQL interface
---

# Database Plugin

Browse database connections in the sidebar, open query editors in workspace
tabs, and execute SQL with pagination support.  Ships with a SQLite provider;
additional providers can be registered via ``DBProvider`` subclasses.

## Components

| Component | Purpose |
|-----------|---------|
| DB sidebar panel | Tree browser for connections, tables, views, triggers |
| Connection form modal | Add / edit / test database connections |
| Query editor | Split-pane SQL editor with paginated results |
| ConnectionManager | Multi-connection manager backed by config + vault |
| leader chord | None (connections opened from sidebar) |

## Events

- ``db.open_query`` — open a query editor tab for a connection