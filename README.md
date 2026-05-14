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

### Technology stack

- [Qt](https://www.qt.io/) via [PySide6](https://doc.qt.io/qtforpython-6/gettingstarted.html#getting-started) as the cross-platform UI framework; and
- [PyQtGraph](https://www.pyqtgraph.org/) for plotting.
