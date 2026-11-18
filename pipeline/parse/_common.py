"""Utilitários compartilhados pelos parsers heurísticos."""

from __future__ import annotations

import re
import unicodedata

from .types import Alternativa, ParseMeta, QuestaoExtraida

QUESTION_START = re.compile(
    # "Questão 12.", "12)", "12 -" OU número sozinho na linha (Cebraspe C/E)
    r"(?m)^\s*(?:quest[aã]o\s+)?(\d{1,3})(?:\s*[.)\-–—]\s+|\s*$)\s*",
    re.I,
)
ALT_LINE = re.compile(
    r"(?m)^\s*([A-E])\s*[)\]\-–—.]\s*(.+?)(?=\n\s*[A-E]\s*[)\]\-–—.]|\n\s*(?:quest[aã]o\s*)?\d{1,3}\s*[.)\-–—]|\Z)",
    re.S,
)
# Cebraspe objetiva: "A texto" (sem ) ou . após a letra), com continuação em linhas recuadas
ALT_LINE_LOOSE = re.compile(
    r"(?m)^\s*([A-E])\s+(?:[)\]\-–—.]\s*)?(.+?)(?=\n\s*[A-E]\s+(?:[)\]\-–—.]|\S)|\n\s*(?:quest[aã]o\s*)?\d{1,3}\b|\Z)",
    re.S,
)
_ALT_PUNCT = re.compile(r"(?m)^\s*[A-E]\s*[)\]\-–—.]\s*")
_ALT_LOOSE = re.compile(r"(?m)^\s*[A-E]\s+(?=\S)")
SECTION_HINT = re.compile(
    r"(?mi)^\s*(língua\s+(?:portuguesa|inglesa|espanhola)|portugu[eê]s|matem[aá]tica|"
    r"racioc[ií]nio\s+l[oó]gico|direito\s+\w+|inform[aá]tica|"
    r"conhecimentos\s+(?:gerais|espec[ií]ficos|b[aá]sicos)|"
    r"atualidades|hist[oó]ria|geografia|ingl[eê]s|espanhol)\s*$"
)
GAB_ENTRY = re.compile(
    r"(?m)(?:quest[aã]o\s*)?(\d{1,3})\s*[:.\-)–—]?\s*([A-E]|Certo|Errado|C|E)\b",
    re.I,
)
KEYWORD_SPLIT = re.compile(r"[^\wÀ-ÿ]+", re.UNICODE)

# Conectores permitidos no meio de uma expressão ("crime de dano", "difusão de doença ou praga")
_KEYWORD_CONNECTORS = frozenset(
    {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "ou",
        "a",
        "o",
        "as",
        "os",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "ao",
        "à",
        "às",
        "aos",
        "para",
        "com",
        "por",
        "pelo",
        "pela",
        "contra",
        "n",
        "º",
        "nº",
    }
)

