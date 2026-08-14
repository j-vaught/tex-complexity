"""Analyze the writing complexity of LaTeX documents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tex-complexity")
except PackageNotFoundError:  # Support direct source-tree imports.
    __version__ = "0+unknown"
