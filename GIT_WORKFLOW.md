# Git Workflow Guide

This document describes the git workflow for the Industrial Communication Simulator project.

## Table of Contents

1. [Initial Setup](#initial-setup)
2. [Daily Workflow](#daily-workflow)
3. [Commit Guidelines](#commit-guidelines)
4. [Branching Strategy](#branching-strategy)
5. [Release Process](#release-process)
6. [Git Hooks](#git-hooks)

---

## Initial Setup

### First Time Setup

```bash
# Clone the repository
git clone https://github.com/nimish-nirmal/industrial-comm-simulator.git
cd industrial-comm-simulator

# Configure git (if not already done)
git config user.name "Your Name"
git config user.email "your.email@example.com"

# Verify remote
git remote -v
```

### Install Git Hooks (Optional)

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# This will run checks before each commit:
# - Code formatting (black)
# - Linting (ruff)
# - Type checking (mypy)
# - Trailing whitespace removal
```

---

## Daily Workflow

### 1. Start New Work

```bash
# Update your local main branch
git checkout main
git pull origin main

# Create a feature branch
git checkout -b feature/add-new-protocol

# Or for bug fixes
git checkout -b fix/modbus-serial-bug
```

### 2. Make Changes

```bash
# Edit files, add new features, fix bugs
# Test your changes
pytest tests/ -v
python3 -m src.main --dry-run

# Check what changed
git status
git diff
```

### 3. Stage Changes

```bash
# Stage specific files
git add src/protocols/modbus/engine.py
git add tests/test_modbus.py

# Or stage all changes
git add .

# Review staged changes
git status
git diff --cached
```

### 4. Commit Changes

```bash
# Commit with descriptive message
git commit -m "feat: add Modbus serial mode support

- Add mode parameter to ModbusEngine (tcp/serial)
- Implement _start_serial_engine() and _stop_serial_engine()
- Update settings.py with MODBUS_MODE configuration
- Add virtual serial port documentation
- Update .env.example with serial mode settings

Closes #123"

# Or use interactive commit
git commit
```

### 5. Push to Remote

```bash
# Push branch to remote
git push origin feature/add-new-protocol

# Set upstream for new branch
git push -u origin feature/add-new-protocol
```

### 6. Create Pull Request

```bash
# Create PR using GitHub CLI (if installed)
gh pr create --title "Add Modbus serial mode" --body "Implements serial RTU support"

# Or create PR via web interface at:
# https://github.com/nimish-nirmal/industrial-comm-simulator/pulls
```

---

## Commit Guidelines

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, missing semicolons, etc.)
- `refactor`: Code refactoring (no feature changes)
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Maintenance tasks (dependencies, build, etc.)
- `ci`: CI/CD changes

### Scopes

- `physics`: Physics engine changes
- `device`: Device/cluster model changes
- `config`: Configuration/settings changes
- `protocol`: Protocol engine changes (specify protocol if possible)
- `workflow`: Workflow manager changes
- `docker`: Docker-related changes
- `tests`: Test suite changes
- `docs`: Documentation changes

### Examples

```bash
# Feature
git commit -m "feat(protocol): add DNP3 outstation engine

- Implement DNP3 TCP server on port 20000
- Map analog signals to Group 30 (Analog Input)
- Map binary signals to Group 1 (Binary Input)
- Add CRC-16 validation
- Include comprehensive DNP3 protocol documentation

Closes #45"

# Bug fix
git commit -m "fix(physics): clamp counter values to max bound

Counters were not being clamped to max_value, causing overflow.
Now properly clamps to max_value after each step.

Fixes #67"

# Documentation
git commit -m "docs: update TESTING.md with Modbus serial examples

Add section on virtual serial port setup with socat
Add Docker serial mode testing instructions
Add troubleshooting for serial port permissions"

# Refactor
git commit -m "refactor(protocol): extract common server start/stop logic

Move server lifecycle management to base ProtocolEngine class
Reduce code duplication across protocol engines
Improve error handling and logging"
```

---

## Branching Strategy

### Branch Naming

```
feature/<short-description>   # New features
fix/<short-description>       # Bug fixes
hotfix/<short-description>    # Urgent production fixes
docs/<short-description>      # Documentation only
refactor/<short-description>  # Code refactoring
test/<short-description>      # Test additions/updates
chore/<short-description>     # Maintenance tasks
```

### Examples

```bash
feature/add-websocket-protocol
fix/modbus-address-allocation
docs/update-readme-with-docker
refactor/extract-protocol-base
test/add-physics-engine-tests
chore/update-dependencies
```

### Branch Protection

Main branch should be protected:
- Require pull request reviews
- Require status checks (CI tests)
- Require branches to be up to date
- Restrict force pushes
- Restrict deletions

---

## Release Process

### 1. Create Release Branch

```bash
git checkout main
git pull origin main
git checkout -b release/v1.0.0
```

### 2. Update Version Numbers

```bash
# Update version in pyproject.toml
# Update version in src/main.py
# Update CHANGELOG.md
```

### 3. Final Testing

```bash
# Run full test suite
pytest tests/ --cov=src --cov-report=html

# Test Docker build
docker-compose build

# Test dry-run
python3 -m src.main --dry-run
```

### 4. Merge and Tag

```bash
# Merge release branch
git checkout main
git merge release/v1.0.0

# Create tag
git tag -a v1.0.0 -m "Release version 1.0.0"

# Push tag
git push origin v1.0.0
git push origin main
```

### 5. Create GitHub Release

```bash
# Using GitHub CLI
gh release create v1.0.0 \
  --title "Version 1.0.0" \
  --notes-file RELEASE_NOTES.md \
  --latest
```

---

## Git Hooks

### Pre-commit Hook

The project includes a `.pre-commit-config.yaml` that runs:

1. **black** - Code formatting
2. **ruff** - Linting
3. **mypy** - Type checking
4. **trailing whitespace** - Cleanup
5. **end of file** - Ensure newline at EOF
6. **large files** - Prevent committing large files

### Manual Hook Execution

```bash
# Run hooks on all files
pre-commit run --all-files

# Run specific hook
pre-commit run black --all-files
```

### Skip Hooks (Emergency Only)

```bash
# Skip pre-commit hooks (not recommended)
git commit --no-verify -m "emergency fix"
```

---

## Common Commands

### Viewing History

```bash
# View commit history
git log --oneline --graph --all

# View changes in last commit
git show HEAD

# View changes for specific file
git log --oneline -- src/protocols/modbus/engine.py

# Compare branches
git diff main..feature/add-new-protocol
```

### Undoing Changes

```bash
# Undo working directory changes (unstaged)
git checkout -- file.py

# Unstage file (keep changes)
git reset HEAD file.py

# Undo last commit (keep changes)
git reset --soft HEAD~1

# Undo last commit (discard changes)
git reset --hard HEAD~1

# Revert commit (create new commit)
git revert HEAD
```

### Stashing

```bash
# Stash current changes
git stash

# Stash with message
git stash save "WIP: adding Modbus serial support"

# List stashes
git stash list

# Apply stash
git stash pop

# Apply specific stash
git stash apply stash@{0}
```

### Branch Management

```bash
# List all branches
git branch -a

# Delete local branch
git branch -d feature/old-feature

# Delete remote branch
git push origin --delete feature/old-feature

# Rename current branch
git branch -m new-name
```

---

## Workflow Example

Complete workflow for adding a new feature:

```bash
# 1. Start from main
git checkout main
git pull origin main

# 2. Create feature branch
git checkout -b feature/add-iec60870-support

# 3. Make changes
# ... edit files, add tests ...

# 4. Test
pytest tests/test_all_protocols.py -v
python3 -m src.main --dry-run

# 5. Format code
black src/
ruff check src/

# 6. Stage and commit
git add src/protocols/iec60870/ tests/test_all_protocols.py
git commit -m "feat(protocol): add IEC 60870-5-104 protocol engine

- Implement IEC 60870-5-104 server on port 2404
- Map signals to ASDU types
- Add connection handling and message parsing
- Include comprehensive protocol documentation
- Add test coverage

Closes #89"

# 7. Push
git push -u origin feature/add-iec60870-support

# 8. Create PR via GitHub
gh pr create --title "Add IEC 60870-5-104 protocol" --body "Implements IEC 60870-5-104 power telecontrol protocol"

# 9. After review, merge PR on GitHub
# 10. Delete feature branch
git branch -d feature/add-iec60870-support
git push origin --delete feature/add-iec60870-support

# 11. Update local main
git checkout main
git pull origin main
```

---

## Troubleshooting

### Merge Conflicts

```bash
# When merge conflict occurs
git status  # See conflicted files

# Edit files to resolve conflicts
# Look for <<<<<<< ======= >>>>>>> markers

# After resolving
git add .
git commit -m "fix: resolve merge conflict in modbus engine"
```

### Accidentally Committed to Main

```bash
# Create branch from current state
git branch saved-work

# Reset main to remote
git checkout main
git reset --hard origin/main

# Switch back to saved work
git checkout saved-work
```

### Large Files Committed

```bash
# Remove large file from history
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch large_file.zip' \
  --prune-empty --tag-name-filter cat -- --all

# Force push (coordinate with team)
git push --force --all
```

---

## Best Practices

1. **Commit Often**: Small, focused commits are better than large ones
2. **Write Good Messages**: Future you will thank present you
3. **Test Before Commit**: Run tests before every commit
4. **Pull Before Push**: Always pull latest changes before pushing
5. **Use Branches**: Don't commit directly to main
6. **Review Diffs**: Always review `git diff` before committing
7. **Sign Commits**: Use GPG signing for important commits
8. **Keep History Clean**: Use interactive rebase to clean up commits

---

## Additional Resources

- [Git Book](https://git-scm.com/book/en/v2)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [GitHub Flow](https://guides.github.com/introduction/flow/)
- [Atlassian Git Tutorials](https://www.atlassian.com/git/tutorials)

For project-specific questions, check [GitHub Issues](https://github.com/nimish-nirmal/industrial-comm-simulator/issues).