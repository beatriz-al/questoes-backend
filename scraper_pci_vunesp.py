#!/usr/bin/env python3
"""Baixa provas e gabaritos VUNESP publicados em pciconcursos.com.br."""

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
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.pciconcursos.com.br"
LIST_URL = f"{BASE_URL}/provas/vunesp"
LINK_API = f"{BASE_URL}/provas/link"
DOWNLOAD_DIR = Path(__file__).resolve().parent / "provas_vunesp"
BANCA = "VUNESP"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

GAB_HINT = re.compile(r"\bgab(?:arito)?s?\b", re.I)
PARTE_RE = re.compile(r"parte[_\-\s]?([ivx\d]+)", re.I)
TIPO_RE = re.compile(r"tipo[_\-\s]?(\d+)", re.I)
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
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


def clean_text(node: Tag | None) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def abs_url(href: str) -> str:
    return urljoin(BASE_URL, href.strip())


def item_id(orgao_abreviado: str, ano: str, cargo: str) -> str:
    return "-".join(part for part in (orgao_abreviado, ano, slugify(cargo)) if part)


def orgao_abreviado_from_href(href: str) -> str:
    slug = urlparse(href).path.strip("/").split("/")[-1]
    return slugify(slug).upper() if slug else ""


def parse_org_year_from_slug(slug: str) -> tuple[str, str | None]:
    slug = slug.strip("/")
    match = re.search(r"(20\d{2})$", slug)
    if not match:
        return slugify(slug).upper(), None
    year = match.group(1)
    org = slug[: match.start()].rstrip("-_")
    return slugify(org).upper() or slugify(slug).upper(), year


def variacao_from_filename(filename: str) -> str:
    name = (filename or "").lower()
    if GAB_HINT.search(name):
        return ""
    match = PARTE_RE.search(name)
    if match:
        token = match.group(1).lower()
        if token.isdigit():
            return f"Parte-{token}"
        num = ROMAN.get(token, token.upper())
        return f"Parte-{num}"
    match = TIPO_RE.search(name)
    if match:
        return f"Tipo-{match.group(1)}"
    if re.search(r"cad[_-]?quest", name):
        return "Objetiva"
    return "Objetiva"


def is_gabarito_filename(filename: str) -> bool:
    return bool(GAB_HINT.search(filename or ""))


def filename_for(org: str, ano: str, cargo: str, variacao: str, gabarito: bool) -> str:
    parts = [org, ano or "s-d", slugify(cargo) or "cargo"]
    var = slugify(variacao)
    if var and var.lower() not in {slugify(cargo).lower(), "objetiva"}:
        parts.append(var)
    if gabarito:
        parts.append("gabarito")
    name = "-".join(p for p in parts if p)
    return name[:180] + ".pdf"


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
        "link_acesso": link_acesso or "",
        "categoria": categoria or "",
        "arquivo": arquivo or "",
        "ano": ano or "",
        "concurso": titulo or "",
        "slug": slug or "",
    }
    if extra:
        record.update({k: v for k, v in extra.items() if v})
    return record


