"""Tests for the git skill scripts."""

import os
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_script(script_name: str, args: list[str] | None = None, cwd: str | None = None) -> tuple[str, int]:
    """Run a git skill script and return (stdout, returncode)."""
    script_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills", "git", "scripts")
    script_path = os.path.join(script_dir, script_name)
    cmd = ["python3", script_path] + (args or [])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd or os.getcwd(),
    )
    return result.stdout.strip(), result.returncode


def _init_git_repo(tmp_path) -> str:
    """Create a minimal git repo in tmp_path and return the path."""
    cwd = str(tmp_path)
    subprocess.run(["git", "init"], cwd=cwd, capture_output=True, timeout=5)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=cwd, capture_output=True, timeout=5)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=cwd, capture_output=True, timeout=5)
    # Make an initial commit
    readme = tmp_path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True, timeout=5)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=cwd, capture_output=True, timeout=5)
    return cwd


# ---------------------------------------------------------------------------
# status.py
# ---------------------------------------------------------------------------


class TestGitStatus:
    def test_status_clean_repo(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        output, rc = _run_script("status.py", cwd=cwd)
        assert rc == 0
        assert "Branch: master" in output or "Branch: main" in output
        assert "Stashes: 0" in output
        assert "Staged (0):" in output

    def test_status_with_untracked_file(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        (tmp_path / "new_file.py").write_text("print('hello')")
        output, rc = _run_script("status.py", cwd=cwd)
        assert rc == 0
        assert "untracked" in output.lower() or "Untracked" in output

    def test_status_not_git_repo(self, tmp_path):
        cwd = str(tmp_path)
        output, rc = _run_script("status.py", cwd=cwd)
        assert "Not a git repository" in output


# ---------------------------------------------------------------------------
# log.py
# ---------------------------------------------------------------------------


class TestGitLog:
    def test_log_shows_commits(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        output, rc = _run_script("log.py", cwd=cwd)
        assert rc == 0
        assert "initial commit" in output

    def test_log_count_argument(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        # Make a few more commits
        for i in range(3):
            (tmp_path / f"file{i}.txt").write_text(f"content {i}")
            subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True, timeout=5)
            subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=cwd, capture_output=True, timeout=5)

        output, rc = _run_script("log.py", args=["2"], cwd=cwd)
        assert rc == 0
        # Should show exactly 2 commit lines (plus header/footer)
        commit_lines = [l for l in output.split("\n") if l.startswith("  ") and "|" not in l and "Showing" not in l]
        assert len(commit_lines) <= 2

    def test_log_not_git_repo(self, tmp_path):
        cwd = str(tmp_path)
        output, rc = _run_script("log.py", cwd=cwd)
        assert "Not a git repository" in output


# ---------------------------------------------------------------------------
# diff_summary.py
# ---------------------------------------------------------------------------


class TestGitDiffSummary:
    def test_diff_summary_clean_repo(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        output, rc = _run_script("diff_summary.py", cwd=cwd)
        assert rc == 0
        assert "Staged (0):" in output

    def test_diff_summary_with_changes(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        # Modify existing file
        (tmp_path / "README.md").write_text("# Modified\n")
        # Add untracked file
        (tmp_path / "new_file.py").write_text("hello")

        output, rc = _run_script("diff_summary.py", cwd=cwd)
        assert rc == 0
        assert "Unstaged" in output
        assert "Untracked" in output

    def test_diff_summary_not_git_repo(self, tmp_path):
        cwd = str(tmp_path)
        output, rc = _run_script("diff_summary.py", cwd=cwd)
        assert "Not a git repository" in output


# ---------------------------------------------------------------------------
# branch_info.py
# ---------------------------------------------------------------------------


class TestGitBranchInfo:
    def test_branch_info_shows_branch(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        output, rc = _run_script("branch_info.py", cwd=cwd)
        assert rc == 0
        assert "Branch:" in output

    def test_branch_info_not_git_repo(self, tmp_path):
        cwd = str(tmp_path)
        output, rc = _run_script("branch_info.py", cwd=cwd)
        assert "Not a git repository" in output


# ---------------------------------------------------------------------------
# checkpoint.py
# ---------------------------------------------------------------------------


class TestGitCheckpoint:
    def test_checkpoint_list_empty(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        output, rc = _run_script("checkpoint.py", args=["list"], cwd=cwd)
        assert rc == 0
        assert "No checkpoints found" in output

    def test_checkpoint_create(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        # Make a dirty change first
        (tmp_path / "new_file.py").write_text("hello")
        output, rc = _run_script("checkpoint.py", args=["create", "test-checkpoint"], cwd=cwd)
        assert rc == 0
        assert "Checkpoint created" in output
        assert "workspace-checkpoint/" in output

    def test_checkpoint_create_clean_tree(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        # Clean tree — checkpoint just tags HEAD
        output, rc = _run_script("checkpoint.py", args=["create", "clean-checkpoint"], cwd=cwd)
        assert rc == 0
        assert "Checkpoint created" in output
        assert "clean" in output.lower()

    def test_checkpoint_create_then_list(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        (tmp_path / "new_file.py").write_text("hello")
        _run_script("checkpoint.py", args=["create", "list-test"], cwd=cwd)
        output, rc = _run_script("checkpoint.py", args=["list"], cwd=cwd)
        assert rc == 0
        assert "list-test" in output

    def test_checkpoint_help(self, tmp_path):
        cwd = _init_git_repo(tmp_path)
        output, rc = _run_script("checkpoint.py", args=["help"], cwd=cwd)
        assert rc == 0
        assert "Git Checkpoint" in output

    def test_checkpoint_not_git_repo(self, tmp_path):
        cwd = str(tmp_path)
        output, rc = _run_script("checkpoint.py", args=["list"], cwd=cwd)
        assert "Not a git repository" in output