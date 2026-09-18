"""Uporabniki, poverilnice in seje (V3-R03).

Tabele `users`, `credentials`, `sessions` in `login_attempts` po
`docs/odlocitve/ADR-027`; izvedba je v `ADR-035`, postopek v
`docs/plan/V3-R03.md`.

Dve stvari, ki nista očitne:

- **Uporabnika nastaneta brez gesla.** `credentials.secret_hash` je `NULL`, kar
  pomeni „geslo ni nastavljeno"; prijava s takim računom ne uspe nikoli. Geslo
  vpiše lastnik z ukazom (`python -m app.ukazi nastavi-geslo <identifikator>`).
  Privzeto geslo v migraciji bi bilo javno geslo — migracija je v repozitoriju.
- **Vrstic z obstoječimi podatki se migracija ne dotakne.** Snov, vprašanja in
  kvizi lastnika ostanejo pri družini Cvek; uporabnik ni njihov lastnik,
  družina je (`ADR-025`).

Revision ID: 0008_uporabniki
Revises: 0007_druzine
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0008_uporabniki"
down_revision: str | None = "0007_druzine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Stalen `id` družine Cvek iz `0007_druzine`.
CVEK_ID = "5b0f6c2e-8d3a-4c7e-9a1b-2f4d6e8c0a13"

#: Stalna `id`-ja obeh uporabnikov. Stalna iz istega razloga kot pri Cveku:
#: ponovljen zagon migracije (ali obnova kopije) mora ciljati isti vrstici.
LASTNIK_ID = "9c1d4f7a-2b6e-4d18-8f35-7a0c9e2b4d61"
OTROK_ID = "3e7b9a05-4c12-4f6d-9b83-1d5f8c0a2e47"

LASTNIK_POVERILNICA_ID = "6a2c8e19-7d54-4b03-9e6f-2c8b1a4d5f70"
OTROK_POVERILNICA_ID = "1f8d3b62-5a97-4e20-8c14-6b9e0d7a3c52"

#: Identifikatorja: e-naslov za starša, uporabniško ime za otroka (`ADR-027`).
LASTNIK_IDENTIFIKATOR = "dejan.ambrus@gmail.com"
OTROK_IDENTIFIKATOR = "masa"

VLOGA_STARS = "parent"
VLOGA_OTROK = "child"
POVERILNICA_GESLO = "password"


def upgrade() -> None:
    """Ustvari tabele identitete in oba uporabnika brez gesla."""
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("is_system_owner", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], name="fk_users_family_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_family_id", "users", ["family_id"])

    op.create_table(
        "credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("identifier", sa.String(length=320), nullable=False),
        sa.Column("secret_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_credentials_user_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identifier", name="credentials_identifier_key"),
    )
    op.create_index("ix_credentials_user_id", "credentials", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_label", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="sessions_token_hash_key"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identifier", sa.String(length=320), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_identifier", "login_attempts", ["identifier"])
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])

    _ustvari_uporabnika(
        user_id=LASTNIK_ID,
        vloga=VLOGA_STARS,
        prikazno_ime="Dejan",
        lastnik_sistema=True,
        poverilnica_id=LASTNIK_POVERILNICA_ID,
        identifikator=LASTNIK_IDENTIFIKATOR,
    )
    _ustvari_uporabnika(
        user_id=OTROK_ID,
        vloga=VLOGA_OTROK,
        prikazno_ime="Maša",
        lastnik_sistema=False,
        poverilnica_id=OTROK_POVERILNICA_ID,
        identifikator=OTROK_IDENTIFIKATOR,
    )


def _ustvari_uporabnika(
    *,
    user_id: str,
    vloga: str,
    prikazno_ime: str,
    lastnik_sistema: bool,
    poverilnica_id: str,
    identifikator: str,
) -> None:
    """Ena oseba in njena poverilnica **brez tajnosti**.

    `secret_hash` ostane `NULL`: geslo pride z ukazom, ne iz repozitorija
    (`ADR-035` G). Tip na parametru časa je tu iz istega razloga kot v
    `0007_druzine` — da čas pretvori SQLAlchemy in ne opuščeni adapter sqlite3.
    """
    povezava = op.get_bind()
    kdaj = datetime.now(UTC)
    cas = sa.bindparam("kdaj", type_=sa.DateTime(timezone=True))

    povezava.execute(
        sa.text(
            "INSERT INTO users "
            "(id, family_id, role, display_name, is_system_owner, is_active, created_at) "
            "VALUES (:id, :druzina, :vloga, :ime, :lastnik, :aktiven, :kdaj)"
        ).bindparams(cas),
        {
            "id": user_id,
            "druzina": CVEK_ID,
            "vloga": vloga,
            "ime": prikazno_ime,
            "lastnik": lastnik_sistema,
            "aktiven": True,
            "kdaj": kdaj,
        },
    )
    povezava.execute(
        sa.text(
            "INSERT INTO credentials "
            "(id, user_id, kind, identifier, secret_hash, created_at, updated_at) "
            "VALUES (:id, :uporabnik, :vrsta, :identifikator, NULL, :kdaj, :kdaj)"
        ).bindparams(cas),
        {
            "id": poverilnica_id,
            "uporabnik": user_id,
            "vrsta": POVERILNICA_GESLO,
            "identifikator": identifikator,
            "kdaj": kdaj,
        },
    )


def downgrade() -> None:
    """Spusti tabele identitete. Podatkov družine se ne dotakne.

    Izgubijo se uporabniki, gesla in seje — po vrnitvi je `/admin` spet
    nezavarovan in strežnik na javnem internetu, zato je vrnitev korak, ki se
    dela skupaj z vrnitvijo `basic_auth` v Caddyju (`ADR-026`).
    """
    op.drop_index("ix_login_attempts_created_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_identifier", table_name="login_attempts")
    op.drop_table("login_attempts")

    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_credentials_user_id", table_name="credentials")
    op.drop_table("credentials")

    op.drop_index("ix_users_family_id", table_name="users")
    op.drop_table("users")