_STOPWORDS = frozenset(
    {
        "a",
        "o",
        "os",
        "as",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "um",
        "uma",
        "uns",
        "umas",
        "para",
        "com",
        "por",
        "que",
        "se",
        "ao",
        "aos",
        "à",
        "às",
        "como",
        "mais",
        "mas",
        "ou",
        "pelo",
        "pela",
        "pelos",
        "pelas",
        "seu",
        "sua",
        "seus",
        "suas",
        "é",
        "ser",
        "são",
        "foi",
        "sendo",
        "este",
        "esta",
        "esse",
        "essa",
        "isso",
        "isto",
        "aquele",
        "aquela",
        "ele",
        "ela",
        "eles",
        "elas",
        "lhe",
        "lhes",
        "não",
        "sim",
        "já",
        "também",
        "ainda",
        "muito",
        "pouco",
        "todo",
        "toda",
        "todos",
        "todas",
        "cada",
        "sobre",
        "entre",
        "após",
        "antes",
        "durante",
        "quando",
        "onde",
        "qual",
        "quais",
        "cujo",
        "cuja",
        "assim",
        "apenas",
        "somente",
        "pode",
        "podem",
        "deve",
        "devem",
        "há",
        "ter",
        "tem",
        "tendo",
        "sido",
        "fora",
        "será",
        "seria",
        "julgue",
        "itens",
        "seguintes",
        "seguir",
        "seguem",
        "acerca",
        "respeito",
        "base",
        "disposto",
        "disposta",
        "seguinte",
        "aseguir",
        "certo",
        "errado",
        "situação",
        "hipotética",
        "assertiva",
        "nessa",
        "neste",
        "nesse",
        "aquela",
        "abaixo",
        "acima",
        "conforme",
        "segundo",
        "mediante",
        "através",
        "qualquer",
        "outras",
        "outros",
        "outra",
        "outro",
        "mesmo",
        "mesma",
        "tais",
        "tal",
        "vez",
        "vezes",
        "ano",
        "anos",
        "tipo",
        "tipos",
        "forma",
        "modo",
        "caso",
        "casos",
        "pois",
        "porque",
        "considerado",
        "considerada",
        "considerados",
        "consideradas",
        "configura",
        "configuram",
        "tutelado",
        "tutelada",
        "admite",
        "admitem",
        "praticado",
        "praticada",
        "passou",
        "realizar",
        "realizou",
        "seja",
        "sejam",
        "sendo",
        "haverá",
        "havendo",
        "quanto",
        "mediante",
        "trata",
        "tratando",
        "refere",
        "seguem",
        "aseguir",
        "pratica",
        "praticar",
        "ministrar",
        "medicamentos",
        "marcos",
        "gustavo",
        "flávio",
        "flavio",
        "alberto",
        "cício",
        "cicio",
    }
)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def join_context_lines(lines: list[str]) -> str:
    """Junta linhas de enunciado-contexto preservando parágrafos.

    Linhas prefixadas com ``\\t`` (recuo detectado no PDF) iniciam novo parágrafo.
    Demais linhas consecutivas são fundidas com espaço (quebra de linha do PDF).
    """
    if not lines:
        return ""
    paragraphs: list[str] = []
    current: list[str] = []

    for line in lines:
        is_new_para = line.startswith("\t")
        chunk = line.lstrip("\t").strip()
        if not chunk:
            continue
        if is_new_para and current:
            paragraphs.append(normalize_space(" ".join(current)))
            current = [chunk]
        else:
            current.append(chunk)

    if current:
        paragraphs.append(normalize_space(" ".join(current)))

    return "\n\n".join(paragraphs)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return text.strip("-") or "item"


# Conectores típicos de termo ("crime de dano", "gestão por processos")
_TERM_CONNECTORS = frozenset(
    {"de", "da", "do", "das", "dos", "por", "contra", "à", "ao"}
)

# Sufixos nominais/adjetivais típicos de termos de prova (PT)
_NOUN_SUFFIX = re.compile(
    r"(?:ções|ção|sões|são|ões|ão|dades|dade|mentos|mento|ismos|ismo|istas|ista|"
    r"ências|ência|âncias|ância|agens|agem|uras|ura|ezas|eza|"
    r"órios|ório|órias|ória|ários|ário|árias|ária|eiro|eira|"
    r"ícios|ício|enças|ença|ancias|ancia|eses|ese|ises|ise|oses|ose)$"
)
_ADJ_SUFFIX = re.compile(
    r"(?:ais|al|ares|ar|áveis|ável|íveis|ível|icos|ico|icas|ica|"
    r"ivos|ivo|ivas|iva|osos|oso|osas|osa|anos|ano|anas|ana|"
    r"órios|ório|órias|ória|ários|ário|árias|ária|"
    r"entes|ente|antes|ante|uais|ual|eis|il)$"
)
# Verbos/advérbios/particípios que vazam no sliding window
_VERBISH = re.compile(
    r"(?:mente$"
    r"|ando$|endo$|indo$"
    r"|aram$|eram$|avam$|assem$|essem$"
    r"|ariam$|eriam$|iriam$"
    r"|izar$|onar$|ear$|utar$|atar$|ecer$"
    r"|adas$|ada$|ados$|ado$|idos$|ido$|ídos$|ído$|edas$|eda$"
    r"|ou$|ava$)$"
)

