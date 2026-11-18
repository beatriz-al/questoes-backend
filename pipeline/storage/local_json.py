"""Persistência local em JSON (backup do parse)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.config import output_dir_for
from pipeline.parse.types import GrupoQuestao, QuestaoExtraida


def save_prova_questoes(
    banca_key: str,
    prova_id: str,
    questoes: list[QuestaoExtraida] | None = None,
    *,
    grupos: list[GrupoQuestao] | None = None,
    erros: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> Path:
    """
    Cebraspe: passa `grupos` (enunciado_principal + itens[]) — formato sem repetição.
    Outras bancas: passa `questoes` flat.
    """
    out_dir = output_dir_for(banca_key)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in prova_id)
    path = out_dir / f"{safe_id}.json"

    if grupos:
        total_itens = sum(g.total_itens() for g in grupos)
        payload: dict[str, Any] = {
            "prova_id": prova_id,
            "banca": banca_key,
            "meta": meta or {},
            "erros": erros or [],
            "total": total_itens,
            "total_grupos": len(grupos),
            "questoes": [g.to_dict() for g in grupos],
        }
    else:
        qs = questoes or []
        payload = {
            "prova_id": prova_id,
            "banca": banca_key,
            "meta": meta or {},
            "erros": erros or [],
            "total": len(qs),
            "questoes": [q.to_dict() for q in qs],
        }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def update_index(banca_key: str, entry: dict[str, Any]) -> Path:
    out_dir = output_dir_for(banca_key)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "_index.json"
    items: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                items = data
        except json.JSONDecodeError:
            items = []
    pid = entry.get("prova_id")
    items = [i for i in items if i.get("prova_id") != pid]
    items.append(entry)
    index_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index_path
