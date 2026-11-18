"""CLI: python -m pipeline scrape|parse|run"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_backend_on_path() -> None:
    backend = Path(__file__).resolve().parent.parent
    backend_str = str(backend)
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Scrape de provas e parse de PDFs (Questão Viva)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--banca",
            required=True,
            choices=["fgv", "cebraspe", "vunesp"],
            help="Banca a processar",
        )
        p.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limite de concursos/provas (0 = todos)",
        )

    p_scrape = sub.add_parser("scrape", help="Baixa provas via scrapers existentes")
    add_common(p_scrape)
    p_scrape.add_argument("--dry-run", action="store_true", help="Não baixa PDFs")
    p_scrape.add_argument(
        "--skip-upload",
        action="store_true",
        help="Não envia PDFs ao Backblaze B2",
    )

    p_parse = sub.add_parser("parse", help="Lê PDFs e gera questões (JSON + DB)")
    add_common(p_parse)
    p_parse.add_argument(
        "--skip-db",
        action="store_true",
        help="Só grava JSON local (não atualiza o banco)",
    )

    p_run = sub.add_parser("run", help="Scrape + parse em sequência")
    add_common(p_run)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--skip-upload", action="store_true")
    p_run.add_argument("--skip-db", action="store_true")

    p_load = sub.add_parser(
        "load-json",
        help="Importa JSON(s) já parseados (grupos ou flat) para o SQLite",
    )
    p_load.add_argument(
        "paths",
        nargs="+",
        help="Arquivo(s) ou pasta(s) com JSON de prova",
    )

    return parser


def _iter_json_paths(raw_paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in raw_paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(p.glob("*.json")))
        elif p.is_file():
            out.append(p)
        else:
            print(f"[pipeline load-json] ignorado (não existe): {p}")
    # pula índice
    return [p for p in out if p.name != "_index.json"]


def main(argv: list[str] | None = None) -> int:
    _ensure_backend_on_path()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)

    if args.command == "scrape":
        from pipeline.scrape.runner import run_scrape

        return run_scrape(
            args.banca,
            limit=args.limit,
            dry_run=args.dry_run,
            skip_upload=args.skip_upload,
        )

    if args.command == "parse":
        from pipeline.parse.runner import run_parse

        run_parse(args.banca, limit=args.limit, skip_db=args.skip_db)
        return 0

    if args.command == "run":
        from pipeline.parse.runner import run_parse
        from pipeline.scrape.runner import run_scrape

        code = run_scrape(
            args.banca,
            limit=args.limit,
            dry_run=args.dry_run,
            skip_upload=args.skip_upload,
        )
        if code != 0:
            return code
        if args.dry_run:
            print("[pipeline run] dry-run: pulando parse")
            return 0
        run_parse(args.banca, limit=args.limit, skip_db=args.skip_db)
        return 0

    if args.command == "load-json":
        from pipeline.storage.database import upsert_from_prova_json

        paths = _iter_json_paths(args.paths)
        if not paths:
            print("[pipeline load-json] nenhum JSON encontrado")
            return 1
        total = {"inserted": 0, "updated": 0, "total": 0}
        for path in paths:
            stats = upsert_from_prova_json(path)
            total["inserted"] += stats["inserted"]
            total["updated"] += stats["updated"]
            total["total"] += stats["total"]
            print(
                f"[pipeline load-json] {path.name}: "
                f"+{stats['inserted']} ~{stats['updated']} ({stats['total']})"
            )
        print(f"[pipeline load-json] concluído: {total}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
