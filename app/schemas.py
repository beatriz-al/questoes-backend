from pydantic import BaseModel, Field


class Alternativa(BaseModel):
    letra: str
    texto: str


class QuestaoOut(BaseModel):
    id: str
    numero: int
    enunciado: str
    enunciado_principal: str | None = None
    alternativas: list[Alternativa]
    gabarito: str
    banca: str
    prova: str
    area: str
    assunto: str | None = None
    ano: str | None = None
    orgao: str | None = None
    cargo: str | None = None
    model_config = {"from_attributes": True}


class QuestaoListResponse(BaseModel):
    items: list[QuestaoOut]
    page: int
    page_size: int
    total: int
    has_more: bool


class FiltrosResponse(BaseModel):
    bancas: list[str] = Field(default_factory=list)
    provas: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
