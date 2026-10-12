"""Povezovalni žetoni; otrokove geselne poverilnice odpadejo (V6-R01).

Dvoje v eni migraciji, ker je eno brez drugega stanje, v katerem se otrok ne
more prijaviti nikakor:

1. **Nova tabela `link_tokens`** (`docs/odlocitve/ADR-061` B). Gol
   `CREATE TABLE`; obstoječih vrstic se ne dotakne.
2. **Izbris geselnih poverilnic vseh otrok**, v vseh družinah (`ADR-061` H).
   Otrok gesla nima več (`ADR-058` A); vrstica, ki je nihče ne more
   uporabiti, ne ostane. Uporabniško ime se s tem sprosti.

**Seje ostanejo.** `sessions` visi na `users`, ne na `credentials`, zato je
otrok, ki je bil prijavljen pred migracijo, prijavljen tudi po njej
(kriterij `V6-R01`). Snov, kvizi in poskusi se ne dotaknejo.

Poverilnice staršev in Google poverilnice ostanejo nedotaknjene: pogoj nosi
vrsto **in** vlogo.

Revision ID: 0014_povezava_telefona
Revises: 0013_preizkusi
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_povezava_telefona"
down_revision: str | None = "0013_preizkusi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ime na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti narazen.
ZETONI = "link_tokens"

#: Tuja ključa in enoličnost so poimenovani, ne prepuščeni dialektu.
KLJUC_DRUZINE = "fk_link_tokens_family_id"
KLJUC_OTROKA = "fk_link_tokens_child_id"
ENOLICNOST = "link_tokens_token_hash_key"

#: Dobesedni vrednosti in ne uvoz iz `app.models`: migracija opisuje shemo, kot
#: je bila ob svojem nastanku, in se ne sme premakniti, če se model spremeni.
VRSTA_GESLO = "password"
VLOGA_OTROK = "child"


def upgrade() -> None:
    """Ustvari `link_tokens` in izbriše geselne poverilnice otrok."""
    op.create_table(
        ZETONI,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("child_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name=ENOLICNOST),
        # Brez `ondelete`, kot pri vseh ključih na `families` in `users`.
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], name=KLJUC_DRUZINE),
        sa.ForeignKeyConstraint(["child_id"], ["users.id"], name=KLJUC_OTROKA),
    )
    op.create_index(op.f(f"ix_{ZETONI}_family_id"), ZETONI, ["family_id"])
    op.create_index(op.f(f"ix_{ZETONI}_child_id"), ZETONI, ["child_id"])

    # Podpoizvedba in ne `DELETE ... USING`: ta oblika je enaka na SQLite
    # (testi) in na Postgresu (produkcija).
    op.execute(
        sa.text(
            "DELETE FROM credentials WHERE kind = :vrsta "
            "AND user_id IN (SELECT id FROM users WHERE role = :vloga)"
        ).bindparams(vrsta=VRSTA_GESLO, vloga=VLOGA_OTROK)
    )


def downgrade() -> None:
    """Vrne shemo v stanje `0013_preizkusi`.

    **Poverilnic ne vrne.** Izbrisanih zgostitev gesel ni več nikjer, zato
    otrok po vrnitvi nima načina prijave, dokler mu poverilnica ne nastane
    znova. Obstoječe seje veljajo naprej do svojega roka. Neporabljeni
    povezovalni žetoni se izgubijo — živeli bi največ deset minut.
    """
    op.drop_index(op.f(f"ix_{ZETONI}_child_id"), table_name=ZETONI)
    op.drop_index(op.f(f"ix_{ZETONI}_family_id"), table_name=ZETONI)
    op.drop_table(ZETONI)
