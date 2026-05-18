# Local development

Ensure uv is installed onto your system. Follow the installation instructions in the uv documentation: https://docs.astral.sh/uv/.

Clone the repository and `cd` into it:

```bash
git clone https://github.com/PulsePump/pulsepump.git
cd pulsepump
```

Now create a virtual environment and install project dependencies using uv:

```bash
uv sync
```

You should have generated a `.venv` folder inside the project directory. Ensure your IDE has recognised this virtual environment. In Visual Studio Code, use _Python: Select Intepreter_.

You can run the project using:

```bash
uv run pulsepump
```

You can format the project using:

```bash
uv run ruff format
```

You can lint the project using:

```bash
uv run ruff check
```

You can typecheck the project using:

```bash
uv run ty check
```

You can build the documentation using:

```bash
uv run sphinx-autobuild --open-browser --watch src docs docs/_build/html
```

In Visual Studio Code, there are bindings that define tasks that carry out the above processes. You can assign these to hotkeys if needed. For these bindings to work properly, you must install the following extensions: [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python), [Python Debugger](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy), [Ruff](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff), and [ty](https://marketplace.visualstudio.com/items?itemName=astral-sh.ty).
