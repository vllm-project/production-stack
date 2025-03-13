# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
from dataclasses import asdict

from sphinx.ext import autodoc

sys.path.insert(0, os.path.abspath("../../src/"))

project = "production-stack"
copyright = "2025, vLLM Production Stack Team"
author = "vLLM Production Stack Team"

extensions = [
    "sphinx_copybutton",
    "sphinx.ext.napoleon",
    # "sphinx.ext.linkcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    # "myst_parser",
    # "sphinxarg.ext",
    "sphinx_design",
    "sphinx_togglebutton",
    "sphinx_click",
]

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

templates_path = ["_templates"]
exclude_patterns = []

copybutton_prompt_text = r"\$ "
copybutton_prompt_is_regexp = True


class MockedClassDocumenter(autodoc.ClassDocumenter):
    """Remove note about base class when a class is
    derived from object."""

    def add_line(self, line: str, source: str, *lineno: int) -> None:
        if line == "   Bases: :py:class:`object`":
            return
        super().add_line(line, source, *lineno)


autodoc.ClassDocumenter = MockedClassDocumenter

# autodoc_default_options = {
#     "members": True,
#     "undoc-members": True,
#     "private-members": True
# }


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_title = project
html_theme = "sphinx_book_theme"
html_static_path = ["_static"]
html_logo = "./assets/prodstack_icon.png"
html_favicon = "./assets/output.ico"
html_permalinks_icon = "<span>#</span>"
# pygments_style = "sphinx"
# pygments_style_dark = "fruity"
html_theme_options = {
    "path_to_docs": "docs/source",
    "repository_url": "https://github.com/vllm-project/production-stack",
    "use_repository_button": True,
    "use_edit_page_button": True,
    # navigation and sidebar
    "show_toc_level": 2,
    "announcement": None,
    "secondary_sidebar_items": [
        "page-toc",
    ],
    "navigation_depth": 3,
    "primary_sidebar_end": [],
    "pygments_light_style": "friendly",
    "pygments_dark_style": "monokai",
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "typing_extensions": ("https://typing-extensions.readthedocs.io/en/latest", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "torch": ("https://pytorch.org/docs/stable", None),
    "psutil": ("https://psutil.readthedocs.io/en/stable", None),
}