def load_links_cache(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_links_cache(path: Path, cache: dict[str, list[dict]]) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def fetch_arquivos_api(
    s: requests.Session, prova_code: str, turnstile_token: str
) -> list[dict] | None:
    if not turnstile_token:
        return None
    r = s.post(
        LINK_API,
        data={"prova_code": prova_code, "cf-turnstile-response": turnstile_token},
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("ok") and data.get("arquivos"):
        return data["arquivos"]
    return None


def fetch_arquivos_api_browser(
    page, prova_code: str, turnstile_token: str
) -> list[dict] | None:
    """Chama a API no contexto do navegador (mesma sessão/cookies do captcha)."""
    if not turnstile_token or not prova_code:
        return None
    try:
        data = page.evaluate(
            """async ({code, token}) => {
                const body = new URLSearchParams({
                    prova_code: code,
                    'cf-turnstile-response': token,
                });
                const r = await fetch('/provas/link', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body,
                    credentials: 'same-origin',
                });
                return await r.json();
            }""",
            {"code": prova_code, "token": turnstile_token},
        )
    except Exception:  # noqa: BLE001
        return None
    if data.get("ok") and data.get("arquivos"):
        return data["arquivos"]
    return None


def sync_cookies_to_session(context, s: requests.Session) -> None:
    for c in context.cookies():
        s.cookies.set(
            c["name"],
            c["value"],
            domain=c.get("domain") or "",
            path=c.get("path") or "/",
        )


def load_cookies_file(s: requests.Session, path: Path) -> None:
    if not path.exists():
        return
    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for c in cookies:
        s.cookies.set(
            c.get("name", ""),
            c.get("value", ""),
            domain=c.get("domain") or "",
            path=c.get("path") or "/",
        )


def save_cookies_file(context, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context.cookies(), ensure_ascii=False, indent=2), encoding="utf-8")


from pci_stealth import connect_cdp, launch_context


class BrowserSession:
    """Sessão Playwright reutilizada para resolver captcha e obter links."""

    def __init__(
        self,
        headless: bool,
        timeout_s: int,
        *,
        use_chrome: bool = False,
        use_firefox: bool = False,
        cdp_url: str = "",
        profile_dir: Path | None = None,
    ):
        self.headless = headless
        self.timeout_s = timeout_s
        self.use_chrome = use_chrome
        self.use_firefox = use_firefox
        self.cdp_url = cdp_url
        self.profile_dir = profile_dir
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._owns_browser = True
        self._token = ""
        self._prompted = False
        self._pending: list[dict] = []

    def __enter__(self) -> BrowserSession:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        if self.cdp_url:
            self._owns_browser = False
            self._browser, self._context = connect_cdp(self._pw, self.cdp_url)
        else:
            self._context = launch_context(
                self._pw,
                headless=self.headless,
                profile_dir=self.profile_dir,
                use_chrome=self.use_chrome,
                browser="firefox" if self.use_firefox else "chromium",
            )
            self._browser = self._context.browser
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page.on("response", self._on_response)
        return self

    def __exit__(self, *_args) -> None:
        if self._owns_browser and self._context:
            self._context.close()
        if self._owns_browser and self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _on_response(self, response) -> None:
        if "/provas/link" not in response.url:
            return
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            return
        if body.get("ok") and body.get("arquivos"):
            self._pending = body["arquivos"]

    @property
    def token(self) -> str:
        return self._token

    def _read_token(self) -> str:
        try:
            tok = self._page.evaluate(
                "() => { try { return turnstile.getResponse() || ''; } catch(e) { return ''; } }"
            )
        except Exception:  # noqa: BLE001
            tok = ""
        if tok:
            self._token = tok
        return self._token

    def _links_ready(self) -> bool:
        try:
            return bool(
                self._page.evaluate(
                    """() => {
                        const els = [...document.querySelectorAll('a.prova-pdf-link[data-acao="baixar"]')];
                        return els.length > 0 && els.every(e => e.href.startsWith('http'));
                    }"""
                )
            )
        except Exception:  # noqa: BLE001
            return False

    def _extract_dom_links(self) -> list[dict]:
        try:
            return (
                self._page.evaluate(
                    """() => [...document.querySelectorAll('a.prova-pdf-link[data-acao="baixar"]')]
                        .map(e => ({arquivo: e.dataset.arquivo, baixar: e.href, ver: e.href}))
                        .filter(x => x.baixar.startsWith('http'))"""
                )
                or []
            )
        except Exception:  # noqa: BLE001
            return []

    def resolve(
        self,
        s: requests.Session,
        url: str,
        prova_code: str,
        timeout_s: int | None = None,
    ) -> list[dict]:
        if not self._page or self._page.is_closed():
            self._page = self._context.new_page()
            self._page.on("response", self._on_response)

        wait = timeout_s if timeout_s is not None else self.timeout_s

        if self._token and prova_code:
            arquivos = fetch_arquivos_api_browser(self._page, prova_code, self._token)
            if arquivos:
                sync_cookies_to_session(self._context, s)
                return arquivos

        self._pending = []
        self._page.goto(url, wait_until="domcontentloaded", timeout=90000)
        sync_cookies_to_session(self._context, s)

        if not self.headless and not self._prompted:
            print(
                "    [browser] Resolva o captcha no navegador quando aparecer "
                "(pode valer para várias provas seguidas)."
            )
            self._prompted = True

        deadline = time.time() + wait
        while time.time() < deadline:
            if self._pending:
                sync_cookies_to_session(self._context, s)
                return self._pending

            tok = self._read_token()
            if tok and prova_code:
                arquivos = fetch_arquivos_api_browser(self._page, prova_code, tok)
                if arquivos:
                    sync_cookies_to_session(self._context, s)
                    return arquivos

            if self._links_ready():
                links = self._extract_dom_links()
                if links:
                    sync_cookies_to_session(self._context, s)
                    return links

            self._page.wait_for_timeout(1000)

        if self._pending:
            sync_cookies_to_session(self._context, s)
            return self._pending
        links = self._extract_dom_links()
        if links:
            sync_cookies_to_session(self._context, s)
        return links


def resolve_arquivos_playwright(
    url: str,
    headless: bool,
    timeout_s: int,
    *,
    use_chrome: bool = False,
    use_firefox: bool = False,
    cdp_url: str = "",
) -> list[dict]:
    s = session()
    with BrowserSession(
        headless=headless,
        timeout_s=timeout_s,
        use_chrome=use_chrome,
        use_firefox=use_firefox,
        cdp_url=cdp_url,
    ) as browser:
        code = prova_code_from_soup(get_soup(s, url))
        return browser.resolve(s, url, code, timeout_s=timeout_s)


def pdf_items_from_page(soup: BeautifulSoup) -> list[dict]:
    """Extrai pares arquivo/código dos links visíveis na página."""
    items: list[dict] = []
    seen: set[str] = set()
    for card in soup.select(".card"):
        header = clean_text(card.select_one(".card-header"))
        if "Download dos arquivos PDF" not in header and "Visualizar os arquivos PDF" not in header:
            continue
        prefer_baixar = "Download dos arquivos PDF" in header
        acao = "baixar" if prefer_baixar else "ver"
        for link in card.select("a.prova-pdf-link"):
            if link.get("data-acao") != acao:
                continue
            arquivo = link.get("data-arquivo") or ""
            href = link.get("href") or ""
            if not arquivo or arquivo in seen:
                continue
            seen.add(arquivo)
            item = {"arquivo": arquivo, "baixar": "", "ver": ""}
            if href.startswith("http"):
                item[acao] = href
            items.append(item)
    return items


def metadata_card(soup: BeautifulSoup) -> Tag | None:
    download = soup.select_one("#download")
    if not download:
        return None
    for card in download.select(".card"):
        h5 = card.select_one(".card-header h5")
        if h5 and re.search(r"\bprova\b", clean_text(h5), re.I):
            return card
    return (
        soup.select_one("#download > div:nth-child(6) .card")
        or (soup.select_one("#download .card .card-header h5") and soup.select_one("#download .card .card-header h5").find_parent(".card"))
    )


def parse_metadata(soup: BeautifulSoup) -> dict[str, str]:
    card = metadata_card(soup)
    meta: dict[str, str] = {}
    if not card:
        return meta
    title_el = card.select_one(".card-header h5")
    if title_el:
        meta["titulo"] = clean_text(title_el)
    for li in card.select("ul li"):
        strong = li.select_one("strong")
        if not strong:
            continue
        key = clean_text(strong).rstrip(":").strip()
        value_el = strong.find_next_sibling()
        if value_el:
            if value_el.name == "a":
                meta[key] = clean_text(value_el)
                meta[f"{key}_href"] = value_el.get("href") or ""
            else:
                meta[key] = clean_text(value_el)
    return meta


def prova_code_from_soup(soup: BeautifulSoup) -> str:
    link = soup.select_one("a.prova-pdf-link[data-code]")
    return (link.get("data-code") if link else "") or ""


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1] if path else ""


