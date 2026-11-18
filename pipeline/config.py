"""Caminhos e mapeamento de bancas do pipeline."""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data" / "questoes"

BANCAS = {
    "fgv": {
        "label": "FGV",
        "provas_dir": BACKEND_ROOT / "provas_fgv",
        "scraper": "scraper_fgv.py",
    },
    "cebraspe": {
        "label": "Cebraspe",
        "provas_dir": BACKEND_ROOT / "provas_cebraspe",
        "scraper": "scraper_cebraspe.py",
    },
    "vunesp": {
        "label": "VUNESP",
        "provas_dir": BACKEND_ROOT / "provas_vunesp",
        "scraper": "scraper_pci_vunesp.py",
    },
}


def resolve_banca(name: str) -> dict:
    key = name.strip().lower()
    if key not in BANCAS:
        known = ", ".join(sorted(BANCAS))
        raise ValueError(f"Banca desconhecida: {name!r}. Use: {known}")
    return BANCAS[key]


def output_dir_for(banca_key: str) -> Path:
    return DATA_DIR / banca_key.lower()
