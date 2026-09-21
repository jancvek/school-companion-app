"""Družina se deaktivira, ne briše (V3-R05).

En stolpec na `families` in nič drugega. `is_active` je logična zastavica po
vzoru `users.is_active` (`docs/odlocitve/ADR-038` A) in ne `deactivated_at` po
vzoru arhiva: oseba in družina se lahko vrneta, vprašanje in snov ne — zato je
tam upokojitev z datumom, tu pa stanje, ki se preklaplja.

**Prelivanja na člane ni** (`ADR-044` A). Deaktivacija družine se `users` ne
dotakne, zato ponovna aktivacija vrne družino natanko v stanje pred njo:
kdor je bil deaktiviran že prej, ostane deaktiviran. Prav zato je to stolpec
na `families` in ne množičen `UPDATE` nad `users`.

`server_default` je `true`, ker je stolpec `NOT NULL` in obstoječe družine
morajo ostati aktivne. Default ostane v shemi tudi po migraciji: vrstice
`families` nastajajo odslej skozi `DruzineRepository.ustvari_z_prvim_starsem`,
ki zastavico postavi izrecno, a shema naj pove resnico tudi brez njega.

Revision ID: 0011_stanje_druzine
Revises: 0010_urnik
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_stanje_druzine"
down_revision: str | None = "0010_urnik"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ime tabele in stolpca na enem mestu, da `upgrade` in `downgrade` ne moreta
#: zdrsniti narazen — isti razlog kot v `0004_upokojena_vprasanja`.
DRUZINE = "families"
STOLPEC = "is_active"


def upgrade() -> None:
    """Doda `is_active`; vse obstoječe družine ostanejo aktivne."""
    op.add_column(
        DRUZINE,
        sa.Column(STOLPEC, sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Vrne shemo v stanje `0010_urnik`.

    **Podatek o tem, katera družina je bila ugasnjena, se izgubi dokončno.**
    Nobena vrstica ne izgine in noben podatek družine se ne dotakne — snov,
    vprašanja, kvizi, poskusi in urniki ostanejo —, shema pred to migracijo pa
    razlike med prižgano in ugasnjeno družino ne zna zapisati. Ponoven
    `upgrade` stolpec vrne poln `true`, torej so **vse** nekdaj ugasnjene
    družine spet prižgane in njihovi člani se spet lahko prijavijo.

    Isti razred izgube kot `0004_upokojena_vprasanja` in `0009_otrok_na_zapisu`:
    vrstice ostanejo, pomen se izgubi. Vrnitev čez to migracijo je zato
    smiselna samo nad bazo, v kateri nobena družina ni deaktivirana.

    `batch_alter_table` ni potreben — `DROP COLUMN` na stolpcu brez omejitev
    zna tudi SQLite, ki poganja teste migracije.
    """
    op.drop_column(DRUZINE, STOLPEC)