def list_page_url(page_num: int) -> str:
    if page_num <= 1:
        return LIST_URL
    return f"{LIST_URL}/{page_num}"


def list_provas_page(s: requests.Session, page_num: int) -> tuple[list[dict], bool]:
    url = list_page_url(page_num)
    soup = get_soup(s, url)
    table = soup.select_one("#lista_provas")
    if not table:
        return [], False

    provas: list[dict] = []
    for tr in table.select("tbody > tr"):
        link = tr.select_one("td.ca > a") or tr.select_one("td:first-child a")
        if not link or not link.get("href"):
            continue
        prova_url = abs_url(link["href"])
        cargo = clean_text(link)
        ano_el = tr.select_one("td.cb")
        org_el = tr.select_one("td.cc a")
        banca_el = tr.select_one("td.cd a")
        provas.append(
            {
                "url": prova_url,
                "slug": slug_from_url(prova_url),
                "cargo": cargo,
                "ano": clean_text(ano_el),
                "orgao": clean_text(org_el),
                "orgao_href": org_el.get("href") if org_el else "",
                "banca": clean_text(banca_el) or BANCA,
            }
        )

    next_link = None
    for a in soup.select("a"):
        txt = a.get_text(strip=True)
        if re.fullmatch(r"Pr[oó]xima", txt, re.I):
            next_link = a
            break
    has_next = bool(next_link)
    return provas, has_next and bool(provas)


