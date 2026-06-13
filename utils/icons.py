"""Icon registry — Nerd Font icons for file types, folders, and actions.

All icon strings live here so any visual change is made in one place.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Action icons — used in RowButton labels, tab close buttons, etc.
# ---------------------------------------------------------------------------

FOLDER = ""
FILE = ""
OPEN = ""           #   eye / open
EDIT = ""          #   pencil / edit
DELETE = ""        #   trash / delete
RENAME = ""        #   rename / edit-alt
ADD_FILE = ""     #   file-plus (using generic file + text)
ADD_DIR = ""       #   folder-plus
PLUS = "\uff0b"           # ＋ full-width plus
REFRESH = "󰑐"        # 󰑐  refresh / sync
CLOSE = "󰅖"          # 󰅖  times / close
COPY = "󰆏"           # 󰆏  copy
COLLAPSE = "󰅀"       # 󰅀  chevron-down
EXPAND = "󰅁"         # 󰅁  chevron-right
SEARCH = "󰍉"         # 󰍉  search / magnifying glass
EYE = ""            #   eye / show hidden
EYE_OFF = ""        #   eye-off / hide hidden
COMMIT = ""         #   git commit

# ---------------------------------------------------------------------------
# Chat action icons
# ---------------------------------------------------------------------------

SEND = ""          #   send / paper-plane
ABORT = "󰜺"         # 󰜺  abort / stop-circle
PLAY = "▶"          # ▶ play / launch

# ---------------------------------------------------------------------------
# Folder icons
# ---------------------------------------------------------------------------

FOLDER_OPEN = ""    #   folder-open
FOLDER_ICON = ""    #   same as FOLDER, used in tree labels

# ---------------------------------------------------------------------------
# File type icons — extension → Nerd Font glyph
# ---------------------------------------------------------------------------

_FILE_ICONS: dict[str, str] = {
    # Programming languages
    ".py": "",       # 󰌠  Python
    ".js": "",       # 󰌞  JavaScript
    ".ts": "",       #   TypeScript
    ".jsx": "",      #   React JSX
    ".tsx": "",      #   React TSX
    ".rs": "",       #   Rust
    ".go": "",        #   Go
    ".rb": "",        #   Ruby
    ".java": "",      #   Java
    ".kt": "",        #   Kotlin
    ".swift": "",     #   Swift
    ".c": "",         #   C
    ".cpp": "",       #   C++
    ".h": "",         #   header file
    ".cs": "󰌛",        # 󰌛  C# (using .NET icon)
    ".php": "",       #   PHP
    ".lua": "",       #   Lua
    ".r": "",         #   R
    ".scala": "",     #   Scala

    # Web / markup
    ".html": "",      # 󰄻  HTML5
    ".css": "",       # 󰄼  CSS3
    ".tcss": "",      # 󰄼  Textual CSS
    ".less": "",      # 󰄼  LESS
    ".json": "",      # 󰀥  JSON
    ".xml": "󰗀",       # 󰀥  XML
    ".yaml": "",      # 󰀥  YAML
    ".yml": "",       # 󰀥  YAML
    ".toml": "",      # 󰀥  TOML
    ".ini": "",       # 󰀥  INI
    ".cfg": "",       # 󰀥  Config

    # Documentation
    ".md": "",        #   Markdown
    ".txt": "",       # 󰍊  Text
    ".pdf": "",       #   PDF

    # Shell / scripting
    ".sh": "",        #   Shell
    ".bash": "",      #   Bash
    ".zsh": "",       #   Zsh
    ".fish": "",      #   Fish
    ".ps1": "",       #   PowerShell

    # Data / database
    ".sql": "",       #   Database
    ".db": "",        #   SQLite
    ".csv": "",       #   Table/CSV
    ".xlsx": "",      #   Excel

    # Image files
    ".png": "",       #   Image
    ".jpg": "",       #   Image
    ".jpeg": "",      #   Image
    ".gif": "",       #   Image
    ".svg": "",       #   Image
    ".ico": "",       #   Image
    ".webp": "",      #   Image

    # Build / config files (special names handled separately)
    ".lock": "",      #   Lock file
    ".log": "",       #   Log

    # Binary / archive
    ".zip": "",       #   Archive
    ".tar": "",       #   Archive
    ".gz": "",        #   Archive
    ".exe": "󰙵",       #   Executable
    ".dll": "",       #   Binary
    ".so": "",        #   Shared library
}

# Special filenames that get unique icons (checked before extension)
_SPECIAL_FILE_ICONS: dict[str, str] = {
    ".gitignore": "",       # 󰜓  Git
}

# Directories that get special icons
_SPECIAL_DIR_ICONS: dict[str, str] = {
    ".git": "",            #   Git
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