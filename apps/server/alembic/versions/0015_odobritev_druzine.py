"""Družina ima stanje odobritve (V6-R02).

Trije stolpci na `families` in nič drugega (`docs/odlocitve/ADR-062` N):

- `status` — `pending`, `approved` ali `rejected` (`ADR-057` B). Ločen od
  `is_active`: eno pove, ali je lastnik sistema družino sprejel, drugo, ali je
  trenutno prižgana.
- `consent_at` — kdaj je starš ob registraciji potrdil soglasje (`ADR-057` D).
- `decided_at` — kdaj je lastnik zahtevek odobril ali zavrnil.

`server_default` stanja je `approved`, ker je stolpec `NOT NULL` in so vse
obstoječe družine nastale po ročni poti lastnika — torej sprejete. Default
ostane v shemi tudi po migraciji: družina, ki jo odpre lastnik, je `approved`
(`ADR-057` I), registracija pa `pending` vpiše izrecno.

Revision ID: 0015_odobritev_druzine
Revises: 0014_povezava_telefona
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_odobritev_druzine"
down_revision: str | None = "0014_povezava_telefona"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Imena na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti narazen.
DRUZINE = "families"
STANJE = "status"
SOGLASJE = "consent_at"
ODLOCITEV = "decided_at"

#: Edino stanje, ki ga shema pred to migracijo zna izraziti.
ODOBRENA = "approved"


def upgrade() -> None:
    """Doda stanje in oba časa; vse obstoječe družine so odobrene."""
    op.add_column(
        DRUZINE,
        sa.Column(STANJE, sa.String(length=16), nullable=False, server_default=ODOBRENA),
    )
    op.add_column(DRUZINE, sa.Column(SOGLASJE, sa.DateTime(timezone=True), nullable=True))
    op.add_column(DRUZINE, sa.Column(ODLOCITEV, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Vrne shemo v stanje `0014_povezava_telefona`.

    **Ne izvede se, dokler obstaja družina, ki ni odobrena.** Shema pred to
    migracijo razlike ne zna zapisati: čakajoča in zavrnjena družina bi brez
    stolpca tiho postali polnopravni in njuni starši bi prišli v ves `/admin`.
    Isti vzorec kot razveljavitev `0007_druzine` z dvema družinama — izguba, ki
    bi odprla vrata, se ne zgodi molče.

    Časa soglasja in odločitve se izgubita dokončno; vrstice ostanejo.
    """
    neodobrenih = op.get_bind().scalar(
        sa.text(f"SELECT COUNT(*) FROM {DRUZINE} WHERE {STANJE} <> :odobrena"),
        {"odobrena": ODOBRENA},
    )
    if neodobrenih:
        raise RuntimeError(
            f"Razveljavitev ni mogoča: {neodobrenih} družin čaka na odobritev ali je "
            "zavrnjenih. Brez stolpca `status` bi vse postale odobrene. Najprej jih "
            "na /admin/system odobri ali počakaj, da zavrnjeni starši račun izbrišejo."
        )
    op.drop_column(DRUZINE, ODLOCITEV)
    op.drop_column(DRUZINE, SOGLASJE)
    op.drop_column(DRUZINE, STANJE)
