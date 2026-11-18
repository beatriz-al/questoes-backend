#!/usr/bin/env python3
"""Baixa provas e gabaritos oficiais publicados em conhecimento.fgv.br."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup, Tag

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://conhecimento.fgv.br"
LIST_URL = f"{BASE_URL}/concursos"
DOWNLOAD_DIR = Path(__file__).resolve().parent / "provas_fgv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Listas Drupal: realizados (#paragraph-128) e em andamento (#paragraph-127)
LIST_SELECTORS = ("#paragraph-128", "#paragraph-127")

CADERNO_HINT = re.compile(
    r"\b(prova\s+objetiva(?:\s+seletiva)?|prova\s+seletiva|"
    r"prova\s+escrita(?:\s+discursiva)?|prova\s+discursiva|"
    r"prova\s+pr[aá]tica(?:\s+de\s+senten[cç]a)?|"
    r"caderno\s+de\s+quest|[cç]aderno\s+de\s+prova)\b",
    re.I,
)
GABARITO_HINT = re.compile(r"gabarito\s+oficial", re.I)
CADERNO_START = re.compile(r"^(prova|caderno)\b", re.I)
SKIP_HINT = re.compile(
    r"recurso|sess[aã]o\s+p[uú]blica|resultado|convoca|"
    r"edital|comunicado|inscri|consulta\s+individual|"
    r"interposi|resposta\s+aos|cronograma|retifica|"
    r"espelho\s+de\s+corre|rela[cç][aã]o\s+definitiva|"
    r"habilitado",
    re.I,
)
TIPO_RE = re.compile(r"tipo\s*[-_]?([0-9A-Za-z]+)", re.I)
YEAR_RE = re.compile(r"(\d{2})$")
VARIACAO_PATTERNS = (
    (re.compile(r"objetiva(?:\s+seletiva)?|prova\s+seletiva", re.I), "Objetiva"),
)
EXCLUIDAS_VARIACOES = re.compile(r"senten[cç]a|discursiva", re.I)
TIPO_VAR_RE = re.compile(r"^tipo[-\s]?(\d+)$", re.I)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    return s


def get_soup(s: requests.Session, url: str, retries: int = 3) -> BeautifulSoup:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=45)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except Exception as err:  # noqa: BLE001
            last_err = err
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Falha ao acessar {url}: {last_err}")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[()\[\]{}]", "", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return text.strip("-")


BANCA = "FGV"
TITLE_ORGAO_RE = re.compile(
    r"(?:concurso p[uú]blico(?: nacional unificado)?|"
    r"processo seletivo(?: simplificado)?|"
    r"exame(?: nacional)?(?: da magistratura)?|"
    r"exame de sufici[eê]ncia|"
    r"exame de qualifica[cç][aã]o t[eé]cnica)"
    r".*?\b(?:para|do|da|de)\s+(?:o|a|os|as)?\s*(.+)$",
    re.I,
)


def parse_org_year(slug: str) -> tuple[str, str | None]:
    slug = slug.strip("/")
    match = re.search(r"(20\d{2})$", slug) or YEAR_RE.search(slug)
    year = None
    org = slug
    if match:
        raw = match.group(1)
        if len(raw) == 4:
            year = raw
        else:
            yy = int(raw)
            year = str(2000 + yy if yy < 80 else 1900 + yy)
        org = slug[: match.start()]
    org = org.rstrip("._-").replace(".", "-")
    return slugify(org).upper(), year


def orgao_completo_from_titulo(titulo: str) -> str:
    titulo = re.sub(r"\s+", " ", titulo or "").strip()
    if not titulo:
        return ""
    match = TITLE_ORGAO_RE.search(titulo)
    if match:
        nome = match.group(1).strip(" -–—")
        nome = re.sub(r"\s+[-–—]\s+.*$", "", nome).strip()
        return nome or titulo
    return titulo


def variacao_from_row(row: dict) -> str:
    for key in ("variacao_prova", "variacao", "tipo"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    arquivo = row.get("arquivo") or ""
    match = re.search(
        r"(Tipo-\d+|Objetiva)",
        arquivo,
        re.I,
    )
    return match.group(1) if match else ""


def is_caderno_objetiva(variacao: str) -> bool:
    value = (variacao or "").strip()
    if not value or EXCLUIDAS_VARIACOES.search(value):
        return False
    if TIPO_VAR_RE.match(value) or value.lower() == "objetiva":
        return True
    return False


def item_id(orgao_abreviado: str, ano: str, cargo: str) -> str:
    return "-".join(
        part for part in (orgao_abreviado, ano, slugify(cargo)) if part
    )


def make_record(
    *,
    titulo: str,
    slug: str,
    orgao_abreviado: str,
    cargo: str,
    variacao: str,
    data: str,
    ano: str,
    categoria: str,
    arquivo: str,
    link_documento: str,
    link_acesso: str,
    extra: dict | None = None,
) -> dict:
    record = {
        "banca": BANCA,
        "data": data or "",
        "cargo": cargo or "",
        "variacao_prova": variacao or "",
        "orgao_completo": orgao_completo_from_titulo(titulo),
        "orgao_abreviado": orgao_abreviado or "",
        "link_documento": link_documento or "",
        "link_acesso": link_acesso or (f"{BASE_URL}/concursos/{slug}" if slug else ""),
        "categoria": categoria or "",
        "arquivo": arquivo or "",
        "ano": ano or "",
        "concurso": titulo or "",
        "slug": slug or "",
    }
    if extra:
        record.update({k: v for k, v in extra.items() if v})
    return record


def is_pdf_href(href: str) -> bool:
    path = urlparse(href).path.lower()
    return path.endswith(".pdf")


def abs_url(href: str) -> str:
    return urljoin(BASE_URL, href.strip())


def clean_text(node: Tag | None) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def looks_like_cargo(text: str) -> bool:
    if not text or len(text) < 3:
        return False
    if TIPO_RE.fullmatch(text.strip()):
        return False
    if CADERNO_HINT.search(text) and len(text) < 90:
        return False
    if SKIP_HINT.search(text):
        return False
    return True


def extract_tipo(text: str) -> str | None:
    compact = re.sub(r"\s+", " ", text or "").strip()
    match = re.fullmatch(r"tipo\s*[-_]?([0-9A-Za-z]+)", compact, re.I)
    if not match:
        return None
    return f"Tipo-{match.group(1)}"


def detect_variacao(text: str) -> str | None:
    for pattern, label in VARIACAO_PATTERNS:
        if pattern.search(text or ""):
            return label
    return None


def list_concursos(s: requests.Session) -> list[dict]:
    found: dict[str, dict] = {}
    page = 0
    empty_streak = 0
    while page <= 20:
        soup = get_soup(s, f"{LIST_URL}?page={page}")
        page_count = 0
        for selector in LIST_SELECTORS:
            block = soup.select_one(selector)
            if not block:
                continue
            for a in block.select(".view-content a[href]"):
                href = a.get("href") or ""
                if not re.match(r"^/concursos/[^/?#]+$", href):
                    continue
                slug = href.rstrip("/").split("/")[-1]
                if slug in found:
                    continue
                found[slug] = {
                    "slug": slug,
                    "nome": clean_text(a),
                    "url": abs_url(href),
                }
                page_count += 1
        print(f"[lista] página {page}: {page_count} concursos novos (total {len(found)})")
        if page_count == 0:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        page += 1
        time.sleep(0.4)
    return list(found.values())


def iter_arquivo_blocks(soup: BeautifulSoup) -> list[Tag]:
    container = soup.select_one(".field--name-field-concurso-arquivos")
    if not container:
        return []
    blocks: list[Tag] = []
    for item in container.find_all("div", class_="field__item", recursive=False):
        para = item.find(
            "div",
            class_=lambda c: c and "paragraph--type--texto-data" in c.split(),
        )
        if para:
            blocks.append(para)
    return blocks


def pdf_links(block: Tag) -> list[tuple[str, str]]:
    out = []
    seen = set()
    for a in block.select("a[href]"):
        href = a.get("href") or ""
        if not is_pdf_href(href):
            continue
        url = abs_url(href)
        if url in seen:
            continue
        seen.add(url)
        out.append((clean_text(a), url))
    return out


def classify_block(block: Tag, text: str, links: list[tuple[str, str]]) -> str | None:
    if not links:
        return None
    joined = " ".join([text] + [t for t, _ in links])
    if GABARITO_HINT.search(joined) and not re.search(
        r"recurso|sess[aã]o|resposta\s+aos", joined, re.I
    ):
        return "gabarito"

    has_tipo = any(extract_tipo(t) for t, _u in links)
    if has_tipo:
        return "prova"

    first_p = ""
    for p in block.select("p"):
        first_p = clean_text(p)
        if first_p:
            break
    head = first_p or text[:80]
    if CADERNO_START.search(head) and not SKIP_HINT.search(head):
        return "prova"
    return None


def cargos_from_block(block: Tag, fallback: str) -> list[str]:
    cargos: list[str] = []
    for p in block.select("p"):
        txt = clean_text(p)
        if not txt:
            continue
        if p.find("a"):
            continue
        if looks_like_cargo(txt) and not CADERNO_HINT.search(txt):
            cargos.append(txt)
    if cargos:
        return cargos
    strongs = [clean_text(s) for s in block.select("strong")]
    for txt in strongs:
        if looks_like_cargo(txt) and not CADERNO_HINT.search(txt):
            cargos.append(txt)
    return cargos or [fallback]


def parse_prova_items(block: Tag, fallback_cargo: str, variacao: str | None) -> list[dict]:
    items: list[dict] = []
    current_cargo = fallback_cargo
    paragraphs = block.select(".field--name-field-td-texto p")
    if not paragraphs:
        paragraphs = block.find_all("p")

    for p in paragraphs:
        txt = clean_text(p)
        links = pdf_links(p)
        if not links:
            if looks_like_cargo(txt) and not CADERNO_HINT.search(txt):
                current_cargo = txt
            continue
        for label, url in links:
            tipo = extract_tipo(label)
            cargo = current_cargo
            if looks_like_cargo(label) and not extract_tipo(label):
                cargo = label
            items.append(
                {
                    "cargo": cargo,
                    "tipo": tipo,
                    "variacao": tipo or variacao,
                    "url": url,
                    "label": label,
                }
            )

    if not items:
        for label, url in pdf_links(block):
            tipo = extract_tipo(label)
            items.append(
                {
                    "cargo": fallback_cargo,
                    "tipo": tipo,
                    "variacao": tipo or variacao,
                    "url": url,
                    "label": label,
                }
            )
    return items


def gabarito_rank(text: str) -> int:
    t = text.lower()
    if "definitivo" in t:
        return 3
    if "preliminar" in t:
        return 1
    return 2


def parse_concurso(soup: BeautifulSoup, concurso: dict) -> dict:
    titulo = clean_text(
        soup.select_one("article h1")
        or soup.select_one("main h1")
        or soup.select_one("h1")
    ) or concurso["nome"]
    org, year_slug = parse_org_year(concurso["slug"])

    provas: list[dict] = []
    gabaritos: list[dict] = []

    for block in iter_arquivo_blocks(soup):
        time_el = block.select_one("time")
        data_iso = time_el.get("datetime") if time_el else ""
        data_txt = clean_text(time_el)
        year = (data_iso or "")[:4] or year_slug
        text = clean_text(block)
        links = pdf_links(block)
        kind = classify_block(block, text, links)
        if kind == "prova":
            cargos = cargos_from_block(block, titulo)
            variacao = detect_variacao(text)
            for item in parse_prova_items(block, cargos[0], variacao):
                provas.append(
                    {
                        **item,
                        "data": data_txt,
                        "data_iso": data_iso,
                        "ano": year,
                        "bloco": text[:180],
                    }
                )
        elif kind == "gabarito":
            cargos = cargos_from_block(block, titulo)
            for label, url in links:
                gabaritos.append(
                    {
                        "cargo": cargos[0] if len(cargos) == 1 else titulo,
                        "tipo": extract_tipo(label),
                        "url": url,
                        "label": label,
                        "data": data_txt,
                        "data_iso": data_iso,
                        "ano": year,
                        "rank": gabarito_rank(text + " " + label),
                        "texto": text,
                    }
                )

    return {
        "org": org,
        "titulo": titulo,
        "provas": _dedupe_by_url(provas),
        "gabaritos": _dedupe_by_url(gabaritos),
        "year_slug": year_slug,
    }


def _dedupe_by_url(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for item in items:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def pick_gabarito(prova: dict, gabaritos: list[dict], titulo: str) -> dict | None:
    if not gabaritos:
        return None
    variacao = (prova.get("variacao") or "").lower()
    if variacao and not variacao.startswith("tipo") and variacao != "objetiva":
        return None
    cargo = (prova.get("cargo") or "").lower()
    tipo = prova.get("tipo")
    scored = []
    for g in gabaritos:
        score = g["rank"] * 10
        gtxt = (g.get("texto") + " " + g.get("label") + " " + g.get("cargo", "")).lower()
        if cargo and cargo[:18] in gtxt:
            score += 5
        if tipo and g.get("tipo") == tipo:
            score += 8
        if titulo.lower()[:20] in gtxt:
            score += 1
        scored.append((score, g["rank"], g))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][2]


def filename_for(org: str, ano: str, cargo: str, tipo: str | None, gabarito: bool) -> str:
    parts = [org, ano or "s-d", slugify(cargo) or "cargo"]
    if tipo:
        parts.append(slugify(tipo))
    if gabarito:
        parts.append("gabarito")
    name = "-".join(p for p in parts if p)
    return name[:180] + ".pdf"


def download_pdf(s: requests.Session, url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return False
    r = s.get(url, timeout=90, stream=True)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        for chunk in r.iter_content(8192):
            if chunk:
                fh.write(chunk)
    return True


def process_concurso(
    s: requests.Session,
    concurso: dict,
    out_dir: Path,
    dry_run: bool,
) -> list[dict]:
    soup = get_soup(s, concurso["url"])
    parsed = parse_concurso(soup, concurso)
    rows: list[dict] = []
    seen_urls: set[str] = set()

    print(f"  {parsed['org']} | {parsed['titulo']}")
    print(f"    provas={len(parsed['provas'])} gabaritos={len(parsed['gabaritos'])}")

    for prova in parsed["provas"]:
        variacao = prova.get("variacao") or prova.get("tipo") or ""
        if not is_caderno_objetiva(variacao):
            continue
        ano = prova.get("ano") or parsed["year_slug"] or "s-d"
        fname = filename_for(
            parsed["org"], ano, prova["cargo"], prova.get("variacao") or prova["tipo"], False
        )
        dest = out_dir / fname
        link_acesso = concurso["url"]
        row = make_record(
            titulo=parsed["titulo"],
            slug=concurso["slug"],
            orgao_abreviado=parsed["org"],
            cargo=prova["cargo"],
            variacao=prova.get("variacao") or prova.get("tipo") or "",
            data=prova.get("data") or "",
            ano=ano,
            categoria="prova",
            arquivo=dest.name,
            link_documento=prova["url"],
            link_acesso=link_acesso,
        )
        if prova["url"] not in seen_urls:
            seen_urls.add(prova["url"])
            if dry_run:
                print(f"    [prova] {dest.name}")
            else:
                try:
                    novo = download_pdf(s, prova["url"], dest)
                    print(f"    [{'OK' if novo else 'skip'}] {dest.name}")
                except Exception as err:  # noqa: BLE001
                    print(f"    [erro prova] {prova['url']}: {err}")
                    row["erro"] = str(err)
        rows.append(row)

        gab = pick_gabarito(prova, parsed["gabaritos"], parsed["titulo"])
        if not gab:
            continue
        gname = filename_for(
            parsed["org"], ano, prova["cargo"], prova.get("variacao") or prova["tipo"], True
        )
        gdest = out_dir / gname
        grow = make_record(
            titulo=parsed["titulo"],
            slug=concurso["slug"],
            orgao_abreviado=parsed["org"],
            cargo=prova["cargo"],
            variacao=prova.get("variacao") or prova.get("tipo") or "",
            data=prova.get("data") or gab.get("data") or "",
            ano=ano,
            categoria="gabarito",
            arquivo=gdest.name,
            link_documento=gab["url"],
            link_acesso=link_acesso,
            extra={"gabarito_label": gab.get("label") or ""},
        )
        if gab["url"] not in seen_urls or gdest.name != dest.name:
            if gab["url"] not in seen_urls:
                seen_urls.add(gab["url"])
            if dry_run:
                print(f"    [gabarito] {gdest.name}")
            else:
                try:
                    # Mesmo PDF de gabarito pode servir a vários tipos: copia o arquivo.
                    if gdest.exists() and gdest.stat().st_size > 0:
                        print(f"    [skip] {gdest.name}")
                    else:
                        same = next(
                            (
                                Path(out_dir) / r["arquivo"]
                                for r in rows
                                if r.get("categoria") == "gabarito"
                                and r.get("link_documento") == gab["url"]
                                and (Path(out_dir) / r["arquivo"]).exists()
                            ),
                            None,
                        )
                        if same and same.exists():
                            gdest.write_bytes(same.read_bytes())
                            print(f"    [copy] {gdest.name}")
                        else:
                            novo = download_pdf(s, gab["url"], gdest)
                            print(f"    [{'OK' if novo else 'skip'}] {gdest.name}")
                except Exception as err:  # noqa: BLE001
                    print(f"    [erro gabarito] {gab['url']}: {err}")
                    grow["erro"] = str(err)
        rows.append(grow)

    # Gabaritos sem prova associada (ainda assim oficiais)
    if not parsed["provas"]:
        best: dict[str, dict] = {}
        for g in parsed["gabaritos"]:
            key = (g.get("cargo"), g.get("tipo"))
            if key not in best or g["rank"] > best[key]["rank"]:
                best[key] = g
        for g in best.values():
            ano = g.get("ano") or parsed["year_slug"] or "s-d"
            gname = filename_for(parsed["org"], ano, g["cargo"], g["tipo"], True)
            gdest = out_dir / gname
            if dry_run:
                print(f"    [gabarito] {gdest.name}")
            else:
                try:
                    download_pdf(s, g["url"], gdest)
                    print(f"    [OK] {gdest.name}")
                except Exception as err:  # noqa: BLE001
                    print(f"    [erro] {g['url']}: {err}")
            rows.append(
                make_record(
                    titulo=parsed["titulo"],
                    slug=concurso["slug"],
                    orgao_abreviado=parsed["org"],
                    cargo=g["cargo"],
                    variacao=g.get("tipo") or "",
                    data=g.get("data") or "",
                    ano=ano,
                    categoria="gabarito",
                    arquivo=gdest.name,
                    link_documento=g["url"],
                    link_acesso=concurso["url"],
                )
            )

    return rows


def flatten_grouped(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    first = rows[0]
    if not isinstance(first.get("variacao_prova"), list):
        return rows
    flat: list[dict] = []
    for item in rows:
        base = {k: v for k, v in item.items() if k != "variacao_prova"}
        for var in item.get("variacao_prova") or []:
            prova_row = {
                **base,
                "categoria": "prova",
                "variacao_prova": var.get("tipo") or "",
                "link_documento": var.get("link_documento") or "",
                "arquivo": var.get("arquivo") or "",
            }
            flat.append(prova_row)
            gab = var.get("gabarito") or {}
            if gab.get("link_documento") or gab.get("arquivo"):
                flat.append(
                    {
                        **base,
                        "categoria": "gabarito",
                        "variacao_prova": var.get("tipo") or "",
                        "link_documento": gab.get("link_documento") or "",
                        "arquivo": gab.get("arquivo") or "",
                    }
                )
    return flat


def tipo_sort_key(tipo: str) -> tuple[int, str]:
    match = TIPO_VAR_RE.match((tipo or "").strip())
    if match:
        return (0, f"{int(match.group(1)):04d}")
    return (1, (tipo or "").lower())


def group_documentos(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], dict] = {}
    order: list[tuple[str, str, str, str]] = []

    for row in flatten_grouped(rows):
        if row.get("erro") and not row.get("arquivo"):
            continue
        variacao = variacao_from_row(row)
        if not is_caderno_objetiva(variacao):
            continue
        cargo = row.get("cargo") or ""
        ano = str(row.get("ano") or "")
        slug = row.get("slug") or ""
        orgao = row.get("orgao_abreviado") or row.get("orgao") or ""
        key = (slug, orgao, ano, cargo)
        if key not in grouped:
            grouped[key] = {
                "id": item_id(orgao, ano, cargo),
                "banca": row.get("banca") or BANCA,
                "data": row.get("data") or "",
                "cargo": cargo,
                "variacao_prova": {},
                "orgao_completo": row.get("orgao_completo")
                or orgao_completo_from_titulo(row.get("concurso") or ""),
                "orgao_abreviado": orgao,
                "link_acesso": row.get("link_acesso")
                or (f"{BASE_URL}/concursos/{slug}" if slug else ""),
                "categoria": "prova",
                "ano": ano,
                "concurso": row.get("concurso") or "",
                "slug": slug,
            }
            order.append(key)
        item = grouped[key]
        if row.get("data") and (
            not item["data"]
            or (TIPO_VAR_RE.match(variacao) and not TIPO_VAR_RE.match(item.get("_data_src") or ""))
        ):
            item["data"] = row["data"]
            item["_data_src"] = variacao
        tipos = item["variacao_prova"]
        if variacao not in tipos:
            tipos[variacao] = {
                "tipo": variacao,
                "link_documento": "",
                "arquivo": "",
            }
        slot = tipos[variacao]
        if (row.get("categoria") or "prova") != "gabarito":
            if row.get("link_documento"):
                slot["link_documento"] = row["link_documento"]
            if row.get("arquivo"):
                slot["arquivo"] = row["arquivo"]
        else:
            gab = slot.setdefault("gabarito", {})
            if row.get("link_documento"):
                gab["link_documento"] = row["link_documento"]
            if row.get("arquivo"):
                gab["arquivo"] = row["arquivo"]
            if row.get("gabarito_label"):
                gab["label"] = row["gabarito_label"]

    result = []
    for key in order:
        item = grouped[key]
        item.pop("_data_src", None)
        tipos = item["variacao_prova"]
        has_tipo = any(TIPO_VAR_RE.match(t) for t in tipos)
        if has_tipo:
            tipos = {k: v for k, v in tipos.items() if TIPO_VAR_RE.match(k)}
        item["variacao_prova"] = [
            tipos[k] for k in sorted(tipos, key=tipo_sort_key) if tipos[k].get("link_documento") or tipos[k].get("arquivo")
        ]
        if item["variacao_prova"]:
            result.append(item)
    return result


def record_from_indice(row: dict) -> dict:
    slug = row.get("slug") or ""
    titulo = row.get("concurso") or row.get("orgao_completo") or ""
    return make_record(
        titulo=titulo,
        slug=slug,
        orgao_abreviado=row.get("orgao_abreviado") or row.get("orgao") or "",
        cargo=row.get("cargo") or "",
        variacao=variacao_from_row(row),
        data=row.get("data") or row.get("data_prova") or "",
        ano=row.get("ano") or "",
        categoria=row.get("categoria") or "",
        arquivo=row.get("arquivo") or "",
        link_documento=row.get("link_documento") or row.get("url") or "",
        link_acesso=row.get("link_acesso") or (f"{BASE_URL}/concursos/{slug}" if slug else ""),
        extra={"gabarito_label": row.get("gabarito_label") or "", "erro": row.get("erro") or ""},
    )


def rebuild_from_indice(out_dir: Path) -> list[dict]:
    for name in ("indice.json", "provas.json"):
        path = out_dir / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, list) and data:
                return [record_from_indice(row) for row in flatten_grouped(data)]
    raise FileNotFoundError(f"Nenhum índice encontrado em {out_dir}")


def save_indices(out_dir: Path, rows: list[dict]) -> None:
    agrupados = group_documentos(rows)
    provas_path = out_dir / "provas.json"
    provas_path.write_text(
        json.dumps(agrupados, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    indice = out_dir / "indice.csv"
    flat_csv: list[dict] = []
    for item in agrupados:
        for var in item["variacao_prova"]:
            gab = var.get("gabarito") or {}
            flat_csv.append(
                {
                    "id": item["id"],
                    "banca": item["banca"],
                    "data": item["data"],
                    "cargo": item["cargo"],
                    "variacao_prova": var.get("tipo") or "",
                    "orgao_completo": item["orgao_completo"],
                    "orgao_abreviado": item["orgao_abreviado"],
                    "link_documento": var.get("link_documento") or "",
                    "arquivo": var.get("arquivo") or "",
                    "gabarito_link": gab.get("link_documento") or "",
                    "gabarito_arquivo": gab.get("arquivo") or "",
                    "link_acesso": item["link_acesso"],
                    "ano": item["ano"],
                    "concurso": item["concurso"],
                    "slug": item["slug"],
                }
            )
    if flat_csv:
        fields = list(flat_csv[0].keys())
        with indice.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(flat_csv)
        (out_dir / "indice.json").write_text(
            json.dumps(flat_csv, ensure_ascii=False, indent=2),
            encoding="utf-8-sig",
        )
    print(f"\nJSON salvo em {provas_path} ({len(agrupados)} itens)")
    print(f"Índice CSV salvo em {indice}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Scraper de provas e gabaritos FGV")
    parser.add_argument("--slug", help="Processa só um concurso, ex: csjt23")
    parser.add_argument("--limit", type=int, default=0, help="Limite de concursos")
    parser.add_argument("--dry-run", action="store_true", help="Não baixa PDFs")
    parser.add_argument(
        "--rebuild-json",
        action="store_true",
        help="Gera provas.json a partir do indice já existente, sem baixar",
    )
    parser.add_argument(
        "--out",
        default=str(DOWNLOAD_DIR),
        help="Pasta de destino (padrão: ./provas_fgv)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Não envia arquivos para o Backblaze B2 ao final",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.rebuild_json:
        rebuilt = rebuild_from_indice(out_dir)
        save_indices(out_dir, rebuilt)
        print(f"JSON reconstruído: {len(rebuilt)} registros")
        return
    s = session()

    if args.slug:
        concursos = [
            {
                "slug": args.slug,
                "nome": args.slug,
                "url": f"{BASE_URL}/concursos/{args.slug}",
            }
        ]
    else:
        concursos = list_concursos(s)

    if args.limit:
        concursos = concursos[: args.limit]

    all_rows: list[dict] = []
    for i, concurso in enumerate(concursos, 1):
        print(f"\n[{i}/{len(concursos)}] {concurso['url']}")
        try:
            rows = process_concurso(s, concurso, out_dir, args.dry_run)
            all_rows.extend(rows)
        except Exception as err:  # noqa: BLE001
            print(f"  [erro concurso] {err}")
            all_rows.append(
                {
                    "slug": concurso["slug"],
                    "url": concurso["url"],
                    "erro": str(err),
                }
            )
        time.sleep(0.35)

    save_indices(out_dir, all_rows)
    print(f"Arquivos em {out_dir}")
    print(f"Registros: {len(all_rows)}")

    if not args.dry_run and not args.skip_upload:
        from b2_upload import upload_provas_dir

        try:
            upload_provas_dir(out_dir, prefix="fgv")
        except Exception as err:  # noqa: BLE001
            print(f"[B2] falha no upload (scraping ok): {err}")


if __name__ == "__main__":
    main()
