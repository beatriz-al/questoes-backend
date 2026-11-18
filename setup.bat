@echo off
REM Instala dependencias Python e navegadores do Playwright
python -m pip install -r requirements.txt
python -m playwright install firefox
echo.
echo Pronto. Para obter o token:
echo   python get_pci_token.py --firefox
echo.
echo Para baixar as provas:
echo   python scraper_pci_vunesp.py --turnstile-token-file provas_vunesp/turnstile_token.txt
