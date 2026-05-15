"""Sphinx configuration for the pulsepump documentation."""

from __future__ import annotations

import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

project = "PulsePump"
authors = [
    "Tahmid Azam",
    "Luca Buxton",
    "India Henry",
    "Lonnie McKiernan",
    "Lucy Payne",
]
author = ", ".join(authors)
copyright = f"2026, {author}"
release = _pkg_version("pulsepump")
version = release


extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "README.md"]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

# -- Autodoc / autosummary ---------------------------------------------------
autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
# MicroPython-only; firmware modules import this on the Pico but not on CPython.
autodoc_mock_imports = ["machine"]
autodoc_typehints = "description"

napoleon_google_docstring = True
napoleon_numpy_docstring = True

# -- MyST --------------------------------------------------------------------
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "linkify",
    "smartquotes",
    "substitution",
]
myst_heading_anchors = 3

# -- Intersphinx -------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
}

# -- HTML output -------------------------------------------------------------
html_theme = "furo"
html_short_title = "PulsePump"
html_static_path = ["_static"]
html_theme_options = {
    "source_repository": "https://github.com/PulsePump/pulsepump",
    "source_branch": "main",
    "source_directory": "docs/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/PulsePump/pulsepump",
            "class": "fa-brands fa-github",
        },
    ],
}