_SHORT_DOMAIN = frozenset(
    {
        "lei",
        "bem",
        "fé",
        "paz",
        "ato",
        "réu",
        "ré",
        "nexo",
        "culpa",
        "dolo",
        "pena",
        "foro",
        "junta",
        "órgão",
        "orgao",
        "crime",
        "crimes",
        "dano",
        "bens",
        "lide",
        "gestão",
        "gestao",
        "projeto",
        "projetos",
        "processo",
        "processos",
        "direito",
    }
)


def _tokenize_pt(text: str) -> list[str]:
    return [t for t in KEYWORD_SPLIT.split((text or "").lower()) if t]


def _content_score(tok: str) -> int:
    """
    Qualidade do token como núcleo de termo.
    0 = rejeita; 2 = adjetivo; 3+ = substantivo/domínio.
    """
    if tok in _STOPWORDS or tok in _KEYWORD_CONNECTORS:
        return 0
    if tok.isdigit() or len(tok) < 3:
        return 0
    if _VERBISH.search(tok):
        return 0
    if tok in _SHORT_DOMAIN:
        return 3
    if _NOUN_SUFFIX.search(tok):
        return 3
    if _ADJ_SUFFIX.search(tok):
        return 2
    # palavra longa sem cara de verbo — possível substantivo ("medicina")
    if len(tok) >= 7 and not re.search(r"(?:am|em)$", tok):
        return 2
    if len(tok) >= 6 and not re.search(r"(?:am|em)$", tok):
        return 1
    return 0


def _has_clear_morphology(tok: str) -> bool:
    return tok in _SHORT_DOMAIN or bool(_NOUN_SUFFIX.search(tok) or _ADJ_SUFFIX.search(tok))


def _phrase_ok(tokens: list[str]) -> bool:
    """
    Aceita só padrões de expressão nominal:
      CC | C k C | C C k C | C k C C | C k C k C
    Núcleo inicial deve ser substantivo (não só adjetivo solto).
    """
    n = len(tokens)
    if n < 2 or n > 5:
        return False

    scores = [_content_score(t) for t in tokens]

    def C(i: int) -> bool:
        return scores[i] > 0

    def K(i: int) -> bool:
        return tokens[i] in _TERM_CONNECTORS

    if n == 2:
        ok = C(0) and C(1)
    elif n == 3:
        ok = C(0) and K(1) and C(2)
    elif n == 4:
        ok = (C(0) and K(1) and C(2) and C(3)) or (C(0) and C(1) and K(2) and C(3))
    else:  # 5
        ok = C(0) and K(1) and C(2) and K(3) and C(4)

    if not ok:
        return False

    # head nominal: evita "típica de organizações", "jurídica de direito…"
    if scores[0] < 3 or not _has_clear_morphology(tokens[0]):
        return False

    content_scores = [s for s in scores if s > 0]
    if not content_scores or max(content_scores) < 3:
        return False

    # bigrama: segundo lado com morfologia clara (evita "processos propicia")
    if n == 2 and not _has_clear_morphology(tokens[1]):
        return False

    joined = " ".join(tokens)
    return 8 <= len(joined) <= 42


def _phrase_score(tokens: list[str]) -> int:
    """Pontua termo: prefere núcleos nominais curtos a pedaços de frase."""
    scores = [_content_score(t) for t in tokens]
    content_scores = [s for s in scores if s > 0]
    connectors = [t for t in tokens if t in _TERM_CONNECTORS]
    score = sum(content_scores) * 4

    if len(tokens) == 3 and connectors:
        score += 14
    elif len(tokens) == 2:
        score += 12
    elif len(tokens) == 4:
        score += 2
    else:
        score -= 6

    if any(t in {"de", "da", "do", "das", "dos", "por", "contra"} for t in connectors):
        score += 4

    # forte preferência por termos curtos
    score -= max(0, len(" ".join(tokens)) - 24) * 2
    return score


