"""Parser heurístico VUNESP (múltipla escolha)."""

from __future__ import annotations

from pathlib import Path

from .pdf_reader import extract_text
from .types import ParseMeta, ParseResult
from ._common import (
    build_questao,
    detect_area,
    extract_alternativas,
    parse_gabarito_map,
    split_question_blocks,
)


class VunespParser:
    banca = "VUNESP"

    def parse(
        self,
        prova_pdf: Path,
        gabarito_pdf: Path | None,
        meta: ParseMeta,
    ) -> ParseResult:
        result = ParseResult()
        try:
            text = extract_text(prova_pdf)
        except Exception as err:  # noqa: BLE001
            result.erros.append(f"Falha ao ler prova {prova_pdf.name}: {err}")
            return result

        gab_map: dict[int, str] = {}
        if gabarito_pdf and gabarito_pdf.is_file():
            try:
                gab_map = parse_gabarito_map(extract_text(gabarito_pdf))
            except Exception as err:  # noqa: BLE001
                result.erros.append(f"Falha ao ler gabarito {gabarito_pdf.name}: {err}")

        area = detect_area(text[:2000])
        blocks = split_question_blocks(text)
        if not blocks:
            result.erros.append(f"Nenhuma questão encontrada em {prova_pdf.name}")
            return result

        for num, body in blocks:
            try:
                enunciado, alts = extract_alternativas(body)
                if not enunciado:
                    result.erros.append(f"Q{num}: enunciado vazio")
                    continue
                gab = gab_map.get(num, "")
                result.questoes.append(
                    build_questao(
                        numero=num,
                        enunciado=enunciado,
                        alternativas=alts,
                        gabarito=gab,
                        meta=meta,
                        area=area,
                        assunto=area if area != "Geral" else None,
                    )
                )
            except Exception as err:  # noqa: BLE001
                result.erros.append(f"Q{num}: {err}")
        return result
