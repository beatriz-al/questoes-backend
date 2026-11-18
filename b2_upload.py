"""Upload de pastas de provas para Backblaze B2 (API nativa — aceita Master Key)."""

from __future__ import annotations

import mimetypes
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

PREFIX_BY_DIR = {
    "provas_fgv": "fgv",
    "provas_cebraspe": "cebraspe",
    "provas_vunesp": "vunesp",
}

SKIP_NAMES = {
    "browser_cookies.json",
    "turnstile_token.txt",
    "firefox_profile",
}


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip().strip('"').strip("'")
    if not value:
        raise RuntimeError(f"Variável de ambiente {name} não definida (veja .env)")
    return value


def get_bucket():
    """Autentica na API nativa B2 e retorna o bucket configurado."""
    from b2sdk.v2 import B2Api, InMemoryAccountInfo

    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account(
        "production",
        _require_env("B2_KEY_ID"),
        _require_env("B2_APPLICATION_KEY"),
    )
    return api.get_bucket_by_name(_require_env("B2_BUCKET_NAME"))


def prefix_for_dir(local_dir: Path) -> str:
    name = local_dir.resolve().name
    if name in PREFIX_BY_DIR:
        return PREFIX_BY_DIR[name]
    if name.startswith("provas_"):
        return name.removeprefix("provas_")
    return name


def iter_upload_files(local_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in local_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES:
            continue
        if any(part in SKIP_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def _object_key(local_dir: Path, file_path: Path, prefix: str) -> str:
    rel = file_path.relative_to(local_dir).as_posix()
    return f"{prefix.strip('/')}/{rel}"


def _remote_sizes(bucket, prefix: str) -> dict[str, int]:
    """Mapeia fileName -> tamanho já existente no bucket."""
    sizes: dict[str, int] = {}
    folder = f"{prefix.strip('/')}/"
    for file_version, _folder in bucket.ls(folder_to_list=folder, recursive=True):
        # ls devolve FileVersion ou Folder; ignoramos pastas
        if getattr(file_version, "size", None) is None:
            continue
        name = file_version.file_name
        sizes[name] = int(file_version.size)
    return sizes


def upload_provas_dir(
    local_dir: Path | str,
    *,
    prefix: str | None = None,
    workers: int = 24,
    dry_run: bool = False,
) -> dict:
    """
    Sync incremental da pasta local para o bucket B2.
    Pula objetos que já existem com o mesmo tamanho.
    """
    local_dir = Path(local_dir).resolve()
    if not local_dir.is_dir():
        raise FileNotFoundError(f"Pasta não encontrada: {local_dir}")

    bucket_name = _require_env("B2_BUCKET_NAME")
    prefix = prefix or prefix_for_dir(local_dir)
    files = iter_upload_files(local_dir)

    print(f"\n[B2] Upload → bucket={bucket_name} prefix={prefix}/")
    print(f"[B2] {len(files)} arquivos em {local_dir} (workers={workers})")

    if dry_run:
        print("[B2] dry-run: nenhum upload")
        return {"uploaded": 0, "skipped": 0, "failed": 0, "total": len(files)}

    print("[B2] autenticando…")
    bucket = get_bucket()
    print("[B2] listando objetos remotos…")
    remote = _remote_sizes(bucket, prefix)
    print(f"[B2] {len(remote)} objetos já no bucket")

    # Filtra antes do pool: skips não competem com uploads reais
    to_upload: list[tuple[Path, str]] = []
    skipped = 0
    for path in files:
        key = _object_key(local_dir, path, prefix)
        if remote.get(key) == path.stat().st_size:
            skipped += 1
        else:
            to_upload.append((path, key))

    print(f"[B2] a enviar: {len(to_upload)} | já ok: {skipped}")
    if not to_upload:
        print("[B2] nada novo para enviar")
        return {
            "uploaded": 0,
            "skipped": skipped,
            "failed": 0,
            "total": len(files),
            "prefix": prefix,
            "bucket": bucket_name,
        }

    uploaded = failed = 0

    def work(path: Path, key: str) -> str:
        content_type, _ = mimetypes.guess_type(str(path))
        bucket.upload_local_file(
            local_file=str(path),
            file_name=key,
            content_type=content_type or "application/octet-stream",
        )
        return key

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, path, key): path for path, key in to_upload}
        done = 0
        for fut in as_completed(futures):
            done += 1
            path = futures[fut]
            try:
                key = fut.result()
                uploaded += 1
                if uploaded <= 5 or uploaded % 50 == 0:
                    print(f"  [B2 ok] {key}")
            except Exception as err:  # noqa: BLE001
                failed += 1
                print(f"  [B2 erro] {path.name}: {err}")
            if done % 100 == 0 or done == len(to_upload):
                print(
                    f"  [B2] progresso {done}/{len(to_upload)} "
                    f"(ok={uploaded} erro={failed})"
                )

    print(
        f"[B2] concluído: novos={uploaded} já existiam={skipped} "
        f"erros={failed} total={len(files)}"
    )
    return {
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "total": len(files),
        "prefix": prefix,
        "bucket": bucket_name,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import argparse

    parser = argparse.ArgumentParser(description="Upload de provas para Backblaze B2")
    parser.add_argument(
        "dirs",
        nargs="*",
        help="Pastas locais (padrão: provas_fgv, provas_cebraspe, provas_vunesp)",
    )
    parser.add_argument("--prefix", help="Prefixo no bucket (padrão: inferido do nome)")
    parser.add_argument(
        "--workers",
        type=int,
        default=24,
        help="Uploads em paralelo (padrão: 24; tente 32–48 se a rede aguentar)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    defaults = [base / "provas_fgv", base / "provas_cebraspe", base / "provas_vunesp"]
    dirs = [Path(d) for d in args.dirs] if args.dirs else [d for d in defaults if d.is_dir()]

    if not dirs:
        print("Nenhuma pasta para enviar.")
        sys.exit(1)

    for d in dirs:
        upload_provas_dir(
            d,
            prefix=args.prefix,
            workers=args.workers,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