def list_all_provas(s: requests.Session, max_pages: int = 0) -> list[dict]:
    seen: set[str] = set()
    all_items: list[dict] = []
    page = 1
    empty_streak = 0
    while True:
        items, has_next = list_provas_page(s, page)
        new_items = [it for it in items if it["url"] not in seen]
        for it in new_items:
            seen.add(it["url"])
        print(
            f"[lista] página {page}: {len(new_items)} novas "
            f"(total {len(all_items) + len(new_items)})"
        )
        if not new_items:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
            all_items.extend(new_items)
        if not items:
            break
        if max_pages and page >= max_pages:
            break
        if not has_next:
            break
        page += 1
        time.sleep(0.4)
    return all_items


def pick_download_url(item: dict) -> str:
    return item.get("baixar") or item.get("ver") or ""


def match_gabarito(prova_arquivo: str, gab_items: list[dict]) -> dict | None:
    if not gab_items:
        return None
    prova_key = re.sub(r"[^a-z0-9]+", "", prova_arquivo.lower())
    best: tuple[int, dict] | None = None
    for gab in gab_items:
        gab_name = gab.get("arquivo") or ""
        gab_key = re.sub(r"[^a-z0-9]+", "", gab_name.lower())
        score = 0
        if prova_key and gab_key and prova_key[:8] in gab_key:
            score += 2
        parte = PARTE_RE.search(prova_arquivo.lower())
        if parte and parte.group(1).lower() in gab_name.lower():
            score += 5
        if score == 0 and len(gab_items) == 1:
            score = 1
        if best is None or score > best[0]:
            best = (score, gab)
    return best[1] if best else gab_items[0]


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


def resolve_arquivos(
    s: requests.Session,
    prova_url: str,
    soup: BeautifulSoup,
    cache: dict[str, list[dict]],
    cache_path: Path,
    turnstile_token: str,
    browser: BrowserSession | None,
    browser_timeout: int,
) -> list[dict]:
    code = prova_code_from_soup(soup)
    if code and code in cache:
        return cache[code]

    arquivos: list[dict] | None = None
    token = turnstile_token or (browser.token if browser else "")
    if token and code:
        arquivos = fetch_arquivos_api(s, code, token)

    if not arquivos and browser:
        if browser._page and not browser._page.is_closed() and token and code:
            arquivos = fetch_arquivos_api_browser(browser._page, code, token)
            if arquivos:
                sync_cookies_to_session(browser._context, s)
        if not arquivos:
            print("    [browser] aguardando captcha / links...")
            arquivos = browser.resolve(s, prova_url, code, timeout_s=browser_timeout)

    if not arquivos:
        arquivos = pdf_items_from_page(soup)
        arquivos = [a for a in arquivos if pick_download_url(a)]

    if code and arquivos:
        cache[code] = arquivos
        save_links_cache(cache_path, cache)
    return arquivos or []


