"""Tests for the icon registry (utils/icons.py)."""

import pytest
from utils.icons import (
    get_file_icon,
    get_folder_icon,
    FILE,
    FOLDER,
    FOLDER_ICON,
    FOLDER_OPEN,
    EDIT,
    DELETE,
    RENAME,
    ADD_FILE,
    ADD_DIR,
    REFRESH,
    CLOSE,
    COPY,
    _FILE_ICONS,
    _SPECIAL_FILE_ICONS,
    _SPECIAL_DIR_ICONS,
)


# ---------------------------------------------------------------------------
# Constants are set
# ---------------------------------------------------------------------------


class TestIconConstants:
    def test_action_icons_are_strings(self):
        """All action icon constants are non-empty strings."""
        for icon in [EDIT, DELETE, RENAME, ADD_FILE, ADD_DIR,
                     REFRESH, CLOSE, COPY, FOLDER, FILE, FOLDER_OPEN]:
            assert isinstance(icon, str)
            assert len(icon) > 0

    def test_folder_icon_is_not_file_icon(self):
        """Folder and file icons are distinct."""
        assert FOLDER != FILE


# ---------------------------------------------------------------------------
# get_file_icon
# ---------------------------------------------------------------------------


class TestGetFileIcon:
    def test_python_file(self):
        assert get_file_icon("main.py") == _FILE_ICONS[".py"]

    def test_javascript_file(self):
        assert get_file_icon("app.js") == _FILE_ICONS[".js"]

    def test_typescript_file(self):
        assert get_file_icon("app.ts") == _FILE_ICONS[".ts"]

    def test_markdown_file(self):
        assert get_file_icon("README.md") == _SPECIAL_FILE_ICONS["README.md"]

    def test_json_file(self):
        assert get_file_icon("package.json") == _SPECIAL_FILE_ICONS["package.json"]

    def test_unknown_extension_falls_back(self):
        assert get_file_icon("data.xyz") == FILE

    def test_no_extension_falls_back(self):
        assert get_file_icon("Makefile") == _SPECIAL_FILE_ICONS["Makefile"]

    def test_gitignore_special(self):
        assert get_file_icon(".gitignore") == _SPECIAL_FILE_ICONS[".gitignore"]

    def test_dockerfile_special(self):
        assert get_file_icon("Dockerfile") == _SPECIAL_FILE_ICONS["Dockerfile"]

    def test_special_filename_takes_priority_over_extension(self):
        """README.md uses the special icon, not the .md extension icon."""
        assert get_file_icon("README.md") == _SPECIAL_FILE_ICONS["README.md"]
        # Regular .md file uses extension icon
        assert get_file_icon("notes.md") == _FILE_ICONS[".md"]

    def test_case_insensitive_extension(self):
        """Extension matching is case-insensitive."""
        assert get_file_icon("main.PY") == _FILE_ICONS[".py"]
        assert get_file_icon("styles.CSS") == _FILE_ICONS[".css"]

    def test_path_with_directories(self):
        """get_file_icon extracts the basename from a path."""
        assert get_file_icon("src/utils/helpers.py") == _FILE_ICONS[".py"]

    def test_hidden_file_with_extension(self):
        """Hidden files (starting with .) still match extension."""
        assert get_file_icon(".env.local") == _SPECIAL_FILE_ICONS[".env.local"]

    def test_rust_file(self):
        assert get_file_icon("main.rs") == _FILE_ICONS[".rs"]

    def test_go_file(self):
        assert get_file_icon("main.go") == _FILE_ICONS[".go"]

    def test_yaml_file(self):
        assert get_file_icon("config.yaml") == _FILE_ICONS[".yaml"]

    def test_toml_file(self):
        assert get_file_icon("Cargo.toml") == _SPECIAL_FILE_ICONS["Cargo.toml"]

    def test_sql_file(self):
        assert get_file_icon("schema.sql") == _FILE_ICONS[".sql"]

    def test_lock_file(self):
        assert get_file_icon("poetry.lock") == _FILE_ICONS[".lock"]

    def test_all_file_icons_are_single_chars(self):
        """All mapped icons and special icons are single characters (Nerd Font)."""
        for ext, icon in _FILE_ICONS.items():
            assert len(icon) == 1, f"Icon for {ext} is not a single char: {repr(icon)}"
        for name, icon in _SPECIAL_FILE_ICONS.items():
            assert len(icon) == 1, f"Icon for {name} is not a single char: {repr(icon)}"


# ---------------------------------------------------------------------------
# get_folder_icon
# ---------------------------------------------------------------------------


class TestGetFolderIcon:
    def test_git_directory(self):
        assert get_folder_icon(".git") == _SPECIAL_DIR_ICONS[".git"]

    def test_github_directory(self):
        assert get_folder_icon(".github") == _SPECIAL_DIR_ICONS[".github"]

    def test_node_modules(self):
        assert get_folder_icon("node_modules") == _SPECIAL_DIR_ICONS["node_modules"]

    def test_pycache(self):
        assert get_folder_icon("__pycache__") == _SPECIAL_DIR_ICONS["__pycache__"]

    def test_src_directory(self):
        assert get_folder_icon("src") == _SPECIAL_DIR_ICONS["src"]

    def test_docs_directory(self):
        assert get_folder_icon("docs") == _SPECIAL_DIR_ICONS["docs"]

    def test_tests_directory(self):
        assert get_folder_icon("tests") == _SPECIAL_DIR_ICONS["tests"]

    def test_build_directory(self):
        assert get_folder_icon("build") == _SPECIAL_DIR_ICONS["build"]

    def test_unknown_directory_falls_back(self):
        assert get_folder_icon("my_custom_folder") == FOLDER_ICON

    def test_path_with_parent(self):
        """get_folder_icon extracts basename from path."""
        assert get_folder_icon("project/src") == _SPECIAL_DIR_ICONS["src"]

    def test_venv_directory(self):
        assert get_folder_icon(".venv") == _SPECIAL_DIR_ICONS[".venv"]

    def test_all_dir_icons_are_single_chars(self):
        for name, icon in _SPECIAL_DIR_ICONS.items():
            assert len(icon) == 1, f"Icon for dir {name} is not a single char: {repr(icon)}"