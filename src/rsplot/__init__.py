"""rsplot — CLI tool for plotting Remote Sensing data, designed for agent."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rsplot")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "unknown"

__all__ = ["__version__"]
