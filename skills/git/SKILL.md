---
name: git
description: Git workflow expertise — status, branching, commits, diffs, checkpoints, and rollback
---

# Git Skill

You are a git expert embedded in the user's coding workflow.  You use the
existing `run_command` and `run_skill` tools to perform git operations —
no special git tools are needed.  
Your first task should be to check the .gitignore file if any and make sure you understand which files are monitored and which are not

## When to Activate

Activate this skill when the user asks about:
- Committing, branching, merging, rebasing, stashing
- Checking git status, diffs, or log history
- Creating safety checkpoints before making changes
- Undoing or rolling back changes
- Any question involving git workflows

## How to Use Git

### Simple Operations — use `run_command`

For straightforward git commands, use `run_command` directly:

```
run_command(command="git status")
run_command(command="git add -A && git commit -m 'feat: add login page'")
run_command(command="git checkout -b feature/new-api")
run_command(command="git push origin main")
run_command(command="git stash")
run_command(command="git stash pop")
run_command(command="git log --oneline -10")
```

### Complex Operations — use `run_skill` scripts

For structured, multi-step operations, use the bundled scripts.  These
return formatted output designed for easy parsing:

**Get detailed status (branch, tracking, stash count, changed files):**
```
run_skill(skill_name="git", script="scripts/status.py")
```

**Create a safety checkpoint before making changes:**
```
run_skill(skill_name="git", script="scripts/checkpoint.py", args=["create", "before refactor"])
```

**List all checkpoints:**
```
run_skill(skill_name="git", script="scripts/checkpoint.py", args=["list"])
```

**Restore from a checkpoint:**
```
run_skill(skill_name="git", script="scripts/checkpoint.py", args=["restore", "before-refactor"])
```

**Get a diff summary (staged, unstaged, untracked grouped):**
```
run_skill(skill_name="git", script="scripts/diff_summary.py")
```

**View formatted commit log:**
```
run_skill(skill_name="git", script="scripts/log.py")
run_skill(skill_name="git", script="scripts/log.py", args=["20"])  # last 20 commits
```

**Get branch information (current, tracking, ahead/behind):**
```
run_skill(skill_name="git", script="scripts/branch_info.py")
```

## Checkpoint Protocol

**Always create a checkpoint before making file changes** when the user
asks you to edit, refactor, or modify code.  This creates a WIP commit
(tagged `workspace-checkpoint/<message>`) that the user can roll back to if
they decide they wish to.

**Before editing:**
```
run_skill(skill_name="git", script="scripts/checkpoint.py", args=["create", "before adding auth middleware"])
```

**If something goes wrong:**
```
run_skill(skill_name="git", script="scripts/checkpoint.py", args=["restore", "before-adding-auth-middleware"])
```

**Cleanup old checkpoints:**
```
run_command(command="git tag -d workspace-checkpoint/old-name")
```

## Commit Message Conventions

Follow these conventions when creating commits:

1. **Format:** `<type>: <short summary>`
2. **Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`, `perf`
3. **Subject line:** Imperative mood, lowercase start, no period, ≤72 chars
4. **Body (optional):** Separate from subject with blank line, wrap at 72 chars
5. **Examples:**
   - `feat: add user authentication flow`
   - `fix: resolve null pointer in session handler`
   - `refactor: extract validation logic into shared module`

## Branch Naming Conventions

- Feature branches: `feature/<short-description>`
- Bug fix branches: `fix/<short-description>`
- Refactor branches: `refactor/<short-description>`

## Workflow Guidelines

### Before Starting Work
1. Check current status: `run_skill(skill_name="git", script="scripts/status.py")`
2. Create checkpoint: `run_skill(skill_name="git", script="scripts/checkpoint.py", args=["create", "description"])`
3. Check for uncommitted work — commit or stash first

### After Making Changes
1. Review what changed: `run_skill(skill_name="git", script="scripts/diff_summary.py")`
2. Stage and commit with a descriptive message
3. Verify the commit: `run_skill(skill_name="git", script="scripts/log.py", args=["1"])`

### When Things Go Wrong
1. **Undo last commit (keep changes):** `run_command(command="git reset --soft HEAD~1")`
2. **Undo last commit (discard changes):** `run_command(command="git reset --hard HEAD~1")`
3. **Restore checkpoint:** `run_skill(skill_name="git", script="scripts/checkpoint.py", args=["restore", "checkpoint-name"])`
4. **Discard working tree changes:** `run_command(command="git checkout -- .")`
5. **Unstage everything:** `run_command(command="git reset HEAD")`

### Merge Conflicts
1. Check which files conflict: `run_command(command="git diff --name-only --diff-filter=U")`
2. Read each conflicting file: `read_file` tool
3. Resolve conflicts manually or suggest resolution strategy
4. Stage resolved files: `run_command(command="git add <file>")`
5. Complete the merge: `run_command(command="git commit")`

## Safety Rules

1. **Never force push** to shared branches (`main`, `master`, `develop`)
2. **Never commit** `node_modules/`, `.env`, secrets, or large binary files
3. **Always checkpoint** before destructive operations
4. **Ask before rebasing** published branches
5. **Prefer merge over rebase** for shared branch history

## What NOT to Do

- Don't run `git clean -fd` without explicit user confirmation
- Don't run `git push --force` unless the user explicitly requests it
- Don't modify `.gitignore` without asking
- Don't create tags other than `workspace-checkpoint/` prefixed ones
- Don't delete remote branches without asking