def process_prova(
    s: requests.Session,
    listing: dict,
    out_dir: Path,
    cache: dict[str, list[dict]],
    cache_path: Path,
    turnstile_token: str,
    browser: BrowserSession | None,
    browser_timeout: int,
    dry_run: bool,
) -> list[dict]:
    url = listing["url"]
    soup = get_soup(s, url)
    meta = parse_metadata(soup)
    slug = listing.get("slug") or slug_from_url(url)

    cargo = meta.get("Cargo") or listing.get("cargo") or ""
    ano = meta.get("Ano") or listing.get("ano") or ""
    orgao = meta.get("Órgão") or meta.get("Orgao") or listing.get("orgao") or ""
    org_href = meta.get("Órgão_href") or meta.get("Orgao_href") or listing.get("orgao_href") or ""
    titulo = meta.get("titulo") or f"Prova {cargo} - {orgao}"
    org_abrev = orgao_abreviado_from_href(org_href) if org_href else parse_org_year_from_slug(slug)[0]

    print(f"  {cargo} | {orgao} | {ano}")

    arquivos = resolve_arquivos(
        s,
        url,
        soup,
        cache,
        cache_path,
        turnstile_token,
        browser,
        browser_timeout,
    )
    if not arquivos:
        print("    [!] Nenhum PDF encontrado (captcha não resolvido?)")
        return [
            make_record(
                titulo=orgao or titulo,
                slug=slug,
                orgao_abreviado=org_abrev,
                cargo=cargo,
                variacao="",
                data="",
                ano=str(ano),
                categoria="prova",
                arquivo="",
                link_documento="",
                link_acesso=url,
                extra={"erro": "PDFs não liberados — informe --turnstile-token ou --browser"},
            )
        ]

    prova_files = [a for a in arquivos if not is_gabarito_filename(a.get("arquivo", ""))]
    gab_files = [a for a in arquivos if is_gabarito_filename(a.get("arquivo", ""))]

    rows: list[dict] = []
    link_acesso = url

    for item in prova_files:
        arquivo_nome = item.get("arquivo") or "prova.pdf"
        variacao = variacao_from_filename(arquivo_nome)
        pdf_url = pick_download_url(item)
        fname = filename_for(org_abrev, str(ano), cargo, variacao, False)
        dest = out_dir / fname
        row = make_record(
            titulo=orgao or titulo,
            slug=slug,
            orgao_abreviado=org_abrev,
            cargo=cargo,
            variacao=variacao,
            data="",
            ano=str(ano),
            categoria="prova",
            arquivo=dest.name,
            link_documento=pdf_url,
            link_acesso=link_acesso,
        )
        if pdf_url:
            if dry_run:
                print(f"    [prova] {dest.name}")
            else:
                try:
                    ok = download_pdf(s, pdf_url, dest)
                    print(f"    [{'OK' if ok else 'skip'}] {dest.name}")
                except Exception as err:  # noqa: BLE001
                    print(f"    [erro prova] {pdf_url}: {err}")
                    row["erro"] = str(err)
        rows.append(row)

        gab = match_gabarito(arquivo_nome, gab_files)
        if not gab:
            continue
        g_url = pick_download_url(gab)
        gname = filename_for(org_abrev, str(ano), cargo, variacao, True)
        gdest = out_dir / gname
        grow = make_record(
            titulo=orgao or titulo,
            slug=slug,
            orgao_abreviado=org_abrev,
            cargo=cargo,
            variacao=variacao,
            data="",
            ano=str(ano),
            categoria="gabarito",
            arquivo=gdest.name,
            link_documento=g_url,
            link_acesso=link_acesso,
            extra={"gabarito_label": gab.get("arquivo") or ""},
        )
        if g_url:
            if dry_run:
                print(f"    [gabarito] {gdest.name}")
            else:
                try:
                    if gdest.exists() and gdest.stat().st_size > 0:
                        print(f"    [skip] {gdest.name}")
                    else:
                        ok = download_pdf(s, g_url, gdest)
                        print(f"    [{'OK' if ok else 'skip'}] {gdest.name}")
                except Exception as err:  # noqa: BLE001
                    print(f"    [erro gabarito] {g_url}: {err}")
                    grow["erro"] = str(err)
        rows.append(grow)

    # Gabarito sem prova associada
    used_gabs = {
        pick_download_url(g)
        for _p, g in (
            (pf, match_gabarito(pf.get("arquivo", ""), gab_files)) for pf in prova_files
        )
        if g
    }
    for gab in gab_files:
        g_url = pick_download_url(gab)
        if not g_url or g_url in used_gabs:
            continue
        variacao = variacao_from_filename(gab.get("arquivo", "")) or "Objetiva"
        gname = filename_for(org_abrev, str(ano), cargo, variacao, True)
        gdest = out_dir / gname
        grow = make_record(
            titulo=orgao or titulo,
            slug=slug,
            orgao_abreviado=org_abrev,
            cargo=cargo,
            variacao=variacao,
            data="",
            ano=str(ano),
            categoria="gabarito",
            arquivo=gdest.name,
            link_documento=g_url,
            link_acesso=link_acesso,
            extra={"gabarito_label": gab.get("arquivo") or ""},
        )
        if not dry_run:
            try:
                ok = download_pdf(s, g_url, gdest)
                print(f"    [{'OK' if ok else 'skip'}] {gdest.name}")
            except Exception as err:  # noqa: BLE001
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
            flat.append(
                {
                    **base,
                    "categoria": "prova",
                    "variacao_prova": var.get("tipo") or "",
                    "link_documento": var.get("link_documento") or "",
                    "arquivo": var.get("arquivo") or "",
                }
            )
            gab = var.get("gabarito") or {}
            if gab.get("link_documento") or gab.get("arquivo"):
                flat.append(
                    {
                        **base,
                        "categoria": "gabarito",
                        "variacao_prova": var.get("tipo") or "",
                        "link_documento": gab.get("link_documento") or "",
                        "arquivo": gab.get("arquivo") or "",
                        "gabarito_label": gab.get("label") or "",
                    }
                )
    return flat


