"""Tipos compartilhados do parse de PDFs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Alternativa:
    letra: str
    texto: str

    def to_dict(self) -> dict[str, str]:
        return {"letra": self.letra, "texto": self.texto}


@dataclass
class QuestaoExtraida:
    id: str
    numero: int
    enunciado: str
    alternativas: list[Alternativa]
    gabarito: str
    banca: str
    prova: str
    area: str = "Geral"
    assunto: str | None = None
    keywords: list[str] = field(default_factory=list)
    enunciado_principal: str | None = None
    ano: str | None = None
    orgao: str | None = None
    cargo: str | None = None
    arquivo: str | None = None

    def to_dict(self) -> dict[str, Any]:
        # JSON flat: texto da questão em enunciado_principal.
        # Se houver contexto (texto de apoio), prefixa ao enunciado.
        if self.enunciado_principal:
            principal = f"{self.enunciado_principal}\n\n{self.enunciado}".strip()
        else:
            principal = self.enunciado
        return {
            "id": self.id,
            "numero": self.numero,
            "enunciado_principal": principal,
            "alternativas": [a.to_dict() for a in self.alternativas],
            "gabarito": self.gabarito,
            "prova": self.prova,
            "area": self.area,
            "assunto": self.assunto,
            "ano": self.ano,
            "orgao": self.orgao,
            "cargo": self.cargo,
            "keywords": list(self.keywords),
            "arquivo": self.arquivo,
        }


@dataclass
class ParseMeta:
    """Metadados da prova vindos do provas.json / índice."""

    prova_id: str
    banca: str
    cargo: str = ""
    orgao: str = ""
    ano: str = ""
    tipo: str = ""
    prova_label: str = ""
    arquivo: str = ""
    link_documento: str = ""
    link_acesso: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParseResult:
    questoes: list[QuestaoExtraida] = field(default_factory=list)
    grupos: list[GrupoQuestao] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)


@dataclass
class ItemGabarito:
    """Item numerado dentro de um enunciado-contexto (Cebraspe)."""

    numero: int
    enunciado: str
    gabarito: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "numero": self.numero,
            "enunciado": self.enunciado,
            "gabarito": (self.gabarito or "").upper()[:1],
        }


@dataclass
class GrupoQuestao:
    """
    Bloco Cebraspe: um enunciado-contexto + N itens que o compartilham.
    Alternativas ficam no grupo (ex.: Certo/Errado) — sem repetir em cada item.
    """

    id: str
    enunciado_principal: str
    itens: list[ItemGabarito]
    alternativas: list[Alternativa]
    banca: str
    prova: str
    area: str = "Geral"
    assunto: str | None = None
    keywords: list[str] = field(default_factory=list)
    arquivo: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "enunciado_principal": self.enunciado_principal,
            "itens": [i.to_dict() for i in self.itens],
            "alternativas": [a.to_dict() for a in self.alternativas],
            "prova": self.prova,
            "area": self.area,
            "assunto": self.assunto,
            "keywords": list(self.keywords),
            "arquivo": self.arquivo,
        }

    def total_itens(self) -> int:
        return len(self.itens)
