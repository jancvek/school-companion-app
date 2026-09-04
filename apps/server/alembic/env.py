"""Okolje za Alembic.

Povezavo bere iz `DATABASE_URL`, ne iz `alembic.ini` — geslo v repozitoriju
nima kaj iskati.

**Izrecna nastavitev klicatelja ima prednost pred okoljem.** Obratni vrstni
red je nevaren, ne le nepriročen: testi migracije si nastavijo svojo začasno
bazo, spremenljivka okolja pa bi jih preusmerila na živo. Test, ki dela
`downgrade base`, bi tako spustil tabelo `materials` v pravi bazi — in bi ob
tem ostal zelen, ker bi trditev preverjal na svoji, prazni bazi.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `alembic.ini` `sqlalchemy.url` namenoma nima, zato je ob običajnem zagonu
# (`alembic upgrade head` v vsebniku) tu prazno in obvelja okolje. Kadar pa je
# url že nastavljen — ker ga je klicatelj podal — se okolja niti ne dotaknemo.
if not config.get_main_option("sqlalchemy.url", None):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        # Brez tega bi Alembic padel z golim `KeyError: 'url'` iz notranjosti
        # SQLAlchemy, kar operaterju ne pove, katera spremenljivka manjka.
        raise RuntimeError(
            "Manjka spremenljivka okolja DATABASE_URL. "
            "V Docker Compose jo poda servis `api`; pri ročnem zagonu jo izvozi sam "
            "(glej apps/server/okolje.primer)."
        )
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Migracije brez povezave — izpiše SQL."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Migracije nad živo povezavo."""
    motor = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with motor.connect() as povezava:
        context.configure(connection=povezava, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
