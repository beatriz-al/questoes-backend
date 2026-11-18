import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Questao
from ..schemas import Alternativa, FiltrosResponse, QuestaoListResponse, QuestaoOut

router = APIRouter(tags=["questoes"])


def _to_out(row: Questao) -> QuestaoOut:
    alts = json.loads(row.alternativas)
    return QuestaoOut(
        id=row.id,
        numero=row.numero,
        enunciado=row.enunciado,
        enunciado_principal=getattr(row, "enunciado_principal", None),
        alternativas=[Alternativa(**a) for a in alts],
        gabarito=row.gabarito,
        banca=row.banca,
        prova=row.prova,
        area=row.area,
        assunto=row.assunto,
        ano=getattr(row, "ano", None),
        orgao=getattr(row, "orgao", None),
        cargo=getattr(row, "cargo", None),
    )


def _apply_filters(
    stmt: Select,
    *,
    banca: list[str] | None = None,
    prova: list[str] | None = None,
    area: list[str] | None = None,
) -> Select:
    if banca:
        stmt = stmt.where(Questao.banca.in_(banca))
    if prova:
        stmt = stmt.where(Questao.prova.in_(prova))
    if area:
        stmt = stmt.where(Questao.area.in_(area))
    return stmt


def _distinct_values(
    db: Session,
    column: ColumnElement[str],
    *,
    banca: list[str] | None = None,
    prova: list[str] | None = None,
    area: list[str] | None = None,
) -> list[str]:
    stmt = select(column).distinct().order_by(column)
    stmt = _apply_filters(stmt, banca=banca, prova=prova, area=area)
    return list(db.scalars(stmt).all())


@router.get("/questoes", response_model=QuestaoListResponse)
def list_questoes(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    banca: list[str] | None = Query(None),
    prova: list[str] | None = Query(None),
    area: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    q = _apply_filters(select(Questao), banca=banca, prova=prova, area=area)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (
        db.scalars(
            q.order_by(Questao.numero.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .all()
    )
    return QuestaoListResponse(
        items=[_to_out(r) for r in rows],
        page=page,
        page_size=page_size,
        total=total,
        has_more=(page * page_size) < total,
    )


@router.get("/questoes/{questao_id}", response_model=QuestaoOut)
def get_questao(questao_id: str, db: Session = Depends(get_db)):
    row = db.get(Questao, questao_id)
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    return _to_out(row)


@router.get("/filtros", response_model=FiltrosResponse)
def get_filtros(
    banca: list[str] | None = Query(None),
    prova: list[str] | None = Query(None),
    area: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    return FiltrosResponse(
        bancas=_distinct_values(db, Questao.banca, prova=prova, area=area),
        provas=_distinct_values(db, Questao.prova, banca=banca, area=area),
        areas=_distinct_values(db, Questao.area, banca=banca, prova=prova),
    )
