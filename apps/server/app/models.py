"""Tabela `materials` na strežniku.

Tipi so izbrani tako, da ista shema stoji nad Postgresom (produkcija) in nad
SQLite (testi) — glej odločitev 2 v `docs/plan/V1-R02.md`. Zato `id` ni
`UUID`, ampak `String`: UUID generira telefon in strežnik ga hrani takšnega,
kot ga je dobil.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Stanje obdelave ob prevzemu. Prehodi (`processing`, `ready`, `failed`) so
#: predmet V1-R03; ta zahteva zna ustvariti samo `new`.
STATUS_NOV = "new"


class Base(DeclarativeBase):
    """Skupna osnova za modele."""


class Material(Base):
    """Ena fotografirana učna snov, prejeta s telefona."""

    __tablename__ = "materials"

    #: UUID, generiran na telefonu. Nosilec idempotentnosti.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Koda predmeta, npr. `MAT`.
    subject: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Trenutek posnetka (ne prejema), s časovnim pasom.
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Pot do slike na disku strežnika.
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    #: Stanje obdelave. V tej zahtevi vedno `new`.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Trenutek, ko je strežnik zapis prevzel.
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
