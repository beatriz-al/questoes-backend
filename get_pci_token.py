#!/usr/bin/env python3
"""Abre a página PCI, aguarda captcha e salva o token Turnstile."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pci_stealth import connect_cdp, launch_context, save_cookies_file

URL = "https://www.pciconcursos.com.br/provas/download/2-tenente-dentista-policia-militar-sp-vunesp-2009"
OUT = Path(__file__).resolve().parent / "provas_vunesp" / "turnstile_token.txt"
COOKIES_OUT = Path(__file__).resolve().parent / "provas_vunesp" / "browser_cookies.json"
TIMEOUT = 300


def page_closed(page) -> bool:
    try:
        return page.is_closed()
    except Exception:  # noqa: BLE001
        return True


def wait_token(page, timeout: int) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if page_closed(page):
            print("\nNavegador fechado antes de obter o token.")
            print("Deixe a janela aberta até o captcha ser resolvido.")
            return ""

        try:
            token = page.evaluate(
                "() => { try { return turnstile.getResponse() || ''; } catch(e) { return ''; } }"
            )
        except Exception as exc:  # noqa: BLE001
            if "closed" in str(exc).lower():
                print("\nNavegador fechado antes de obter o token.")
                print("Deixe a janela aberta até o captcha ser resolvido.")
                return ""
            token = ""

        if token:
            return token

        try:
            page.wait_for_timeout(1000)
        except Exception as exc:  # noqa: BLE001
            if "closed" in str(exc).lower():
                print("\nNavegador fechado antes de obter o token.")
                print("Deixe a janela aberta até o captcha ser resolvido.")
                return ""
            raise

    return ""


def pick_browser(args) -> str:
    if args.firefox:
        return "firefox"
    if args.chrome:
        return "chromium"
    return "chromium"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Obtém token Turnstile do PCI Concursos")
    parser.add_argument("--url", default=URL)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--chrome", action="store_true", help="Usa Google Chrome instalado")
    parser.add_argument(
        "--firefox",
        action="store_true",
        help="Usa Mozilla Firefox (recomendado se Chrome falhar)",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Abre o navegador com janela (necessário para resolver captcha manualmente)",
    )
    parser.add_argument(
        "--connect-cdp",
        default="",
        help="Conecta ao Chrome já aberto, ex: http://127.0.0.1:9222",
    )
    args = parser.parse_args()

    if args.chrome and args.firefox:
        print("Use apenas um: --chrome ou --firefox")
        sys.exit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    token = ""
    with sync_playwright() as p:
        owns_browser = not args.connect_cdp
        if args.connect_cdp:
            print(f"Conectando ao Chrome em {args.connect_cdp}...")
            browser, context = connect_cdp(p, args.connect_cdp)
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser_name = "Firefox" if args.firefox else ("Chrome" if args.chrome else "Chromium")
            mode = "visível" if args.visible else "headless"
            print(f"Abrindo {browser_name} ({mode})...")
            if args.visible:
                print("IMPORTANTE: não feche a janela até aparecer 'Token salvo'.")
            context = launch_context(
                p,
                headless=not args.visible,
                profile_dir=None,
                use_chrome=args.chrome,
                browser=pick_browser(args),
            )
            browser = context.browser
            page = context.pages[0] if context.pages else context.new_page()

        page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
        print("Aguardando captcha... (até 5 minutos)")
        token = wait_token(page, args.timeout)

        if token and context:
            save_cookies_file(context, COOKIES_OUT)
            print(f"Cookies salvos em {COOKIES_OUT}")

        if owns_browser and context:
            context.close()
        if owns_browser and browser:
            browser.close()

    if not token:
        print("\nToken não obtido. Tente:")
        print("  1) python get_pci_token.py --firefox")
        print("  2) python get_pci_token.py --chrome")
        print("  3) Abra Chrome manualmente e use --connect-cdp")
        sys.exit(1)

    OUT.write_text(token, encoding="utf-8")
    print(f"\nToken salvo em {OUT}")
    print(
        "Execute: python scraper_pci_vunesp.py --browser --firefox "
        "--turnstile-token-file provas_vunesp/turnstile_token.txt"
    )


if __name__ == "__main__":
    main()