def variacao_from_row(row: dict) -> str:
    for key in ("variacao_prova", "variacao", "tipo"):
        value = row.get(key) or ""
        if value and not isinstance(value, list):
            return str(value).strip()
    return ""


def group_documentos(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], dict] = {}
    order: list[tuple[str, str, str, str]] = []

    for row in flatten_grouped(rows):
        if row.get("erro") and not row.get("arquivo"):
            continue
        variacao = variacao_from_row(row) or "Objetiva"
        cargo = row.get("cargo") or ""
        ano = str(row.get("ano") or "")
        slug = row.get("slug") or ""
        orgao = row.get("orgao_abreviado") or ""
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
                "link_acesso": row.get("link_acesso") or "",
                "categoria": "prova",
                "ano": ano,
                "concurso": row.get("concurso") or "",
                "slug": slug,
            }
            order.append(key)
        item = grouped[key]
        tipos = item["variacao_prova"]
        if variacao not in tipos:
            tipos[variacao] = {"tipo": variacao, "link_documento": "", "arquivo": ""}
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
        description="Scraper de provas e gabaritos VUNESP (PCI Concursos)"
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Só busca/salva provas_list.json, sem baixar PDFs",
    )
    parser.add_argument("--url", help="Processa só uma prova (URL de download)")
    parser.add_argument(
        "--refresh-list",
        action="store_true",
        help="Rebusca a listagem mesmo se provas_list.json existir",
    )
    parser.add_argument("--pages", type=int, default=0, help="Limite de páginas da listagem")
    parser.add_argument("--limit", type=int, default=0, help="Limite de provas")
    parser.add_argument("--dry-run", action="store_true", help="Não baixa PDFs")
    parser.add_argument(
        "--turnstile-token",
        default="",
        help="Token cf-turnstile-response (Cloudflare) para liberar links via API",
    )
    parser.add_argument(
        "--turnstile-token-file",
        default="",
        help="Arquivo com token cf-turnstile-response (gerado por get_pci_token.py)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Abre Chromium (com janela) para resolver o captcha manualmente",
    )
    parser.add_argument(
        "--browser-visible",
        action="store_true",
        help="Abre o navegador com janela (padrão: headless)",
    )
    parser.add_argument(
        "--chrome",
        action="store_true",
        help="Usa Google Chrome instalado em vez do Chromium de teste",
    )
    parser.add_argument(
        "--firefox",
        action="store_true",
        help="Usa Mozilla Firefox em vez do Chromium",
    )
    parser.add_argument(
        "--connect-cdp",
        default="",
        help="Conecta ao Chrome real já aberto (ex: http://127.0.0.1:9222)",
    )
    parser.add_argument(
        "--browser-timeout",
        type=int,
        default=120,
        help="Segundos aguardando captcha/links no navegador (padrão: 120)",
    )
    parser.add_argument(
        "--out",
        default=str(DOWNLOAD_DIR),
        help="Pasta de destino (padrão: ./provas_vunesp)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Não envia arquivos para o Backblaze B2 ao final",
    )
    args = parser.parse_args()
    turnstile_token = args.turnstile_token
    if args.turnstile_token_file:
        token_path = Path(args.turnstile_token_file)
        if token_path.exists():
            turnstile_token = token_path.read_text(encoding="utf-8").strip()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "links_cache.json"
    cache = load_links_cache(cache_path)

    s = session()
    all_rows: list[dict] = []

    if args.url:
        provas = [
            {
                "url": args.url,
                "slug": slug_from_url(args.url),
                "cargo": "",
                "ano": "",
                "orgao": "",
                "orgao_href": "",
                "banca": BANCA,
            }
        ]
    else:
        list_path = out_dir / "provas_list.json"
        if list_path.exists() and not args.pages and not args.refresh_list:
            provas = json.loads(list_path.read_text(encoding="utf-8-sig"))
            print(f"[lista] carregadas {len(provas)} provas de {list_path.name}")
        else:
            provas = list_all_provas(s, max_pages=args.pages)
            list_path.write_text(
                json.dumps(provas, ensure_ascii=False, indent=2),
                encoding="utf-8-sig",
            )
            print(f"[lista] salvas {len(provas)} provas em {list_path.name}")

    if args.limit:
        provas = provas[: args.limit]

    if args.list_only:
        print(f"Listagem concluída: {len(provas)} provas.")
        return

    cookies_path = out_dir / "browser_cookies.json"
    load_cookies_file(s, cookies_path)

    # Token Turnstile exige sessão do navegador; ativa Firefox automaticamente.
    use_browser = (
        args.browser
        or args.connect_cdp
        or (bool(turnstile_token) and not args.dry_run)
    )
    use_firefox = args.firefox or (
        use_browser and not args.chrome and not args.connect_cdp
    )
    browser_ctx: BrowserSession | None = None
    if use_browser:
        browser_ctx = BrowserSession(
            headless=not args.browser_visible,
            timeout_s=args.browser_timeout,
            use_chrome=args.chrome,
            use_firefox=use_firefox,
            cdp_url=args.connect_cdp,
        )
        browser_ctx.__enter__()
        if turnstile_token:
            browser_ctx._token = turnstile_token

    try:
        for i, prova in enumerate(provas, 1):
            print(f"\n[{i}/{len(provas)}] {prova['url']}")
            try:
                wait = args.browser_timeout if i == 1 else 30
                rows = process_prova(
                    s,
                    prova,
                    out_dir,
                    cache,
                    cache_path,
                    turnstile_token or (browser_ctx.token if browser_ctx else ""),
                    browser_ctx,
                    wait,
                    args.dry_run,
                )
                all_rows.extend(rows)
                if i % 10 == 0:
                    save_indices(out_dir, all_rows)
            except Exception as err:  # noqa: BLE001
                print(f"  [erro] {err}")

        save_indices(out_dir, all_rows)
    finally:
        if browser_ctx:
            browser_ctx.__exit__(None, None, None)

    if not args.dry_run and not args.list_only and not args.skip_upload:
        from b2_upload import upload_provas_dir

        try:
            upload_provas_dir(out_dir, prefix="vunesp")
        except Exception as err:  # noqa: BLE001
            print(f"[B2] falha no upload (scraping ok): {err}")


if __name__ == "__main__":
    main()
