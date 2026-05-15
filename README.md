# PulsePump

1. Install `uv` (https://docs.astral.sh/uv/getting-started/installation/);
2. Clone the repo using `git clone https://github.com/PulsePump/pulsepump.git`;
3. Create a virtual environment by running `uv sync`;
4. Run the application using `uv run pulsepump`.

## Stack

- [Qt](https://www.qt.io/) via [PySide6](https://doc.qt.io/qtforpython-6/gettingstarted.html#getting-started) as the cross-platform UI framework; and
- [PyQtGraph](https://www.pyqtgraph.org/) for plotting.
- [Sphinx](https://www.sphinx-doc.org/) for documentation.

## Development

Tools:

- Lint the project using `uv run ruff check`;
- Format the project using `uv run ruff format`; and
- Typecheck the project using `uv run ty check`.

### VS Code

Install extensions: [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python), [Python Debugger](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy), [Ruff](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff), [ty](https://marketplace.visualstudio.com/items?itemName=astral-sh.ty).

Launch configs (`⇧⌘D` → F5, with debugger):

| Name                          | Runs                  |
| ----------------------------- | --------------------- |
| `pulsepump: run`              | `python -m pulsepump` |
| `pulsepump: run current file` | the active file       |

Tasks (`⇧⌘P` → "Tasks: Run Task", no debugger):

| Name                                         | Runs                                                                               |
| -------------------------------------------- | ---------------------------------------------------------------------------------- |
| `pulsepump: run`                             | `uv run pulsepump`                                                                 |
| `pulsepump: run current file`                | `uv run python ${file}`                                                            |
| `docs: serve + live reload`                  | `uv run sphinx-autobuild` — opens browser, rebuilds on edits to `docs/` and `src/` |
| `ruff: format` / `ruff: check` / `ty: check` | individual checks                                                                  |
| `prelaunch: format + lint + typecheck`       | the three above in sequence                                                        |

Every launch and task depends on `prelaunch: format + lint + typecheck`; failures abort the run and surface in the Problems panel. `.vscode/settings.json` pins the interpreter to `.venv/bin/python` and enables Ruff format-on-save.

## Documentation

You can build locally by running:

```bash
uv run sphinx-autobuild --open-browser --watch src docs docs/_build/html
```
