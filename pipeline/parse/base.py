"""Interface comum dos parsers por banca."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .types import ParseMeta, ParseResult


class BancaParser(Protocol):
    banca: str

    def parse(
        self,
        prova_pdf: Path,
        gabarito_pdf: Path | None,
        meta: ParseMeta,
    ) -> ParseResult:
        """Extrai questões de um PDF de prova (+ gabarito opcional)."""
        ...
