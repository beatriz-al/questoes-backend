"""Helpers anti-detecção para Playwright / Turnstile."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent / "provas_vunesp"
CHROME_PROFILE_DIR = BASE_DIR / "chrome_profile"
FIREFOX_PROFILE_DIR = BASE_DIR / "firefox_profile"

CHROME_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5],
});
"""

FIREFOX_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""

CHROME_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--window-size=1366,768",
]

FIREFOX_USER_PREFS = {
    "dom.webdriver.enabled": False,
    "useAutomationExtension": False,
    "general.platform.override": "Win32",
    "intl.accept_languages": "pt-BR, pt, en-US, en",
}


def _profile_dir(browser: str, profile_dir: Path | None) -> Path:
    if profile_dir:
        return profile_dir
    if browser == "firefox":
        return FIREFOX_PROFILE_DIR
    return CHROME_PROFILE_DIR


def launch_context(
    playwright,
    *,
    headless: bool,
    profile_dir: Path | None = None,
    use_chrome: bool = False,
    browser: str = "chromium",
):
    """Abre Chromium ou Firefox com perfil persistente e flags anti-bot."""
    browser = "firefox" if browser == "firefox" else "chromium"
    profile = _profile_dir(browser, profile_dir)
    profile.mkdir(parents=True, exist_ok=True)

    common = {
        "headless": headless,
        "viewport": {"width": 1366, "height": 768},
        "locale": "pt-BR",
        "timezone_id": "America/Sao_Paulo",
    }

    try:
        if browser == "firefox":
            context = playwright.firefox.launch_persistent_context(
                user_data_dir=str(profile),
                **common,
                firefox_user_prefs=FIREFOX_USER_PREFS,
            )
            context.add_init_script(FIREFOX_STEALTH_INIT_SCRIPT)
            return context

        launch_kwargs: dict = {
            **common,
            "args": CHROME_LAUNCH_ARGS,
            "ignore_default_args": ["--enable-automation"],
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        if use_chrome:
            launch_kwargs["channel"] = "chrome"

        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            **launch_kwargs,
        )
        context.add_init_script(CHROME_STEALTH_INIT_SCRIPT)
        return context
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            target = "firefox" if browser == "firefox" else "chromium"
            raise RuntimeError(
                f"Navegador Playwright ({target}) não instalado.\n"
                f"Execute: python -m playwright install {target}"
            ) from exc
        raise


def connect_cdp(playwright, cdp_url: str = "http://127.0.0.1:9222"):
    """Conecta a um Chrome real já aberto com --remote-debugging-port."""
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
        context.add_init_script(CHROME_STEALTH_INIT_SCRIPT)
    return browser, context


def save_cookies_file(context, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context.cookies(), ensure_ascii=False, indent=2), encoding="utf-8")

