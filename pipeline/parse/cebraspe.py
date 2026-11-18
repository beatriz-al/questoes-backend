"""Parser heurístico Cebraspe (múltipla escolha e CERTO/ERRADO).

JSON de saída agrupa por enunciado-contexto:

  {
    "enunciado_principal": "Acerca dos crimes... julgue os itens...",
    "itens": [
      {"numero": 51, "enunciado": "...", "gabarito": "E"},
      {"numero": 52, "enunciado": "...", "gabarito": "E"}
    ],
    "alternativas": [{"letra": "C", "texto": "Certo"}, ...]
  }
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .pdf_reader import HLINE_MARKER, extract_text
from .types import (
    Alternativa,
    GrupoQuestao,
    ItemGabarito,
    ParseMeta,
    ParseResult,
    QuestaoExtraida,
)
from ._common import (
    SECTION_HINT,
    build_questao,
    detect_area,
    extract_alternativas,
    join_context_lines,
    keywords_from_text,
    normalize_space,
    parse_gabarito_map,
    slugify,
)

# Aceita: "118", "118.", "118)", "118 Texto", "118. Texto"
ITEM_LINE = re.compile(r"^\s*(\d{1,3})(?:\s*[.)\-–—])?(?:\s+(.*))?$")

# Bloco de texto de apoio Cebraspe (ex.: "Texto CB1A1AAA" / "Text CB1A5AAA")
TEXTO_LABEL = re.compile(r"(?i)^\s*Text(?:o)?\s+\S+")

# Fim do corpo do texto / início do comando sobre ele
TEXTO_CMD = re.compile(
    r"(?i)\b(?:"
    r"julgue\b|juzgue\b|judge\b|"
    r"considerando\s+(?:os\s+)?aspectos|"
    r"a\s+respeito\s+d|"
    r"en\s+relaci[oó]n\s+(?:al|con)\s+(?:el\s+)?texto|"
    r"with\s+regard\s+to\s+(?:the\s+)?text|"
    r"based\s+on\s+(?:the\s+)?(?:text|passage)|"
    r"according\s+to\s+(?:the\s+)?(?:text|passage)"
    r")"
)

# Numeração de margem nos textos longos: 1, 4, 7, 10…
LINE_NUM_ONLY = re.compile(r"^\d{1,2}$")

# Referência a texto de apoio dentro do enunciado ("texto CB1A1")
TEXTO_REF = re.compile(r"(?i)\btexto\s+(\S+)")
# Rótulo isolado de bloco de apoio (ex.: "Texto CB1A1" — não frases que citam o texto)
TEXTO_BLOCK_LABEL = re.compile(r"^\s*Text(?:o)?\s+[A-Z][A-Z0-9]+\s*$", re.I)

CONTEXT_START = re.compile(
    r"(?i)^\s*(?:"
    r"acerca\b|julgue\b|com\s+base\b|[aà]\s+luz\b|"
    r"no\s+que\s+se\s+refere\b|considerando\b|com\s+rela[cç][aã]o\b|"
    r"relativamente\b|ainda\s+com\s+base\b|tendo\s+como\b|"
    r"segundo\s+o\b|de\s+acordo\b|com\s+respeito\b|"
    r"em\s+rela[cç][aã]o\b|quanto\s+[aà]o?\b|"
    r"a\s+partir\b|a\s+respeito\b|com\s+refer[eê]ncia\b|"
    r"a\s+tabela\b|o\s+texto\b|com\s+respeito\b|"
    r"texto\s+\S+"
    r")"
)

SKIP_LINE = re.compile(
    r"(?i)^\s*(?:"
    r"\|\|.*\|\|"
    r"|cespe\s*\|"
    r"|cebraspe"
    r"|aplica[cç][aã]o\s*:"
    r"|cargo\s+\d+"
    r"|espa[cç]o\s+livre"
    r"|www\."
    r"|https?://"
    r"|p[aá]gina\s+\d+"
    r")",
)

ALTS_CERTO_ERRADO = [
    Alternativa(letra="C", texto="Certo"),
    Alternativa(letra="E", texto="Errado"),
]


def strip_text_line_numbers(text: str) -> str:
    """Remove a contagem de linhas (1, 4, 7…) dentro de blocos 'Texto CBxxx'."""
    lines = (text or "").splitlines()
    out: list[str] = []
    in_texto = False
    for line in lines:
        s = line.strip()
        if TEXTO_LABEL.match(s):
            in_texto = True
            out.append(line)
            continue
        if in_texto and TEXTO_CMD.search(s):
            in_texto = False
            out.append(line)
            continue
        if in_texto and LINE_NUM_ONLY.match(s):
            continue
        # Número colado no início da linha do texto: "4internacional" / "1 No começo"
        if in_texto:
            glued = re.match(r"^(\d{1,2})(\s*)(\S.*)$", s)
            if glued:
                n = int(glued.group(1))
                rest = glued.group(3)
                # típico de margem (1+3k) seguido de continuação minúscula ou palavra
                if (
                    n <= 40
                    and n % 3 == 1
                    and (rest[:1].islower() or glued.group(2) == "")
                ):
                    out.append(rest)
                    continue
        out.append(line)
    return "\n".join(out)


@dataclass
class _RawItem:
    numero: int
    texto: str
    contexto: str
    area: str


@dataclass
class _ParseState:
    area: str = "Geral"
    contexto: str = ""
    contexto_buf: list[str] = field(default_factory=list)
    item_num: int | None = None
    item_buf: list[str] = field(default_factory=list)
    in_item: bool = False
    items: list[_RawItem] = field(default_factory=list)
    last_item_num: int | None = None

    def flush_contexto_buf(self) -> None:
        if self.contexto_buf:
            self.contexto = join_context_lines(self.contexto_buf)
            self.contexto_buf.clear()

    def flush_item(self) -> None:
        if self.item_num is None:
            return
        texto = normalize_space(" ".join(self.item_buf))
        if texto:
            self.items.append(
                _RawItem(
                    numero=self.item_num,
                    texto=texto,
                    contexto=self.contexto,
                    area=self.area,
                )
            )
            self.last_item_num = self.item_num
        self.item_num = None
        self.item_buf.clear()
        self.in_item = False


def _item_num_from_match(m: re.Match[str]) -> tuple[int, str]:
    num = int(m.group(1))
    rest = (m.group(2) or "").strip()
    return num, rest


def _starts_like_assertiva(text: str, *, allow_formula: bool = False) -> bool:
    """Assertiva Cebraspe começa com maiúscula (ou aspas/parêntese)."""
    s = (text or "").lstrip()
    if not s:
        return False
    if allow_formula and s[0] == ".":
        return True
    return bool(re.match(r"^[A-ZÀ-Ü“\"(]", s))


def _is_plausible_item(
    num: int,
    last_num: int | None,
    rest: str,
    next_line: str = "",
) -> bool:
    """Evita células de tabela (22, 18, 0…) e numeração de margem virarem itens."""
    if not (1 <= num <= 200):
        return False
    # Número sozinho: a assertiva costuma estar na linha seguinte
    if not rest:
        nxt = (next_line or "").strip()
        if last_num is None:
            return _starts_like_assertiva(nxt)
        if not (last_num < num <= last_num + 5):
            return False
        # Em sequência: aceita maiúscula ou resíduo de fórmula (ex.: ".")
        return _starts_like_assertiva(nxt, allow_formula=True)
    # Com texto: rejeita salto para trás (típico de tabela)
    if last_num is not None and num < last_num:
        return False
    # Texto de item Cebraspe costuma começar com letra maiúscula
    if not _starts_like_assertiva(rest):
        return False
    return True


def _item_done(buf: list[str]) -> bool:
    """Assertiva parece concluída (termina com pontuação)."""
    if not buf:
        return False
    return bool(re.search(r"[.!?…][”\"]?\s*$", buf[-1].rstrip()))


def _prepare_context_line(raw: str) -> str | None:
    """Normaliza linha do PDF preservando marcador de parágrafo (tab inicial)."""
    line = raw.rstrip()
    if not line.strip():
        return None
    if line.startswith("\t"):
        return "\t" + line.lstrip("\t").strip()
    return line.strip()


# Início típico de assertiva Cebraspe (maiúscula / aspas / parêntese).
# Evita partir "52" → "5"+"2" ou "2018" → "18".
_ASSERTIVA = r"[A-ZÀ-Ü\"'(]"


#
# Âncora: início do texto OU newline (opcional tab) antes de "Questão N"
# Fim: próxima "Questão N" / CEBRASPE / "--" / fim do texto
QUESTAO_OBJETIVA_RE = re.compile(
    r"(?:^|(?:\n\t|\n))\s*Quest(?:ão|ao)\s+(\d{1,3})\s*"
    r"([\s\S]*?)"
    r"(?=(?:\n\t|\n)\s*Quest(?:ão|ao)\s+\d+|CEBRASPE|--|\Z)",
    flags=re.IGNORECASE | re.DOTALL,
)



def split_cebraspe_blocks(text: str) -> list[_RawItem]:
    """Separa o texto em itens via HLINE_ITEM_RE (Certo/Errado + traços).

    Fluxo direto:
      1. Remove numeração de margem dos blocos "Texto CBxxx".
      2. Sem <<<HLINE>>> → fallback linha a linha.
      3. Aplica HLINE_ITEM_RE e monta _RawItem.
      4. Itens seguintes herdam o último contexto válido (mesmo grupo).
      5. Se o regex não achar nada útil → fallback linha a linha.
    """
    text = strip_text_line_numbers(text)
    
    # Sem traço horizontal no PDF: layout diferente → parser antigo.
    if HLINE_MARKER not in text:
        return _split_cebraspe_blocks_lines(text)

    area_conhecimento = detect_area(text[:3000])
    itens: list[_RawItem] = []

    bloco_re = re.compile(r"(?:<<<HLINE>>>|^)\n*([\s\S]*?)(?=\n*(?:<<<HLINE>>>|$))"
    r"(?:\n\t|\n)\s*Questão\s+\d+[\s\S]*?(?=(?:\n\t|\n)\s*Questão\s+\d+|CEBRASPE|--|$)"
    )
    #(?:QUESTÃO\s+\d+|<<<HLINE>>>)\s*([\s\S]*?)(?=\n*(?:QUESTÃO\s+\d+|<<<HLINE>>>|$)) 
    #r"(?:QUESTÃO\s+\d+|<<<HLINE>>>)\s*([\s\S]*?)(?=\n*(?:QUESTÃO\s+\d+|<<<HLINE>>>|$))"gm
    #r"(?:<<<HLINE>>>|^)\n*([\s\S]*?)(?=\n*(?:<<<HLINE>>>|$))"gm
    padrao_quebra_linha = re.compile(r"(?<=[^\s])\n\t(?=[^\s])")
    padrao_itens = re.compile(
        rf"\n(\d{{1,3}}(?:\s*\n|\s+(?={_ASSERTIVA}))[\s\S]*?)"
        rf"(?=\n\d{{1,3}}(?:\s*\n|\s+(?={_ASSERTIVA}))|$)",
        re.MULTILINE,
    )
    padrao_alternativas = re.compile(
        rf"(?:\n|^)([A-E])\n\t([\s\S]*?)(?=\n[A-E]\n\t|\n*(?:QUESTÃO\s+\d+|<<<HLINE>>>|$))",
        re.MULTILINE,
    )
    for match in bloco_re.finditer(text):
        for bloco in match.groups():
            """print(f"\n\nBloco {bloco_num} found at {match.start(bloco_num)}-{match.end(bloco_num)}:")"""
            bloco = padrao_quebra_linha.sub(" ", bloco)
            bloco = bloco.replace("Espaço livre", "")
            enunciado = padrao_alternativas.sub("", bloco).strip()
            # enunciado = enunciado.split(area_conhecimento)[-1]
            alternativas_bloco = padrao_itens.findall(bloco)
            if not alternativas_bloco:
                alternativas_bloco = padrao_alternativas.findall(bloco)
            
            print("\n\nEnunciado:")
            print(enunciado)
            print("\n\nAlternativas:")
            print(alternativas_bloco)
            last_num: int | None = None
            for alt in alternativas_bloco:
                print(alt)
                item_m = ITEM_LINE.match(alt.strip())
                if not item_m:
                    continue
                num, alternativa = _item_num_from_match(item_m)
                if not _is_plausible_item(num, last_num, alternativa):
                    continue
                itens.append(
                    _RawItem(
                        numero=num,
                        texto=alternativa,
                        contexto=enunciado,
                        area=area_conhecimento,
                    )
                )
                last_num = num

    if itens:
        return itens
    return _split_cebraspe_blocks_lines(text)


def _split_cebraspe_blocks_lines(text: str) -> list[_RawItem]:
    """Fallback linha a linha (sem traços horizontais no PDF)."""
    text = strip_text_line_numbers(text)
    state = _ParseState(area=detect_area(text[:2500]))
    lines = [
        prepared
        for raw in (text or "").splitlines()
        if (prepared := _prepare_context_line(raw))
    ]

    def _new_contexto(first_line: str) -> None:
        state.flush_item()
        state.contexto = ""
        state.contexto_buf = [first_line] if first_line else []
        state.in_item = False

    for i, line in enumerate(lines):
        # Traço horizontal = novo bloco temático
        if line == HLINE_MARKER:
            state.flush_item()
            state.contexto = ""
            state.contexto_buf.clear()
            state.in_item = False
            continue

        if SKIP_LINE.search(line):
            continue

        sec = SECTION_HINT.match(line)
        if sec:
            state.flush_item()
            state.contexto = ""
            state.contexto_buf.clear()
            state.area = normalize_space(sec.group(1)).title()
            state.last_item_num = None
            state.in_item = False
            continue

        if TEXTO_LABEL.match(line):
            _new_contexto(line)
            continue

        item_m = ITEM_LINE.match(line)
        if item_m:
            num, rest = _item_num_from_match(item_m)
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            if _is_plausible_item(num, state.last_item_num, rest, next_line):
                state.flush_contexto_buf()
                state.flush_item()
                state.item_num = num
                state.item_buf = [rest] if rest else []
                state.in_item = True
                continue

        if state.in_item:
            # Troca de enunciado sem HLINE (coluna / "Julgue…" solto)
            if _item_done(state.item_buf) and (
                CONTEXT_START.match(line) or TEXTO_LABEL.match(line)
            ):
                _new_contexto(line)
                continue
            state.item_buf.append(line)
            continue

        # Fora de item: tudo vira enunciado-contexto até o 1º número
        state.contexto_buf.append(line)

    state.flush_contexto_buf()
    state.flush_item()
    return state.items


def _is_certo_errado(body: str) -> bool:
    return not (
        re.search(r"(?m)^\s*[A-E]\s*[)\]\-–—.]\s*", body or "")
        or re.search(r"(?m)^\s*[A-E]\s+(?=\S)", body or "")
    )


def extract_texto_blocks(text: str) -> dict[str, str]:
    """Mapeia rótulo (ex.: CB1A1) → corpo do texto de apoio Cebraspe."""
    text = strip_text_line_numbers(text)
    blocks: dict[str, str] = {}
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not TEXTO_BLOCK_LABEL.match(s):
            i += 1
            continue
        label_m = re.search(r"(\S+)\s*$", s)
        label = (label_m.group(1) if label_m else s).upper()
        buf: list[str] = []
        i += 1
        while i < len(lines):
            raw = lines[i]
            st = raw.strip()
            if st == HLINE_MARKER:
                break
            if TEXTO_BLOCK_LABEL.match(st):
                break
            if re.match(r"(?i)^\s*quest[aã]o\s+\d", st):
                break
            prep = _prepare_context_line(raw)
            if prep:
                buf.append(prep)
            i += 1
        body = join_context_lines(buf)
        blocks[label] = f"{s}\n\n{body}" if body else s
    return blocks


def split_questao_objetiva_blocks(text: str) -> list[tuple[int, str]]:
    """Separa blocos 'Questão N' via QUESTAO_OBJETIVA_RE (prova objetiva).

    Fluxo direto: um match do regex = uma questão (número + corpo).
    """
    blocks: list[tuple[int, str]] = []
    seen: set[int] = set()
    for m in QUESTAO_OBJETIVA_RE.finditer(text or ""):
        num = int(m.group(1))
        # Faixa típica de prova; evita duplicata se o regex sincronizar duas vezes.
        if not (1 <= num <= 200) or num in seen:
            continue
        body = (m.group(2) or "").strip()
        if body:
            blocks.append((num, body))
            seen.add(num)
    return blocks


def parse_multipla_escolha(
    text: str,
    gab_map: dict[int, str],
    meta: ParseMeta,
) -> tuple[list[QuestaoExtraida], list[str]]:
    """Prova objetiva Cebraspe: Questão N + alternativas A–E (sem HLINE).

    Fluxo direto:
      1. Remove numeração de margem dos blocos "Texto CBxxx".
      2. QUESTAO_OBJETIVA_RE → (número, corpo) por questão.
      3. extract_alternativas separa enunciado e A–E.
      4. build_questao monta o objeto final.
    """
    text = strip_text_line_numbers(text)
    area = detect_area(text[:2500])
    textos = extract_texto_blocks(text)
    erros: list[str] = []
    questoes: list[QuestaoExtraida] = []

    for numero, body in split_questao_objetiva_blocks(text):
        # body = enunciado + alternativas (tudo que veio depois de "Questão N")
        enunciado, alts = extract_alternativas(body)
        if not enunciado:
            erros.append(f"Q{numero}: enunciado vazio")
            continue
        if len(alts) < 2:
            erros.append(f"Q{numero}: alternativas insuficientes ({len(alts)})")
            continue

        # Texto de apoio referenciado no enunciado ("… texto CB1A1 …")
        contexto: str | None = None
        ref = TEXTO_REF.search(enunciado)
        if ref:
            key = ref.group(1).upper().rstrip(".,;:")
            contexto = textos.get(key)

        gab = (gab_map.get(numero, "") or "").upper()[:1]
        questoes.append(
            build_questao(
                numero=numero,
                enunciado=enunciado,
                enunciado_principal=contexto,
                alternativas=alts,
                gabarito=gab,
                meta=meta,
                area=area,
                assunto=area if area != "Geral" else None,
            )
        )
    return questoes, erros


def _prova_label(meta: ParseMeta, area: str) -> str:
    base = meta.prova_label or " - ".join(
        p for p in (meta.banca, meta.orgao, meta.cargo, meta.ano) if p
    )
    if area and area != "Geral" and area not in base:
        return f"{base} - {area}"
    return base


def _group_id(meta: ParseMeta, area: str, first_num: int) -> str:
    parts = [slugify(meta.prova_id)]
    if meta.tipo:
        parts.append(slugify(meta.tipo))
    elif area and area != "Geral":
        parts.append(slugify(area))
    parts.append(f"q{first_num}")
    return "-".join(parts)


def group_raw_items(
    raw_items: list[_RawItem],
    gab_map: dict[int, str],
    meta: ParseMeta,
) -> tuple[list[GrupoQuestao], list[QuestaoExtraida], list[str]]:
    """Agrupa itens pelo mesmo enunciado-contexto; também gera lista flat p/ DB."""
    grupos: list[GrupoQuestao] = []
    flat: list[QuestaoExtraida] = []
    erros: list[str] = []

    current: GrupoQuestao | None = None
    current_key: tuple[str, str] | None = None
    current_kw_parts: list[str] = []

    def _finalize_keywords(grupo: GrupoQuestao, parts: list[str]) -> None:
        grupo.keywords = keywords_from_text(" ".join(parts), limit=5)

    for raw in raw_items:
        item_texto, alts = extract_alternativas(raw.texto)
        if not item_texto:
            item_texto = raw.texto
        if not item_texto:
            erros.append(f"Q{raw.numero}: enunciado vazio")
            continue
        # confirmar se isso é necessário
        if not alts and _is_certo_errado(raw.texto):
            alts = list(ALTS_CERTO_ERRADO)

        gab = (gab_map.get(raw.numero, "") or "").upper()[:1]
        key = (raw.contexto, raw.area)

        if current is None or key != current_key:
            if current is not None:
                _finalize_keywords(current, current_kw_parts)
            current_key = key
            current_kw_parts = [raw.contexto or "", item_texto]
            current = GrupoQuestao(
                id=_group_id(meta, raw.area, raw.numero),
                enunciado_principal=raw.contexto or "",
                itens=[],
                alternativas=alts or list(ALTS_CERTO_ERRADO),
                banca=meta.banca,
                prova=_prova_label(meta, raw.area),
                area=raw.area or "Geral",
                assunto=raw.area if raw.area != "Geral" else None,
                keywords=[],
                arquivo=meta.arquivo or None,
            )
            grupos.append(current)
        else:
            current_kw_parts.append(item_texto)

        current.itens.append(
            ItemGabarito(numero=raw.numero, enunciado=item_texto, gabarito=gab)
        )

        flat.append(
            build_questao(
                numero=raw.numero,
                enunciado=item_texto,
                enunciado_principal=raw.contexto or None,
                alternativas=current.alternativas,
                gabarito=gab,
                meta=meta,
                area=raw.area or "Geral",
                assunto=raw.area if raw.area != "Geral" else None,
            )
        )

    if current is not None:
        _finalize_keywords(current, current_kw_parts)

    return grupos, flat, erros


class CebraspeParser:
    banca = "Cebraspe"

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

        raw_items = split_cebraspe_blocks(text)
        if raw_items:
            grupos, flat, erros = group_raw_items(raw_items, gab_map, meta)
            result.grupos = grupos
            result.questoes = flat
            result.erros.extend(erros)
        else:
            questoes, erros = parse_multipla_escolha(text, gab_map, meta)
            if not questoes:
                result.erros.append(f"Nenhuma questão encontrada em {prova_pdf.name}")
            else:
                result.questoes = questoes
            result.erros.extend(erros)
        return result
