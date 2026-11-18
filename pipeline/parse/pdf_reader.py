"""Leitura de texto embutido em PDFs (sem OCR)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

# Linha horizontal: quase plana e com comprimento mínimo (pontos PDF).
_MIN_LINE_WIDTH = 40.0
_MAX_LINE_THICKNESS = 2.5
_Y_TOL = 0.75
_X_OVERLAP_MIN = 20.0

# Marcador inserido no texto onde há traço horizontal no PDF.
HLINE_MARKER = "<<<HLINE>>>"

# Recuo de parágrafo Cebraspe: primeira linha ~12+ pt à direita da margem.
_PARA_INDENT_PT = 12.0
# Salto horizontal típico entre colunas no layout de duas colunas.
_COL_SWITCH_PT = 80.0


def _segment_from_line(p1: Any, p2: Any) -> tuple[float, float, float] | None:
    """Retorna (y, x0, x1) se o segmento for horizontal o bastante."""
    y1, y2 = float(p1.y), float(p2.y)
    x1, x2 = float(p1.x), float(p2.x)
    if abs(y1 - y2) > _Y_TOL:
        return None
    width = abs(x2 - x1)
    if width < _MIN_LINE_WIDTH:
        return None
    return ((y1 + y2) / 2.0, min(x1, x2), max(x1, x2))


def _segment_from_rect(rect: Any) -> tuple[float, float, float] | None:
    """Retorna (y, x0, x1) se o retângulo for uma barra horizontal fina."""
    x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
    height = abs(y1 - y0)
    width = abs(x1 - x0)
    if height > _MAX_LINE_THICKNESS or width < _MIN_LINE_WIDTH:
        return None
    return ((y0 + y1) / 2.0, min(x0, x1), max(x0, x1))


def _x_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return min(a1, b1) - max(a0, b0) >= _X_OVERLAP_MIN


def horizontal_lines_from_page(page: Any) -> list[dict[str, float | int | str]]:
    """Detecta traços horizontais via get_drawings() (paths 'l' e 're' finos)."""
    found: list[dict[str, float | int | str]] = []
    for path in page.get_drawings():
        for item in path.get("items") or []:
            kind = item[0]
            seg: tuple[float, float, float] | None = None
            if kind == "l":
                seg = _segment_from_line(item[1], item[2])
            elif kind == "re":
                seg = _segment_from_rect(item[1])
            if seg is None:
                continue
            y, x0, x1 = seg
            found.append(
                {
                    "page": page.number + 1,
                    "y": round(y, 2),
                    "x0": round(x0, 2),
                    "x1": round(x1, 2),
                    "width": round(x1 - x0, 2),
                    "kind": kind,
                }
            )
    found.sort(key=lambda s: (s["page"], s["y"], s["x0"]))
    return found


def _page_text_with_hline_markers(page: Any) -> str:
    """Texto da página com HLINE_MARKER onde há traço horizontal entre linhas."""
    hlines = horizontal_lines_from_page(page)
    used: set[int] = set()
    data = page.get_text("dict") or {}
    parts: list[str] = []
    prev: dict[str, float] | None = None
    margin_x0: float | None = None

    for block in data.get("blocks") or []:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            spans = line.get("spans") or []
            text = "".join(str(s.get("text") or "") for s in spans)
            bbox = line.get("bbox")
            if not bbox:
                continue
            x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            curr = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}

            if prev is not None:
                # Só injeta marcador entre linhas da mesma coluna (overlap em X).
                same_column = _x_overlap(prev["x0"], prev["x1"], curr["x0"], curr["x1"])
                if same_column and prev["y1"] <= curr["y0"] + _Y_TOL:
                    for i, hl in enumerate(hlines):
                        if i in used:
                            continue
                        hy = float(hl["y"])
                        hx0, hx1 = float(hl["x0"]), float(hl["x1"])
                        if not (prev["y1"] - _Y_TOL <= hy <= curr["y0"] + _Y_TOL):
                            continue
                        if not (
                            _x_overlap(prev["x0"], prev["x1"], hx0, hx1)
                            or _x_overlap(curr["x0"], curr["x1"], hx0, hx1)
                        ):
                            continue
                        parts.append(f"\n{HLINE_MARKER}")
                        used.add(i)
                        margin_x0 = None
                parts.append("\n")

            if margin_x0 is None or abs(x0 - margin_x0) > _COL_SWITCH_PT:
                margin_x0 = x0
            if x0 >= margin_x0 + _PARA_INDENT_PT:
                text = f"\t{text}"
            else:
                margin_x0 = min(margin_x0, x0)

            parts.append(text)
            prev = curr

    return "".join(parts)


def extract_text(path: Path | str) -> str:
    """Extrai texto de todas as páginas e normaliza whitespace leve."""
    import pymupdf

    pdf_path = Path(path)
    
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")

    parts: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            parts.append(_page_text_with_hline_markers(page))

    text = "\n".join(parts)
    
    matches = []
    if 'ADAPAR_PR_20' in str(pdf_path) or '2020' in str(pdf_path):
        print(str(pdf_path))
        pattern = re.compile(r"(?:\n\t|\n)\s*Questão\s+\d+[\s\S]*?(?=(?:\n\t|\n)\s*Questão\s+\d+|CEBRASPE|--|$)", flags=re.IGNORECASE)
        matches = list(pattern.finditer(text))
        
        for match in matches:
            print(f"Match found at {match.start(0)}-{match.end(0)}:")
            print(match.group())

    _ASSERTIVA = r"[A-ZÀ-Ü\"'(]"
    _ITEM_START = rf"^\s*\d{{1,3}}(?:\s*$|\s+{_ASSERTIVA})"


    #text = text.replace("\r\n", "\n").replace("\r", "\n")
    #text = re.sub(r"[ \t]+\n", "\n", text)
    #text = re.sub(r"\n{3,}", "\n\n", text)
    # text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
