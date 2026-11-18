#!/usr/bin/env python3
"""Baixa provas objetivas e gabaritos definitivos publicados pelo Cebraspe."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup, Tag

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://www.cebraspe.org.br"
API_BASE = "https://apis.cebraspe.org.br/cebraspe"
CDN_BASE = "https://cdn.cebraspe.org.br"
LIST_URL = f"{BASE_URL}/concursos/encerrado"
LIST_API = f"{API_BASE}/eventos/tipo/concursos"
EVENT_API = f"{API_BASE}/eventos/{{slug}}"
DOWNLOAD_DIR = Path(__file__).resolve().parent / "provas_cebraspe"
BANCA = "Cebraspe"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}

YEAR_RE = re.compile(r"(?:_|-)?(\d{2})$")
SKIP_HINT = re.compile(
    r"discursiv|padr[aã]o\s+de\s+resposta|preliminar|"
    r"justificativa|recurso|edital|comunicado|resultado|"
    r"convoca|inscri|cronograma|retifica",
    re.I,
)
GABARITO_DEF = re.compile(r"gabarito\s+definitivo", re.I)
PROVA_OBJ = re.compile(r"prova\s+objetiva", re.I)
PREFIX_RE = re.compile(
    r"^(gabarito\s+definitivo(?:\s*[–\-—:]\s*prova\s+objetiva)?|"
    r"prova\s+objetiva)\s*[–\-—:]?\s*",
    re.I,
)
CARGO_NUM_RE = re.compile(r"cargos?\s*(\d+(?:\s*[,e]\s*\d+)*)", re.I)
AREA_RE = re.compile(
    r"[áa]reas?\s*(?:de\s*)?(\d+(?:\s*(?:a|e|,)\s*\d+)*)",
    re.I,
)
ADAPT_RE = re.compile(r"(superampliada|adaptada)", re.I)
HTML_ENTITY_RE = re.compile(r"&[a-z]+;|&#\d+;", re.I)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    return s


def get_json(s: requests.Session, url: str, retries: int = 3):
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=45)
            r.raise_for_status()
            if not r.content:
                return None
            r.encoding = "utf-8"
            return json.loads(r.text)
        except Exception as err:  # noqa: BLE001
            last_err = err
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Falha ao acessar {url}: {last_err}")


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


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = HTML_ENTITY_RE.sub(" ", text)
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def clean_text(node: Tag | None) -> str:
    if node is None:
        return ""
    return html.unescape(re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip())


def decode_text(value: str | None) -> str:
    return html.unescape((value or "").strip())


def abs_url(href: str) -> str:
    return urljoin(BASE_URL, href.strip())


def is_pdf_href(href: str) -> bool:
    path = urlparse(href).path.lower()
    return path.endswith(".pdf")


def parse_org_year(slug: str, ano_api: int | None = None) -> tuple[str, str | None]:
    slug = (slug or "").strip("/")
    year = str(ano_api) if ano_api else None
    org = slug
    match = re.search(r"(20\d{2})$", slug) or YEAR_RE.search(slug)
    if match:
        raw = match.group(1)
        if not year:
            if len(raw) == 4:
                year = raw
            else:
                yy = int(raw)
                year = str(2000 + yy if yy < 80 else 1900 + yy)
        org = slug[: match.start()]
    org = org.rstrip("._-").replace(".", "-")
    return slugify(org).upper(), year


def item_id(orgao_abreviado: str, ano: str, cargo: str) -> str:
    return "-".join(part for part in (orgao_abreviado, ano, slugify(cargo)) if part)


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
        "orgao_completo": titulo or "",
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


def list_concursos_html(s: requests.Session) -> list[dict]:
    soup = get_soup(s, LIST_URL)
    container = soup.find("div", class_="itens-container")
    items = (
        container.find_all("li", class_="q_circle_outer")
        if container
        else soup.find_all("li", class_="q_circle_outer")
    )
    found: dict[str, dict] = {}
    for item in items:
        link_tag = item.find("a", class_="icon_with_title_link", href=True)
        if not link_tag:
            continue
        href = link_tag["href"]
        if not re.search(r"/concursos/[^/?#]+", href):
            continue
        slug = href.rstrip("/").split("/")[-1]
        title_tag = item.find("h3", class_="q_circle_title")
        nome = clean_text(title_tag) or slug
        found[slug] = {"slug": slug, "nome": nome, "url": abs_url(href)}
    return list(found.values())


def list_concursos_api(s: requests.Session) -> list[dict]:
    data = get_json(s, LIST_API) or []
    found: dict[str, dict] = {}
    for grupo in data:
        fase = fold(str(grupo.get("faseEvento") or ""))
        if "encerr" not in fase:
            continue
        for ev in grupo.get("eventos") or []:
            slug = (ev.get("eventoURL") or "").strip()
            if not slug:
                continue
            found[slug] = {
                "slug": slug,
                "nome": ev.get("eventoNomeAbreviado") or slug,
                "url": f"{BASE_URL}/concursos/{slug}",
                "ano": ev.get("eventoAno"),
            }
    return list(found.values())


def list_concursos(s: requests.Session) -> list[dict]:
    html_items = []
    try:
        html_items = list_concursos_html(s)
    except Exception as err:  # noqa: BLE001
        print(f"[lista] HTML indisponível ({err}); usando API.")
    if html_items:
        print(f"[lista] {len(html_items)} concursos via HTML")
        return html_items
    api_items = list_concursos_api(s)
    print(f"[lista] {len(api_items)} concursos encerrados via API")
    return api_items


def file_url(slug: str, nome_arquivo: str) -> str:
    encoded = quote(nome_arquivo, safe="._-()")
    return f"{CDN_BASE}/concursos/{slug}/arquivos/{encoded}"


def normalize_key(label: str) -> str:
    text = fold(label)
    text = PREFIX_RE.sub("", text)
    text = re.sub(r"\bprova\s+objetiva\b", "", text)
    text = re.sub(r"\bgabarito\s+definitivo\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stem_filename(nome: str) -> str:
    name = Path(nome).stem.upper()
    name = re.sub(r"^GAB[_-]?DEFINITIVO[_-]?", "", name)
    name = re.sub(r"^GAB[_-]?", "", name)
    name = re.sub(r"^MATRIZ[_-]?", "", name)
    return re.sub(r"[^A-Z0-9]+", "", name)


def is_adaptada_or_superampliada(*parts: str) -> bool:
    """Provas adaptadas/superampliadas não entram no acervo."""
    return any(ADAPT_RE.search(p or "") for p in parts)


def classify_label(label: str, nome: str = "") -> str | None:
    text = fold(label)
    if is_adaptada_or_superampliada(label, nome):
        return None
    if SKIP_HINT.search(text) and not (GABARITO_DEF.search(text) or PROVA_OBJ.search(text)):
        return None
    if "discursiv" in text or "padrao de resposta" in text or "padrão de resposta" in text:
        return None
    if "preliminar" in text:
        return None
    if GABARITO_DEF.search(text):
        return "gabarito"
    if PROVA_OBJ.search(text):
        return "prova"
    return None


def _short_cargo_name(mapped: str, numero: str) -> str:
    nome = re.sub(r"^cargo\s*\d+\s*[:\-–—]\s*", "", mapped or "", flags=re.I).strip()
    if nome and len(slugify(nome)) <= 40:
        return nome
    return f"Cargo {numero}"


def _suffix_variacao(label: str) -> str:
    parts: list[str] = []
    area = AREA_RE.search(label or "")
    if area:
        parts.append(f"Área {area.group(1).strip()}")
    return " ".join(parts)


def cargo_from_label(
    label: str,
    cargos_map: dict[str, str],
    fallback: str,
    unique_cargo: str = "",
) -> str:
    folded = fold(label)
    nums = CARGO_NUM_RE.findall(label)
    if nums:
        parts = re.split(r"\s*[,e]\s*", nums[0], flags=re.I)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) == 1:
            mapped = cargos_map.get(parts[0].zfill(2)) or cargos_map.get(parts[0]) or ""
            return _short_cargo_name(mapped, parts[0])
        return "Cargos " + ", ".join(parts)
    if "todos os cargos" in folded:
        return "Todos os cargos"
    if unique_cargo:
        return unique_cargo
    return fallback


def variacao_from_label(label: str) -> str:
    text = PREFIX_RE.sub("", (label or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" -–—:")
    suffix = _suffix_variacao(label)
    match = re.search(
        r"(conhecimentos\s+(?:b[aá]sicos|espec[ií]ficos|gerais))",
        text,
        re.I,
    )
    if match:
        base = re.sub(r"\s+", " ", match.group(1)).title()
        return f"{base} {suffix}".strip()
    leftover = re.sub(r"cargos?\s*\d+(?:\s*[,e]\s*\d+)*", "", text, flags=re.I)
    leftover = AREA_RE.sub("", leftover)
    leftover = leftover.strip(" -–—:")
    core = leftover or "Objetiva"
    return f"{core} {suffix}".strip()


def parse_arquivos_api(evento: dict, slug: str) -> list[dict]:
    arquivos = evento.get("arquivosGabarito") or []
    cargos_map: dict[str, str] = {}
    for cargo in evento.get("eventoCargos") or []:
        area = decode_text(cargo.get("area"))
        cid = str(cargo.get("idArea") or "").lstrip("0") or str(cargo.get("idArea") or "")
        if cid:
            cargos_map[cid] = area or f"Cargo {cid}"
            cargos_map[cid.zfill(2)] = area or f"Cargo {cid}"
    unique_cargos = sorted(set(cargos_map.values()))
    unique_cargo = unique_cargos[0] if len(unique_cargos) == 1 else ""
    items = []
    for arq in arquivos:
        label = decode_text(arq.get("descricaoArquivo"))
        nome = decode_text(arq.get("nomeArquivo"))
        if not nome:
            continue
        kind = classify_label(label, nome)
        if not kind:
            continue
        items.append(
            {
                "kind": kind,
                "label": label,
                "nome": nome,
                "url": file_url(slug, nome),
                "data": (arq.get("dataArquivo") or "").split(" ")[0],
                "key": normalize_key(label),
                "stem": stem_filename(nome),
                "cargo": cargo_from_label(
                    label,
                    cargos_map,
                    decode_text(evento.get("eventoNomeAbreviado")) or slug,
                    unique_cargo=unique_cargo,
                ),
                "variacao": variacao_from_label(label),
            }
        )
    if items:
        specific_urls = {
            item["url"]
            for item in items
            if item["cargo"]
            and item["cargo"] not in {decode_text(evento.get("eventoNomeAbreviado")), slug}
            and not item["cargo"].startswith("Cargos ")
        }
        fallback_names = {decode_text(evento.get("eventoNomeAbreviado")), slug}
        items = [
            item
            for item in items
            if not (item["cargo"] in fallback_names and item["url"] in specific_urls)
        ]
    return items


def parse_arquivos_html(soup: BeautifulSoup, slug: str, fallback: str) -> list[dict]:
    items = []
    for a in soup.select("ul.page-concursos__cargos-list a[href], a[href]"):
        href = a.get("href") or ""
        if not is_pdf_href(href):
            continue
        label = clean_text(a)
        nome = urlparse(href).path.split("/")[-1]
        kind = classify_label(label, nome)
        if not kind:
            continue
        items.append(
            {
                "kind": kind,
                "label": label,
                "nome": nome,
                "url": abs_url(href) if href.startswith("http") else file_url(slug, nome),
                "data": "",
                "key": normalize_key(label),
                "stem": stem_filename(nome),
                "cargo": cargo_from_label(label, {}, fallback),
                "variacao": variacao_from_label(label),
            }
        )
    return items


def pick_gabarito(prova: dict, gabaritos: list[dict]) -> dict | None:
    if not gabaritos:
        return None
    scored = []
    for g in gabaritos:
        score = 0
        if prova["key"] and g["key"] and prova["key"] == g["key"]:
            score += 50
        if prova["stem"] and g["stem"] and prova["stem"] == g["stem"]:
            score += 40
        if prova["key"] and g["key"] and (prova["key"] in g["key"] or g["key"] in prova["key"]):
            score += 15
        if prova.get("cargo") and prova["cargo"] == g.get("cargo"):
            score += 8
        scored.append((score, g))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    return best if best_score >= 15 else None


def filename_for(org: str, ano: str, cargo: str, variacao: str, gabarito: bool) -> str:
    parts = [org, ano or "s-d", slugify(cargo) or "cargo"]
    var = slugify(variacao)
    if var and var.lower() not in {slugify(cargo).lower(), "objetiva"}:
        parts.append(var)
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


def copy_or_download(
    s: requests.Session,
    url: str,
    dest: Path,
    rows: list[dict],
    out_dir: Path,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"    [gabarito] {dest.name}")
        return
    if dest.exists() and dest.stat().st_size > 0:
        print(f"    [skip] {dest.name}")
        return
    same = next(
        (
            out_dir / r["arquivo"]
            for r in rows
            if r.get("categoria") == "gabarito"
            and r.get("link_documento") == url
            and (out_dir / r["arquivo"]).exists()
        ),
        None,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    if same and same.exists():
        dest.write_bytes(same.read_bytes())
        print(f"    [copy] {dest.name}")
        return
    novo = download_pdf(s, url, dest)
    print(f"    [{'OK' if novo else 'skip'}] {dest.name}")


def process_concurso(
    s: requests.Session,
    concurso: dict,
    out_dir: Path,
    dry_run: bool,
) -> list[dict]:
    slug = concurso["slug"]
    evento = get_json(s, EVENT_API.format(slug=slug)) or {}
    titulo = (
        decode_text(evento.get("eventoNomeAbreviado"))
        or concurso.get("nome")
        or slug
    )
    org, year_slug = parse_org_year(slug, evento.get("eventoAno") or concurso.get("ano"))
    arquivos = parse_arquivos_api(evento, slug)
    if not arquivos:
        try:
            soup = get_soup(s, concurso["url"])
            arquivos = parse_arquivos_html(soup, slug, titulo)
        except Exception as err:  # noqa: BLE001
            print(f"    [!] HTML também falhou: {err}")

    provas = [a for a in arquivos if a["kind"] == "prova"]
    gabaritos = [a for a in arquivos if a["kind"] == "gabarito"]
    print(f"  {org} | {titulo}")
    print(f"    provas={len(provas)} gabaritos={len(gabaritos)}")

    rows: list[dict] = []
    seen_urls: set[str] = set()
    used_gabs: set[str] = set()
    ano = year_slug or "s-d"
    link_acesso = concurso["url"]

    for prova in provas:
        cargo = prova["cargo"]
        variacao = prova["variacao"]
        fname = filename_for(org, ano, cargo, variacao, False)
        dest = out_dir / fname
        row = make_record(
            titulo=titulo,
            slug=slug,
            orgao_abreviado=org,
            cargo=cargo,
            variacao=variacao,
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

        gab = pick_gabarito(prova, gabaritos)
        if not gab:
            continue
        used_gabs.add(gab["url"])
        gname = filename_for(org, ano, cargo, variacao, True)
        gdest = out_dir / gname
        grow = make_record(
            titulo=titulo,
            slug=slug,
            orgao_abreviado=org,
            cargo=cargo,
            variacao=variacao,
            data=prova.get("data") or gab.get("data") or "",
            ano=ano,
            categoria="gabarito",
            arquivo=gdest.name,
            link_documento=gab["url"],
            link_acesso=link_acesso,
            extra={"gabarito_label": gab.get("label") or ""},
        )
        try:
            copy_or_download(s, gab["url"], gdest, rows, out_dir, dry_run)
        except Exception as err:  # noqa: BLE001
            print(f"    [erro gabarito] {gab['url']}: {err}")
            grow["erro"] = str(err)
        rows.append(grow)

    for gab in gabaritos:
        if gab["url"] in used_gabs:
            continue
        cargo = gab["cargo"]
        variacao = gab["variacao"]
        gname = filename_for(org, ano, cargo, variacao, True)
        gdest = out_dir / gname
        grow = make_record(
            titulo=titulo,
            slug=slug,
            orgao_abreviado=org,
            cargo=cargo,
            variacao=variacao,
            data=gab.get("data") or "",
            ano=ano,
            categoria="gabarito",
            arquivo=gdest.name,
            link_documento=gab["url"],
            link_acesso=link_acesso,
            extra={"gabarito_label": gab.get("label") or ""},
        )
        try:
            copy_or_download(s, gab["url"], gdest, rows, out_dir, dry_run)
        except Exception as err:  # noqa: BLE001
            print(f"    [erro gabarito] {gab['url']}: {err}")
            grow["erro"] = str(err)
        rows.append(grow)

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


def variacao_from_row(row: dict) -> str:
    for key in ("variacao_prova", "variacao", "tipo"):
        value = (row.get(key) or "").strip()
        if value and not isinstance(value, list):
            return value
    return ""


def group_documentos(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], dict] = {}
    order: list[tuple[str, str, str, str]] = []

    for row in flatten_grouped(rows):
        if row.get("erro") and not row.get("arquivo"):
            continue
        variacao = variacao_from_row(row) or "Objetiva"
        if is_adaptada_or_superampliada(
            variacao,
            row.get("arquivo") or "",
            row.get("link_documento") or "",
            row.get("gabarito_arquivo") or "",
            row.get("gabarito_link") or "",
        ):
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
                "orgao_completo": row.get("orgao_completo") or row.get("concurso") or "",
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
        if row.get("data") and not item["data"]:
            item["data"] = row["data"]
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
        tipos = item["variacao_prova"]
        item["variacao_prova"] = [
            tipos[k]
            for k in sorted(tipos, key=lambda t: t.lower())
            if tipos[k].get("link_documento") or tipos[k].get("arquivo")
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
    parser = argparse.ArgumentParser(
        description="Scraper de provas objetivas e gabaritos definitivos Cebraspe"
    )
    parser.add_argument("--slug", help="Processa só um concurso, ex: AEB_24")
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
        help="Pasta de destino (padrão: ./provas_cebraspe)",
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
        time.sleep(1)

    save_indices(out_dir, all_rows)
    print(f"Arquivos em {out_dir}")
    print(f"Registros: {len(all_rows)}")

    if not args.dry_run and not args.skip_upload:
        from b2_upload import upload_provas_dir

        try:
            upload_provas_dir(out_dir, prefix="cebraspe")
        except Exception as err:  # noqa: BLE001
            print(f"[B2] falha no upload (scraping ok): {err}")


if __name__ == "__main__":
    main()