_SENTENCE_SPLIT = re.compile(r"(?<=[\.\!\?;:])\s+|\n+")


def keywords_from_text(text: str, limit: int = 5) -> list[str]:
    """
    Extrai poucos termos relevantes (expressões nominais) presentes no texto.

    Ex.: "incolumidade pública", "crime de dano", "exercício ilegal da profissão".
    """
    sentences = _SENTENCE_SPLIT.split(text or "")
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()

    for sent in sentences:
        tokens = _tokenize_pt(sent)
        if len(tokens) < 2:
            continue
        for n in (3, 2, 4, 5):
            for i in range(len(tokens) - n + 1):
                gram = tokens[i : i + n]
                if not _phrase_ok(gram):
                    continue
                phrase = " ".join(gram)
                if phrase in seen:
                    continue
                score = _phrase_score(gram)
                if score < 14:
                    continue
                seen.add(phrase)
                candidates.append((score, phrase))

    # melhor score; em empate, preferir o mais curto (mais "termo")
    candidates.sort(key=lambda x: (-x[0], len(x[1])))
    chosen: list[str] = []
    for _score, phrase in candidates:
        if any(phrase != other and phrase in other for other in chosen):
            continue
        subsumed = [o for o in chosen if o != phrase and o in phrase]
        for o in subsumed:
            chosen.remove(o)
        chosen.append(phrase)
        if len(chosen) >= limit:
            break

    return chosen


def _normalize_gabarito_ans(raw: str) -> str:
    ans = (raw or "").strip().upper()
    if ans in {"CERTO", "C"}:
        return "C"
    if ans in {"ERRADO", "E"}:
        return "E"
    if ans in {"A", "B", "C", "D", "E"}:
        return ans
    if ans in {"X", "*"}:  # anulado
        return "X"
    return ans[:1] if ans else ""


