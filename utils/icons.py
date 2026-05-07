"""Icon registry — Nerd Font icons for file types, folders, and actions.

All icon strings live here so any visual change is made in one place.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Action icons — used in RowButton labels, tab close buttons, etc.
# ---------------------------------------------------------------------------

FOLDER = "\uf07b"        # 󰉋  folder
FILE = "\uf15b"          # 󰅛  generic file
EDIT = "\uf040"          # 󰦊  pencil / edit
DELETE = "\uf2ed"        # 󰆴  trash / delete
RENAME = "\uf44d"        # 󰑕  rename / edit-alt
ADD_FILE = "\uf15b"     # 󰝠  file-plus (using generic file + text)
ADD_DIR = "\uf07b"       # 󰝔  folder-plus
REFRESH = "\uf2f1"        # 󰑐  refresh / sync
CLOSE = "\uf00d"          # 󰅖  times / close
COPY = "\uf0c5"           # 󰆏  copy
COLLAPSE = "\uf078"       # 󰅀  chevron-down
EXPAND = "\uf054"         # 󰅁  chevron-right
SEARCH = "\uf002"         # 󰍉  search / magnifying glass

# ---------------------------------------------------------------------------
# Folder icons
# ---------------------------------------------------------------------------

FOLDER_OPEN = "\uf07c"    # 󰉌  folder-open
FOLDER_ICON = "\uf07b"    # 󰉋  same as FOLDER, used in tree labels

# ---------------------------------------------------------------------------
# File type icons — extension → Nerd Font glyph
# ---------------------------------------------------------------------------

_FILE_ICONS: dict[str, str] = {
    # Programming languages
    ".py": "\ue73c",       # 󰌠  Python
    ".js": "\ue74e",       # 󰌞  JavaScript
    ".ts": "\ue628",       # 󰛦  TypeScript
    ".jsx": "\ue7ba",      # 󰌺  React JSX
    ".tsx": "\ue7ba",      # 󰌺  React TSX
    ".rs": "\ue7a8",       # 󰚨  Rust
    ".go": "\ue627",        # 󰛧  Go
    ".rb": "\ue791",        # 󰞑  Ruby
    ".java": "\ue738",      # 󰌸  Java
    ".kt": "\ue634",        # 󰛴  Kotlin
    ".swift": "\ue755",     # 󰝕  Swift
    ".c": "\ue61e",         # 󰘞  C
    ".cpp": "\ue61d",       # 󰘝  C++
    ".h": "\uf0fd",         # 󰂽  header file
    ".cs": "\ue627",        # 󰛧  C# (using .NET icon)
    ".php": "\ue73d",       # 󰌽  PHP
    ".lua": "\ue620",       # 󰘠  Lua
    ".r": "\uf25d",         # 󰉝  R
    ".scala": "\ue737",     # 󰌷  Scala

    # Web / markup
    ".html": "\uf13b",      # 󰄻  HTML5
    ".css": "\uf13c",       # 󰄼  CSS3
    ".scss": "\uf13c",      # 󰄼  SASS/SCSS
    ".less": "\uf13c",      # 󰄼  LESS
    ".json": "\uf025",      # 󰀥  JSON
    ".xml": "\uf025",       # 󰀥  XML
    ".yaml": "\uf025",      # 󰀥  YAML
    ".yml": "\uf025",       # 󰀥  YAML
    ".toml": "\uf025",      # 󰀥  TOML
    ".ini": "\uf025",       # 󰀥  INI
    ".cfg": "\uf025",       # 󰀥  Config
    ".conf": "\uf025",      # 󰀥  Config

    # Documentation
    ".md": "\uf48a",        # 󰍊  Markdown
    ".rst": "\uf48a",       # 󰍊  reStructuredText
    ".txt": "\uf48a",       # 󰍊  Text
    ".pdf": "\uf1c1",       # 󰜁  PDF

    # Shell / scripting
    ".sh": "\ue795",        # 󰞕  Shell
    ".bash": "\ue795",      # 󰞕  Bash
    ".zsh": "\ue795",       # 󰞕  Zsh
    ".fish": "\ue795",      # 󰞕  Fish
    ".ps1": "\uf025",       # 󰀥  PowerShell

    # Data / database
    ".sql": "\uf1c0",       # 󰜀  Database
    ".db": "\uf1c0",        # 󰜀  SQLite
    ".csv": "\uf1c3",       # 󰜃  Table/CSV
    ".xlsx": "\uf1c3",      # 󰜃  Excel

    # Image files
    ".png": "\uf1c5",       # 󰜅  Image
    ".jpg": "\uf1c5",       # 󰜅  Image
    ".jpeg": "\uf1c5",      # 󰜅  Image
    ".gif": "\uf1c5",       # 󰜅  Image
    ".svg": "\uf1c5",       # 󰜅  Image
    ".ico": "\uf1c5",       # 󰜅  Image
    ".webp": "\uf1c5",      # 󰜅  Image

    # Build / config files (special names handled separately)
    ".lock": "\uf023",      # 󰀣  Lock file
    ".log": "\uf18d",       # 󰆍  Log

    # Binary / archive
    ".zip": "\uf410",       # 󰀐  Archive
    ".tar": "\uf410",       # 󰀐  Archive
    ".gz": "\uf410",        # 󰀐  Archive
    ".exe": "\uf2d7",       # 󰋗  Executable
    ".dll": "\uf2d7",       # 󰋗  Binary
    ".so": "\uf2d7",        # 󰋗  Shared library
}

# Special filenames that get unique icons (checked before extension)
_SPECIAL_FILE_ICONS: dict[str, str] = {
    ".gitignore": "\uf1d3",       # 󰜓  Git
    ".gitmodules": "\uf1d3",      # 󰜓  Git
    ".env": "\uf462",             # 󰍢  Environment
    ".env.local": "\uf462",      # 󰍢  Environment
    ".env.production": "\uf462", # 󰍢  Environment
    ".env.development": "\uf462", # 󰍢  Environment
    "Dockerfile": "\uf308",       # 󰌈  Docker
    "docker-compose.yml": "\uf308",  # 󰌈  Docker
    "docker-compose.yaml": "\uf308", # 󰌈  Docker
    "Makefile": "\uf410",        # 󰀐  Build
    "README": "\uf48a",          # 󰍊  Docs
    "README.md": "\uf48a",       # 󰍊  Docs
    "LICENSE": "\uf48a",         # 󰍊  Docs
    "pyproject.toml": "\uf025",  # 󰀥  Python config
    "setup.py": "\ue73c",        # 󰌠  Python
    "package.json": "\uf1c3",    # 󰜃  Node/Package
    "Cargo.toml": "\ue7a8",     # 󰚨  Rust
    "go.mod": "\ue627",          # 󰛧  Go
    "requirements.txt": "\ue73c", # 󰌠  Python
}

# Directories that get special icons
_SPECIAL_DIR_ICONS: dict[str, str] = {
    ".git": "\uf1d3",            # 󰜓  Git
    ".github": "\uf1d3",         # 󰜓  GitHub
    "node_modules": "\uf1c3",    # 󰜃  Node
    "__pycache__": "\ue73c",    # 󰌠  Python cache
    ".venv": "\ue73c",           # 󰌠  Python venv
    "venv": "\ue73c",            # 󰌠  Python venv
    "src": "\uf114",             # 󰅔  Source
    "docs": "\uf48a",            # 󰍊  Docs
    "tests": "\uf48a",           # 󰍊  Tests
    "test": "\uf48a",            # 󰍊  Tests
    "dist": "\uf410",            # 󰀐  Distribution
    "build": "\uf410",           # 󰀐  Build
    ".cargo": "\ue7a8",         # 󰚨  Rust
}


def get_file_icon(filename: str) -> str:
    """Return the Nerd Font icon for *filename*.

    Checks special filenames first, then the extension mapping,
    then falls back to the generic file icon.
    """
    basename = os.path.basename(filename)

    # Check special filenames (exact match)
    if basename in _SPECIAL_FILE_ICONS:
        return _SPECIAL_FILE_ICONS[basename]

    # Check extension
    _, ext = os.path.splitext(basename)
    ext = ext.lower()
    if ext in _FILE_ICONS:
        return _FILE_ICONS[ext]

    # Fallback
    return FILE


def get_folder_icon(dirname: str) -> str:
    """Return the Nerd Font icon for the directory *dirname*.

    Checks special directory names first, then falls back to the
    generic folder icon.
    """
    basename = os.path.basename(dirname)

    if basename in _SPECIAL_DIR_ICONS:
        return _SPECIAL_DIR_ICONS[basename]

    return FOLDER_ICON