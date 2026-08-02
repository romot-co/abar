"""ABAR public package."""

try:
    from importlib.metadata import version

    __version__ = version("abar")
except Exception:  # pragma: no cover - editable source without metadata
    __version__ = "2.0.0"

__all__ = ["__version__"]
