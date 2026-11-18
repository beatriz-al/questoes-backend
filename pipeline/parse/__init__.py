"""Parse de PDFs → questões."""

from __future__ import annotations

from typing import Any

__all__ = ["run_parse", "get_parser"]


def __getattr__(name: str) -> Any:
    if name == "run_parse":
        from .runner import run_parse

        return run_parse
    if name == "get_parser":
        from .registry import get_parser

        return get_parser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
