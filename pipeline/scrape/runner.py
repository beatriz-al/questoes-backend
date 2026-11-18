"""Dispara os scrapers existentes via subprocess (sem duplicar lógica)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pipeline.config import BACKEND_ROOT, resolve_banca


def run_scrape(
    banca: str,
    *,
    limit: int = 0,
    dry_run: bool = False,
    skip_upload: bool = False,
    extra_args: list[str] | None = None,
) -> int:
    cfg = resolve_banca(banca)
    script = BACKEND_ROOT / cfg["scraper"]
    if not script.is_file():
        raise FileNotFoundError(f"Scraper não encontrado: {script}")

    cmd: list[str] = [sys.executable, str(script)]
    if limit and limit > 0:
        cmd.extend(["--limit", str(limit)])
    if dry_run:
        cmd.append("--dry-run")
    if skip_upload:
        cmd.append("--skip-upload")
    if extra_args:
        cmd.extend(extra_args)

    print(f"[pipeline scrape] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(BACKEND_ROOT))
    return int(result.returncode)
