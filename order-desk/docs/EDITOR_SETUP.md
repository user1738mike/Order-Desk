# Local editor setup

The application continues to run and test through Docker Compose. VS Code
uses a separate workspace-local Python environment for imports and editor
linting, with the same locked dependencies as the backend image.

The current `Billion1` workspace has Python 3.14.8 and uv 0.12.23 under
`.tools`, and its editor environment is `.venv`. Both are excluded from Git.
The workspace and repository `.vscode/settings.json` files select that
environment, add the active backend to import paths, and run Ruff 0.16.10
using `backend/pyproject.toml`. Ruff also formats Python on save using the
editor's existing format-on-save preference. Flake8 and Pylint are disabled
for this workspace because their defaults conflict with the established
project checks. They remain installed for other projects.

Historical verification checkouts remain available on disk, but current
workspace analysis focuses on `order-desk`. Open that repository directly
when working on the application. No archived code was reformatted to satisfy
different tools or an older Python parser.

If imports or old lint messages remain cached, run **Developer: Reload Window**
from the Command Palette. The Python status bar should show 3.14.8 and the
Ruff output should show the workspace `.venv/Scripts/ruff.exe` at 0.16.10.
For an existing terminal that still uses system Python, run the environment's
Python explicitly or open a new Python terminal after selecting it.

Repeat local linting from `Billion1/order-desk/backend`:

```powershell
& ../../.venv/Scripts/ruff.exe check . ../scripts
& ../../.venv/Scripts/ruff.exe format --check . ../scripts
```

Use **Tasks: Run Task > backend-lint** from the root workspace for the Docker
lint gate. Test tasks preserve `test_orderdesk` and use the dedicated test
settings. The former reset/drop aliases now run the same safe order tests.

To resync the editor environment from `Billion1`:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.tools/cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.tools/python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) '.venv'
& ./.tools/uv/uv.exe sync --project ./order-desk/backend --locked --no-install-project
```

Do not change the lockfile or install application packages into the unrelated
system Python to repair editor imports.
