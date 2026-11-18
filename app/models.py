from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Questao(Base):
    __tablename__ = "questoes"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    enunciado: Mapped[str] = mapped_column(Text, nullable=False)
    enunciado_principal: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternativas: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    gabarito: Mapped[str] = mapped_column(String(1), nullable=False)
    banca: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prova: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    area: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    assunto: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ano: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    orgao: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
