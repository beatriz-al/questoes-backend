"""Registro banca -> parser."""

from __future__ import annotations

from .base import BancaParser
from .cebraspe import CebraspeParser
from .fgv import FgvParser
from .vunesp import VunespParser

_PARSERS: dict[str, BancaParser] = {
    "fgv": FgvParser(),
    "cebraspe": CebraspeParser(),
    "vunesp": VunespParser(),
}


def get_parser(banca_key: str) -> BancaParser:
    key = banca_key.strip().lower()
    if key not in _PARSERS:
        known = ", ".join(sorted(_PARSERS))
        raise ValueError(f"Parser não encontrado para banca {banca_key!r}. Use: {known}")
    return _PARSERS[key]