def _parse_gabarito_colunas(text: str) -> dict[int, str]:
    """
    Cebraspe (e similares): o PDF do gabarito extrai em colunas —
    bloco de números e, em seguida, bloco de respostas (C/E/A-E).

    Ex.:
      51\\n52\\n53\\n...\\n70\\n
      E\\nE\\nC\\n...\\nE\\n
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    mapping: dict[int, str] = {}
    i = 0
    while i < len(lines):
        nums: list[int] = []
        while i < len(lines) and re.fullmatch(r"\d{1,3}", lines[i]):
            n = int(lines[i])
            # ignora "0" solto (ruído comum nesses PDFs)
            if 1 <= n <= 200:
                nums.append(n)
            i += 1
        answers: list[str] = []
        while i < len(lines) and re.fullmatch(
            r"[A-EX]|Certo|Errado|CERTO|ERRADO",
            lines[i],
            flags=re.I,
        ):
            answers.append(_normalize_gabarito_ans(lines[i]))
            i += 1
        if nums and answers and len(nums) == len(answers):
            for n, a in zip(nums, answers):
                if a:
                    mapping[n] = a
        elif nums and answers and len(answers) >= len(nums):
            # mais respostas que números: alinha pelo início do bloco
            for n, a in zip(nums, answers):
                if a:
                    mapping[n] = a
        elif not nums and not answers:
            i += 1
    return mapping


def parse_gabarito_map(text: str) -> dict[int, str]:
    """Monta {numero: letra} a partir do texto do PDF de gabarito."""
    mapping: dict[int, str] = {}

    # 1) Formato inline: "51 C", "Questão 12: E", "3 - Certo"
    for m in GAB_ENTRY.finditer(text or ""):
        num = int(m.group(1))
        ans = _normalize_gabarito_ans(m.group(2))
        if 1 <= num <= 200 and ans:
            mapping[num] = ans

    # 2) Formato em colunas (Cebraspe) — preenche/sobrescreve o que faltou
    colunas = _parse_gabarito_colunas(text)
    if len(colunas) >= len(mapping):
        mapping.update(colunas)
    else:
        for num, ans in colunas.items():
            mapping.setdefault(num, ans)

    return mapping


def detect_area(block: str, fallback: str = "Geral") -> str:
    m = SECTION_HINT.search(block or "")
    if m:
        return normalize_space(m.group(1)).title()
    return fallback


def split_question_blocks(text: str) -> list[tuple[int, str]]:
    matches = list(QUESTION_START.finditer(text or ""))
    # Filtra números isolados fora da faixa típica de prova (reduz falsos positivos)
    filtered = []
    for m in matches:
        num = int(m.group(1))
        if 1 <= num <= 200:
            filtered.append(m)
    blocks: list[tuple[int, str]] = []
    for i, m in enumerate(filtered):
        end = filtered[i + 1].start() if i + 1 < len(filtered) else len(text)
        num = int(m.group(1))
        body = text[m.end() : end].strip()
        if body:
            blocks.append((num, body))
    return blocks


def _normalize_alt_body(text: str) -> str:
    """Funde linhas de continuação (recuo \\t) de uma alternativa."""
    parts: list[str] = []
    for line in (text or "").splitlines():
        chunk = line.lstrip("\t").strip()
        if chunk:
            parts.append(chunk)
    return normalize_space(" ".join(parts))


def extract_alternativas(body: str) -> tuple[str, list[Alternativa]]:
    """Separa enunciado e alternativas A–E (ou C/E implícito)."""
    alts: list[Alternativa] = []
    first_alt = _ALT_PUNCT.search(body or "")
    pattern = ALT_LINE
    if not first_alt:
        first_alt = _ALT_LOOSE.search(body or "")
        pattern = ALT_LINE_LOOSE
    if not first_alt:
        # Cebraspe certo/errado: enunciado inteiro, sem alternativas textuais
        return normalize_space(body), []

    stem_raw = body[: first_alt.start()]
    stem_lines = [
        ln if ln.startswith("\t") else ln.strip()
        for ln in stem_raw.splitlines()
        if ln.strip()
    ]
    enunciado = (
        join_context_lines(stem_lines)
        if any(l.startswith("\t") for l in stem_lines)
        else normalize_space(stem_raw)
    )

    chunk = body[first_alt.start() :]
    for m in pattern.finditer(chunk):
        letra = m.group(1).upper()
        texto = _normalize_alt_body(m.group(2))
        if texto:
            alts.append(Alternativa(letra=letra, texto=texto))
    return enunciado, alts


def build_questao(
    *,
    numero: int,
    enunciado: str,
    alternativas: list[Alternativa],
    gabarito: str,
    meta: ParseMeta,
    area: str = "Geral",
    assunto: str | None = None,
    enunciado_principal: str | None = None,
) -> QuestaoExtraida:
    prova = meta.prova_label or " - ".join(
        p for p in (meta.banca, meta.orgao, meta.cargo, meta.ano) if p
    )
    qid = f"{slugify(meta.prova_id)}-q{numero}"
    if meta.tipo:
        qid = f"{slugify(meta.prova_id)}-{slugify(meta.tipo)}-q{numero}"
    return QuestaoExtraida(
        id=qid,
        numero=numero,
        enunciado=enunciado,
        enunciado_principal=enunciado_principal or None,
        alternativas=alternativas,
        gabarito=(gabarito or "").upper()[:1],
        banca=meta.banca,
        prova=prova,
        area=area or "Geral",
        assunto=assunto,
        ano=meta.ano or None,
        orgao=meta.orgao or None,
        cargo=meta.cargo or None,
        keywords=keywords_from_text(
            " ".join(p for p in (enunciado_principal, enunciado) if p)
        ),
        arquivo=meta.arquivo or None,
    )
