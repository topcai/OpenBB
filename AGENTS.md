# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This is the **OpenBB Open Data Platform** — a Python-based financial data integration platform. The primary development targets are:

- **OpenBB Platform** (Python library + extensions): `/workspace/openbb_platform/`
- **OpenBB Platform API** (FastAPI/Uvicorn REST server at `127.0.0.1:6900`): part of the platform extensions
- **OpenBB CLI** (optional): `/workspace/cli/`

### Development Environment

- **Python**: 3.12 (system python3; no `python` alias — always use `python3`)
- **Package Manager**: Poetry (installed at `~/.local/bin/poetry`; ensure `$HOME/.local/bin` is on PATH)
- **Virtual Environment**: Managed by Poetry at `~/.cache/pypoetry/virtualenvs/openbb-*`
- **Dev Install**: Run from `/workspace/openbb_platform`: `python3 dev_install.py -e` (installs all extensions + extras in editable mode)
- All commands that need the project's virtualenv must be prefixed with `poetry run` (from `/workspace/openbb_platform`)

### Running Services

**API Server** (primary service):
```bash
cd /workspace/openbb_platform
export OPENBB_AUTO_BUILD=false
poetry run openbb-api --host 127.0.0.1 --port 6900
```
Setting `OPENBB_AUTO_BUILD=false` avoids a slow rebuild on every import when the package is already built.

**First import after install** triggers an auto-build of the package extensions (takes ~20s). Subsequent imports are fast.

### Lint / Test / Build

- **Lint**: `cd /workspace/openbb_platform && poetry run ruff check . --config ../ruff.toml`
- **Unit tests**: `cd /workspace/openbb_platform && poetry run pytest core/tests/ -m "not integration" -x -q`
- **Provider tests**: `cd /workspace/openbb_platform && poetry run pytest providers/<name>/tests/ -m "not integration" -x -q`
- **Integration tests** (require running API): `cd /workspace/openbb_platform && poetry run pytest -m integration`
- **Full test suite**: `cd /workspace/openbb_platform && poetry run pytest`

### Gotchas

- The `dev_install.py` script temporarily modifies `pyproject.toml` and `poetry.lock` during install, then reverts them. Do not interrupt it.
- Many data providers require API keys configured in `~/.openbb_platform/user_settings.json`. For tests that hit external APIs, use recorded cassettes or mock data.
- The first `from openbb import obb` after a fresh install will trigger a build step that detects installed extensions. Set `OPENBB_AUTO_BUILD=false` env var to skip if extensions haven't changed.
- `ruff` is pinned as a dependency of `openbb-core` (currently `^0.15`), so use `poetry run ruff` rather than a system-installed version.
