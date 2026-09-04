"""Motor, seja in tanka plast nad tabelo `materials`.

Poslovna logika govori z `MaterialsRepository`, ne s SQLAlchemy neposredno —
tako testi tečejo nad SQLite v pomnilniku, produkcija pa nad Postgresom, in
oboje skozi isto kodo.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Material


def naredi_motor(database_url: str) -> Engine:
    """Motor za dano povezavo.

    `pool_pre_ping` zato, ker Postgres v Compose lahko vstane pozneje od API-ja
    in ker povezava čez noč odmre; brez tega bi prva zahteva zjutraj padla.
    """
    return create_engine(database_url, pool_pre_ping=True, future=True)


def naredi_tovarno_sej(motor: Engine) -> sessionmaker[Session]:
    """Tovarna sej za dani motor."""
    return sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


class MaterialsRepository:
    """Operacije nad tabelo `materials`, ki jih potrebuje V1-R02."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def poisci(self, material_id: str) -> Material | None:
        """Zapis z danim `id` ali `None`."""
        return self.session.get(Material, material_id)

    def obstaja(self, material_id: str) -> bool:
        """Ali zapis z danim `id` že obstaja."""
        return self.poisci(material_id) is not None

    def vstavi_ce_ga_ni(self, material: Material) -> bool:
        """Vstavi zapis; vrne `True`, če je nastal, in `False`, če ga je že bilo.

        Preverba pred vstavljanjem pokrije običajni primer (telefon pošlje isti
        `id` znova, ker prvega odgovora ni dočakal). `IntegrityError` pokrije
        tekmovanje dveh hkratnih zahtev z istim `id`: takrat je zmagala prva in
        to za klicatelja pomeni isto — zapis obstaja, ni ga ustvaril on.
        """
        if self.obstaja(material.id):
            return False

        try:
            self.session.add(material)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return False

        return True
