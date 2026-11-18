"""Orquestra parse de PDFs a partir de provas.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pipeline.config import BACKEND_ROOT, resolve_banca
from pipeline.parse.registry import get_parser
from pipeline.parse.types import ParseMeta, QuestaoExtraida
from pipeline.storage.database import upsert_questoes
from pipeline.storage.local_json import save_prova_questoes, update_index


def _load_provas_json(banca_key: str, provas_dir: Path) -> list[dict[str, Any]]:
    candidates = [
        provas_dir / "provas.json",
        BACKEND_ROOT / f"provas_{banca_key}.json",
    ]
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, list):
                print(f"[pipeline parse] índice: {path} ({len(data)} itens)")
                return data
            raise ValueError(f"JSON inválido (esperado lista): {path}")
    raise FileNotFoundError(
        "provas.json não encontrado. Procurou em: "
        + ", ".join(str(p) for p in candidates)
    )


def _gabarito_path(provas_dir: Path, variacao: dict[str, Any]) -> Path | None:
    gab = variacao.get("gabarito")
    if isinstance(gab, dict):
        name = gab.get("arquivo")
        if name:
            path = provas_dir / name
            return path if path.is_file() else None
    # fallback: mesmo nome da prova com sufixo -gabarito
    arquivo = variacao.get("arquivo") or ""
    if arquivo.lower().endswith(".pdf"):
        candidate = provas_dir / f"{Path(arquivo).stem}-gabarito.pdf"
        if candidate.is_file():
            return candidate
    return None


def run_parse(
    banca: str,
    *,
    limit: int = 0,
    skip_db: bool = False,
) -> dict[str, Any]:
    cfg = resolve_banca(banca)
    banca_key = banca.strip().lower()
    provas_dir: Path = cfg["provas_dir"]
    parser = get_parser(banca_key)
    items = _load_provas_json(banca_key, provas_dir)

    if limit and limit > 0:
        items = items[:limit]

    total_questoes = 0
    total_erros = 0
    arquivos_ok = 0
    arquivos_skip = 0
    db_stats = {"inserted": 0, "updated": 0, "total": 0}

    for item in items:
        prova_id = str(item.get("id") or "")
        variacoes = item.get("variacao_prova") or []
        if not isinstance(variacoes, list) or not variacoes:
            continue

        all_qs: list[QuestaoExtraida] = []
        all_grupos: list = []
        all_errs: list[str] = []
        links_documento: list[str] = []

        for var in variacoes:
            if not isinstance(var, dict):
                continue
            tipo = str(var.get("tipo") or "")
            arquivo = var.get("arquivo") or ""
            gab = var.get("gabarito") if isinstance(var.get("gabarito"), dict) else {}
            if re.search(
                r"(superampliada|adaptada)",
                " ".join(
                    [
                        tipo,
                        arquivo,
                        str(var.get("link_documento") or ""),
                        str(gab.get("arquivo") or ""),
                        str(gab.get("link_documento") or ""),
                    ]
                ),
                re.I,
            ):
                arquivos_skip += 1
                continue
            if not arquivo:
                continue
            prova_pdf = provas_dir / arquivo
            if not prova_pdf.is_file():
                all_errs.append(f"PDF ausente: {arquivo}")
                arquivos_skip += 1
                continue

            gab_pdf = _gabarito_path(provas_dir, var)
            meta = ParseMeta(
                prova_id=prova_id,
                banca=cfg["label"],
                cargo=str(item.get("cargo") or ""),
                orgao=str(item.get("orgao_abreviado") or item.get("orgao_completo") or ""),
                ano=str(item.get("ano") or ""),
                tipo=tipo,
                prova_label=" - ".join(
                    p
                    for p in (
                        cfg["label"],
                        str(item.get("orgao_abreviado") or ""),
                        str(item.get("cargo") or ""),
                        str(item.get("ano") or ""),
                        tipo,
                    )
                    if p
                ),
                arquivo=str(arquivo),
                link_documento=str(var.get("link_documento") or ""),
                link_acesso=str(item.get("link_acesso") or ""),
            )
            parsed = parser.parse(prova_pdf, gab_pdf, meta)
            all_qs.extend(parsed.questoes)
            all_grupos.extend(parsed.grupos)
            all_errs.extend(parsed.erros)
            arquivos_ok += 1
            doc_link = str(var.get("link_documento") or "")
            if doc_link and doc_link not in links_documento:
                links_documento.append(doc_link)

        if not all_qs and not all_grupos and not all_errs:
            continue

        meta_out: dict[str, Any] = {
            "cargo": item.get("cargo"),
            "ano": item.get("ano"),
            "orgao": item.get("orgao_abreviado"),
            "slug": item.get("slug"),
            "link_acesso": item.get("link_acesso"),
        }
        if len(links_documento) == 1:
            meta_out["link_documento"] = links_documento[0]
        elif len(links_documento) > 1:
            meta_out["link_documento"] = links_documento[0]
            meta_out["links_documento"] = links_documento

        out_path = save_prova_questoes(
            banca_key,
            prova_id or f"item-{arquivos_ok}",
            all_qs if not all_grupos else None,
            grupos=all_grupos or None,
            erros=all_errs,
            meta=meta_out,
        )
        n_itens = (
            sum(g.total_itens() for g in all_grupos) if all_grupos else len(all_qs)
        )
        update_index(
            banca_key,
            {
                "prova_id": prova_id,
                "arquivo": out_path.name,
                "questoes": n_itens,
                "grupos": len(all_grupos) if all_grupos else None,
                "erros": len(all_errs),
            },
        )
        total_questoes += n_itens
        total_erros += len(all_errs)
        print(
            f"[pipeline parse] {prova_id}: {n_itens} itens"
            + (f" em {len(all_grupos)} grupos" if all_grupos else "")
            + f", {len(all_errs)} avisos → {out_path.name}"
        )

        if all_qs and not skip_db:
            stats = upsert_questoes(all_qs)
            db_stats["inserted"] += stats["inserted"]
            db_stats["updated"] += stats["updated"]
            db_stats["total"] += stats["total"]

    summary = {
        "banca": banca_key,
        "itens": len(items),
        "pdfs_ok": arquivos_ok,
        "pdfs_skip": arquivos_skip,
        "questoes": total_questoes,
        "erros": total_erros,
        "db": db_stats,
    }
    print(
        f"[pipeline parse] concluído: questoes={total_questoes} "
        f"erros={total_erros} pdfs_ok={arquivos_ok} skip={arquivos_skip} db={db_stats}"
    )
    return summary
