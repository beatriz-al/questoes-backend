"""Upsert de questões no SQLite da API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database import Base, SessionLocal, engine
from app.models import Questao
from pipeline.parse.types import Alternativa, QuestaoExtraida

_NEW_COLUMNS: list[tuple[str, str]] = [
    ("keywords", "TEXT NOT NULL DEFAULT '[]'"),
    ("assunto", "VARCHAR(128)"),
    ("enunciado_principal", "TEXT"),
    ("ano", "VARCHAR(16)"),
    ("orgao", "VARCHAR(64)"),
    ("cargo", "VARCHAR(255)"),
]


def _ensure_schema() -> None:
    """create_all não altera tabelas antigas — completa colunas faltantes."""
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(questoes)")).fetchall()
        cols = {r[1] for r in rows}  # name
        # rename legado enunciado_contexto → enunciado_principal

        # apagar depois
        if "enunciado_contexto" in cols and "enunciado_principal" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE questoes RENAME COLUMN enunciado_contexto "
                    "TO enunciado_principal"
                )
            )
            cols.discard("enunciado_contexto") 
            cols.add("enunciado_principal")
        for name, ddl in _NEW_COLUMNS:
            if name not in cols:
                conn.execute(text(f"ALTER TABLE questoes ADD COLUMN {name} {ddl}"))





def _payload_from_extraida(q: QuestaoExtraida) -> dict[str, Any]:
    return {
        "numero": q.numero,
        "enunciado": q.enunciado,
        "enunciado_principal": q.enunciado_principal,
        "alternativas": json.dumps(
            [a.to_dict() for a in q.alternativas],
            ensure_ascii=False,
        ),
        "gabarito": (q.gabarito or "")[:1] or "?",
        "banca": q.banca,
        "prova": (q.prova or "")[:255],
        "area": q.area or "Geral",
        "assunto": q.assunto,
        "ano": q.ano,
        "orgao": q.orgao,
        "cargo": q.cargo,
        "keywords": json.dumps(q.keywords or [], ensure_ascii=False),
    }


def upsert_questoes(questoes: list[QuestaoExtraida]) -> dict[str, int]:
    _ensure_schema()
    # Última ocorrência vence (evita UNIQUE por IDs duplicados no mesmo lote)
    by_id: dict[str, QuestaoExtraida] = {q.id: q for q in questoes}

    inserted = 0
    updated = 0
    db = SessionLocal()
    try:
        for q in by_id.values():
            payload = _payload_from_extraida(q)
            existing = db.get(Questao, q.id)
            if existing is None:
                db.add(Questao(id=q.id, **payload))
                inserted += 1
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                updated += 1
        db.commit()
    finally:
        db.close()
    return {"inserted": inserted, "updated": updated, "total": len(by_id)}


def _alts_from_json(raw: Any) -> list[Alternativa]:
    if not isinstance(raw, list):
        return []
    out: list[Alternativa] = []
    for a in raw:
        if isinstance(a, dict) and a.get("letra"):
            out.append(
                Alternativa(letra=str(a["letra"]), texto=str(a.get("texto") or ""))
            )
    return out


def flatten_prova_arquivo(data: dict[str, Any]) -> list[QuestaoExtraida]:
    """Converte JSON de prova (grupos Cebraspe ou flat) em lista para o DB."""
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    ano = str(meta.get("ano") or "") or None
    orgao = str(meta.get("orgao") or "") or None
    cargo = str(meta.get("cargo") or "") or None
    banca_fallback = str(data.get("banca") or "")

    flat: list[QuestaoExtraida] = []
    for g in data.get("questoes") or []:
        if not isinstance(g, dict):
            continue

        # Formato agrupado (Cebraspe)
        if isinstance(g.get("itens"), list):
            contexto = (
                str(
                    g.get("enunciado_principal")
                    or g.get("enunciado")
                    or ""
                )
                or None
            )
            alts = _alts_from_json(g.get("alternativas"))
            banca = str(g.get("banca") or banca_fallback)
            prova = str(g.get("prova") or "")
            area = str(g.get("area") or "Geral")
            assunto = g.get("assunto")
            keywords = g.get("keywords") if isinstance(g.get("keywords"), list) else []
            grupo_id = str(g.get("id") or "grupo")

            for item in g["itens"]:
                if not isinstance(item, dict):
                    continue
                numero = int(item.get("numero") or 0)
                if not numero:
                    continue
                item_txt = str(item.get("enunciado") or "")
                gab = str(item.get("gabarito") or "").upper()[:1]
                flat.append(
                    QuestaoExtraida(
                        id=f"{grupo_id}-item{numero}",
                        numero=numero,
                        enunciado=item_txt,
                        enunciado_principal=contexto,
                        alternativas=alts,
                        gabarito=gab,
                        banca=banca,
                        prova=prova,
                        area=area,
                        assunto=str(assunto) if assunto else None,
                        ano=ano,
                        orgao=orgao,
                        cargo=cargo,
                        keywords=[str(k) for k in keywords],
                    )
                )
            continue

        # Formato flat (múltipla escolha): texto da questão em enunciado_principal
        numero = int(g.get("numero") or 0)
        if not numero or not g.get("id"):
            continue
        texto = str(
            g.get("enunciado_principal")
            or g.get("enunciado")
            or ""
        )
        flat.append(
            QuestaoExtraida(
                id=str(g["id"]),
                numero=numero,
                enunciado=texto,
                enunciado_principal=None,
                alternativas=_alts_from_json(g.get("alternativas")),
                gabarito=str(g.get("gabarito") or "").upper()[:1],
                banca=str(g.get("banca") or banca_fallback),
                prova=str(g.get("prova") or ""),
                area=str(g.get("area") or "Geral"),
                assunto=str(g["assunto"]) if g.get("assunto") else None,
                ano=str(g["ano"]) if g.get("ano") else ano,
                orgao=str(g["orgao"]) if g.get("orgao") else orgao,
                cargo=str(g["cargo"]) if g.get("cargo") else cargo,
                keywords=(
                    [str(k) for k in g["keywords"]]
                    if isinstance(g.get("keywords"), list)
                    else []
                ),
            )
        )
    return flat


def upsert_from_prova_json(path: Path | str) -> dict[str, int]:
    """Carrega um JSON de prova (já parseado) e faz upsert no SQLite."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON de prova inválido: {p}")
    return upsert_questoes(flatten_prova_arquivo(data))
