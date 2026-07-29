# CI/CD Pipeline Documentation

This document describes the Continuous Integration and Continuous Deployment pipeline for the Industrial Communication Simulator.

## Table of Contents

1. [Overview](#overview)
2. [CI Pipeline](#ci-pipeline)
3. [Status Checks](#status-checks)
4. [Deployment](#deployment)
5. [Monitoring](#monitoring)

---

## Overview

The CI/CD pipeline automates:
- **Code quality checks** (formatting, linting, type checking)
- **Unit testing** with coverage reporting
- **Protocol validation** (all 15 protocols)
- **Docker image builds**
- **Integration testing** with MQTT broker
- **Status badges** for README

### Pipeline Diagram

```
Push/PR → Code Quality → Unit Tests → Protocol Validation → Docker Build → Integration Tests → Status Check
              ↓               ↓                ↓                 ↓                  ↓
           black/ruff     pytest/          import            docker            mosquitto
           mypy          coverage         validation        build
```

---

## CI Pipeline

### Workflow File

Location: `.github/workflows/ci.yml`

### Triggers

```yaml
on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]
  workflow_dispatch:  # Manual trigger
```

### Jobs

#### 1. Code Quality

**Purpose:** Ensure code follows style guidelines and type safety

**Steps:**
- Checkout code
- Set up Python 3.11
- Install black, ruff, mypy
- Run black (code formatting)
- Run ruff (linting)
- Run mypy (type checking)

**Status:** ❌ Failed if any check fails

**Run Time:** ~30 seconds

#### 2. Unit Tests

**Purpose:** Test core functionality with coverage

**Steps:**
- Checkout code
- Set up Python 3.11
- Install pytest, pytest-cov, pydantic
- Run physics engine tests (20 tests)
- Run device model tests (20 tests)
- Run protocol instantiation tests (15 tests)
- Upload coverage to Codecov

**Status:** ❌ Failed if any test fails

**Coverage Target:** >80%

**Run Time:** ~1 minute

#### 3. Protocol Import Validation

**Purpose:** Verify all 15 protocol engines can be imported and instantiated

**Steps:**
- Checkout code
- Set up Python 3.11
- Install core dependencies
- Validate all protocol imports
- Validate configuration loading

**Status:** ❌ Failed if any protocol fails to import

**Run Time:** ~20 seconds

#### 4. Docker Build

**Purpose:** Ensure Docker image builds successfully

**Steps:**
- Checkout code
- Set up Docker Buildx
- Build Docker image
- Test Docker image (list protocols, dry-run)

**Status:** ❌ Failed if build fails

**Run Time:** ~2 minutes

#### 5. Integration Tests

**Purpose:** Test protocols with real services (MQTT broker)

**Steps:**
- Checkout code
- Set up Python 3.11
- Install pymodbus, paho-mqtt
- Start Mosquitto MQTT broker
- Wait for broker to be ready
- Test MQTT protocol engine
- Test Sparkplug protocol engine

**Status:** ❌ Failed if integration tests fail

**Run Time:** ~2 minutes

**Note:** This job only runs if jobs 2, 3, and 4 pass

#### 6. Status Check Aggregator

**Purpose:** Final status check and badge generation

**Steps:**
- Check all previous jobs
- Print success message
- Generate status badge

**Status:** ✅ Only runs if all previous jobs pass

---

## Status Checks

### Required Status Checks

For PRs to be merged, the following checks must pass:

1. ✅ **Code Quality** - black, ruff, mypy
2. ✅ **Unit Tests** - pytest with coverage
3. ✅ **Protocol Validation** - all 15 protocols import
4. ✅ **Docker Build** - image builds successfully

### Optional Status Checks

5. ⚠️ **Integration Tests** - MQTT/Sparkplug with broker

### Status Badge

Add this to your README.md:

```markdown
![CI](https://github.com/nimish-nirmal/industrial-comm-simulator/workflows/CI%20Pipeline/badge.svg)
```

### Branch Protection Rules

Configure in GitHub repository settings:

```yaml
# .github/branch-protection-rules.json
{
  "main": {
    "required_status_checks": {
      "strict": true,
      "contexts": [
        "Code Quality",
        "Unit Tests",
        "Protocol Validation",
        "Docker Build"
      ]
    },
    "enforce_admins": false,
    "required_pull_request_reviews": {
      "required_approving_review_count": 1,
      "dismiss_stale_reviews": true
    },
    "restrictions": null,
    "allow_force_pushes": false,
    "allow_deletions": false
  }
}
```

---

## Deployment

### Automated Deployment (Future)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    tags:
      - 'v*'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build and push Docker image
        run: |
          docker build -t industrial-simulator:${{ github.ref }} .
          docker push industrial-simulator:${{ github.ref }}
      
      - name: Deploy to production
        run: |
          # Add deployment script here
          ./deploy.sh ${{ github.ref }}
```

### Manual Deployment

```bash
# Build Docker image
docker build -t industrial-simulator:latest .

# Tag and push
docker tag industrial-simulator:latest industrial-simulator:v1.0.0
docker push industrial-simulator:v1.0.0

# Deploy to server
ssh user@server "docker pull industrial-simulator:v1.0.0"
ssh user@server "docker-compose up -d"
```

---

## Monitoring

### GitHub Actions Dashboard

View pipeline status:
```
https://github.com/nimish-nirmal/industrial-comm-simulator/actions
```

### Codecov Dashboard

View coverage reports:
```
https://codecov.io/gh/nimish-nirmal/industrial-comm-simulator
```

### Status Badges

Add to README.md:

```markdown
# Industrial Communication Simulator

![CI](https://github.com/nimish-nirmal/industrial-comm-simulator/workflows/CI%20Pipeline/badge.svg)
![Coverage](https://codecov.io/gh/nimish-nirmal/industrial-comm-simulator/branch/main/graph/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
```

### Notifications

Configure in repository settings:

**Slack Notifications:**
```yaml
# .github/workflows/ci.yml
- name: Slack notification
  if: failure()
  uses: slackapi/slack-github-action@v1
  with:
    payload: |
      {
        "text": "CI failed for ${{ github.repository }}"
      }
```

**Email Notifications:**
- Configure in GitHub repository settings → Notifications

---

## Local CI Testing

### Run All Checks Locally

```bash
# Install dependencies
pip install black ruff mypy pytest pytest-cov

# Code quality
black --check --diff src/ tests/
ruff check src/ tests/
mypy src/ --ignore-missing-imports

# Unit tests
pytest tests/ -v --cov=src --cov-report=html

# Protocol validation
python3 -c "
import sys
sys.path.insert(0, '.')
# ... (copy from ci.yml)
"

# Docker build
docker-compose build
```

### Pre-commit Hooks

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Run on all files
pre-commit run --all-files

# Skip hooks (emergency only)
git commit --no-verify -m "emergency fix"
```

### GitHub CLI

```bash
# Install GitHub CLI
# https://cli.github.com/

# View workflow runs
gh run list

# View specific run
gh run view <run-id>

# Rerun failed jobs
gh run rerun <run-id>

# Watch workflow
gh run watch
```

---

## Troubleshooting

### CI Fails on Code Quality

**Issue:** Black formatting check fails

**Solution:**
```bash
# Format code
black src/ tests/

# Verify
black --check --diff src/ tests/
```

**Issue:** Ruff linting fails

**Solution:**
```bash
# Auto-fix issues
ruff check src/ tests/ --fix

# Verify
ruff check src/ tests/
```

**Issue:** Mypy type checking fails

**Solution:**
```bash
# Check specific errors
mypy src/ --ignore-missing-imports --show-error-codes

# Fix type hints or add type: ignore comments
```

### CI Fails on Tests

**Issue:** Tests fail locally but pass in CI

**Solution:**
```bash
# Ensure same Python version
python3 --version  # Should be 3.11

# Clean environment
pip install -e ".[dev]"

# Run with same settings as CI
pytest tests/ -v --tb=short
```

**Issue:** Coverage below threshold

**Solution:**
```bash
# Generate coverage report
pytest tests/ --cov=src --cov-report=html

# Open htmlcov/index.html to see uncovered lines

# Add tests for uncovered code
```

### CI Fails on Docker Build

**Issue:** Docker build fails

**Solution:**
```bash
# Build locally
docker build -t test .

# Check Dockerfile syntax
docker build --no-cache -t test .

# Check Docker daemon
docker info
```

### CI Fails on Protocol Validation

**Issue:** Protocol import fails

**Solution:**
```bash
# Test import locally
python3 -c "from src.protocols.modbus import ModbusEngine"

# Check for missing dependencies
pip list | grep pymodbus

# Install missing dependency
pip install pymodbus
```

---

## Performance Optimization

### Caching

The CI pipeline uses caching to speed up builds:

```yaml
# Cache pip dependencies
- uses: actions/setup-python@v5
  with:
    cache: 'pip'

# Cache Docker layers
- uses: docker/build-push-action@v5
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

### Parallel Jobs

Jobs run in parallel to reduce total time:

```
code-quality (30s) ─┐
                    ├→ status-check (5s)
test-unit (1m) ─────┤
                    ├→ status-check (5s)
test-protocols (20s)┘
                    │
test-docker (2m) ───┘
                    │
test-integration (2m) ───┘ (needs: test-unit, test-protocols, test-docker)
```

**Total Time:** ~2 minutes (with parallelization)

### Cost Optimization

- Use GitHub Actions free tier (2000 minutes/month for public repos)
- Cache dependencies to reduce install time
- Use self-hosted runners for private repos
- Run integration tests only on main branch

---

## Best Practices

1. **Run CI Locally First:** Test before pushing
2. **Fix Issues Immediately:** Don't leave CI broken
3. **Monitor Coverage:** Keep coverage >80%
4. **Review Logs:** Check CI logs for errors
5. **Use Status Checks:** Require checks before merge
6. **Cache Dependencies:** Speed up builds
7. **Parallel Jobs:** Reduce total time
8. **Fail Fast:** Stop pipeline on first failure

---

## Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Codecov Documentation](https://docs.codecov.com/)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
- [Pre-commit Hooks](https://pre-commit.com/)

For CI/CD issues, check [GitHub Issues](https://github.com/nimish-nirmal/industrial-comm-simulator/issues).