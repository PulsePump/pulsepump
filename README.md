# PulsePump

1. Install `uv` (https://docs.astral.sh/uv/getting-started/installation/);
2. Clone the repo using `git clone https://github.com/PulsePump/pulsepump.git`;
3. Create a virtual environment by running `uv sync`;
4. Run the application using `uv run pulsepump`.

## Development

Tools:

- Lint the project using `uv run ruff check`;
- Format the project using `uv run ruff format`; and
- Typecheck the project using `uv run ty check`.

### VS Code

The repo ships a `.vscode/` workspace with two launch configs and a prelaunch task:

1. Install extensions: [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python), [Python Debugger](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy), [Ruff](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff), and [ty](https://marketplace.visualstudio.com/items?itemName=astral-sh.ty).
2. Open the Run and Debug panel (`⇧⌘D` / `Ctrl+Shift+D`).
3. Pick a config and press F5:
   - **pulsepump: run** — runs `python -m pulsepump` against the workspace `.venv`. Breakpoints in any project file just work.
   - **pulsepump: run current file** — runs the active file (useful for one-off scripts).

Before launching, VS Code runs the composite task `prelaunch: format + lint + typecheck` which executes, in order: `ruff format`, `ruff check`, `ty check`. Format applies in place; lint or typecheck failures **abort the launch** and surface in the Problems panel.

`.vscode/settings.json` pins the workspace interpreter to `.venv/bin/python` and enables Ruff format-on-save with import sorting.

### Technology stack

- [Qt](https://www.qt.io/) via [PySide6](https://doc.qt.io/qtforpython-6/gettingstarted.html#getting-started) as the cross-platform UI framework; and
- [PyQtGraph](https://www.pyqtgraph.org/) for plotting.
