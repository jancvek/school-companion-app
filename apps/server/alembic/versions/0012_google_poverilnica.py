"""Google poverilnica dobi prikazni e-naslov (V3-R08).

En stolpec na `credentials` in nič drugega. **`users` in `sessions` se ne
dotakneta** — to ni skromnost, ampak kriterij `V3-R08`: `ADR-027` je trdil, da
je Google „nova vrstica in ne nova shema", in če bi ta migracija segla v tabeli
identitete, bi bila trditev ovržena in zahteva ustavljena.

Zakaj stolpec sploh je (`docs/odlocitve/ADR-046` A): `identifier` Google
poverilnice je Googlov `sub`, ker je to edina vrednost, za katero Google jamči,
da se ne spremeni — e-naslov se sme. `sub` pa je za človeka niz števk, po
katerem svojega računa ne prepozna. `label` nosi e-naslov **izključno za
izris**: po njem se nikoli ne išče in nikoli ne prijavlja.

Stolpec je `NULL`-abilen in ostane `NULL` pri vseh geselnih poverilnicah,
vključno z vsemi, ki v bazi že so. Zato ne potrebuje ne `server_default` ne
zapolnitve: vrstica brez oznake je veljavno stanje in ne manjkajoč podatek.

Revision ID: 0012_google_poverilnica
Revises: 0011_stanje_druzine
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_google_poverilnica"
down_revision: str | None = "0011_stanje_druzine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ime tabele in stolpca na enem mestu, da `upgrade` in `downgrade` ne moreta
#: zdrsniti narazen — isti razlog kot v `0011_stanje_druzine`.
POVERILNICE = "credentials"
STOLPEC = "label"

#: Ista dolžina kot `identifier`: oba nosita e-naslov, in stolpec, ki bi bil
#: krajši, bi dolg naslov odrezal ob prijavi, ne ob vpisu.
DOLZINA = 320


def upgrade() -> None:
    """Doda `label`; obstoječe poverilnice ostanejo nedotaknjene."""
    op.add_column(POVERILNICE, sa.Column(STOLPEC, sa.String(length=DOLZINA), nullable=True))


def downgrade() -> None:
    """Vrne shemo v stanje `0011_stanje_druzine`.

    **Nobena poverilnica ne izgine in nobena prijava ne neha delovati.** Izgubi
    se samo prikazni e-naslov ob Google povezavi; `identifier` (`sub`), po
    katerem prijava dejansko teče, je v drugem stolpcu in ostane. To je
    najblažja izguba med vsemi migracijami tega projekta — za razliko od
    `0004`, `0009` in `0011` se tu ne izgubi noben **pomen**, le berljivost
    izpisa v nastavitvah.

    Ponoven `upgrade` pusti stolpec prazen; napolni ga naslednja prijava z
    Googlom, ki oznako tako ali tako osveži (`ADR-046` A).

    `batch_alter_table` ni potreben — `DROP COLUMN` na stolpcu brez omejitev
    zna tudi SQLite, ki poganja teste migracije.
    """
    op.drop_column(POVERILNICE, STOLPEC)
