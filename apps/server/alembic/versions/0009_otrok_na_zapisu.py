"""Otrok na snovi, kvizu in poskusu (V3-R07).

Obvezen `child_id` na `materials`, `quizzes` in `question_attempts`. Vse
obstoječe vrstice dobijo **edinega otroka svoje družine**. Razlogi so v
`docs/odlocitve/ADR-039` C, postopek v `docs/plan/V3-R07.md`.

Tri stvari, ki niso očitne:

- **Pravilo je „edini otrok družine", ne „Maša".** Ime produkcijske vrstice v
  kodi migracije bi bilo ime, ki ga na drugem stroju ni.
- **Družina z nič ali več kot enim otrokom migracijo ustavi.** Ugibanje (npr.
  najstarejši otrok) bi tuje odgovore tiho pripisalo napačni osebi, in tega
  potem nihče ne zna popraviti. Pustiti `NULL` pa ne gre: `NOT NULL` je prav
  razlog te zahteve (`ADR-039` A). Preverba teče **pred prvim DDL**, ker na
  SQLite DDL ni v transakciji in bi padec pozneje pustil napol spremenjeno
  shemo.
- **Preverijo se vse družine, tudi tiste brez ene same vrstice v teh treh
  tabelah.** Migracija, ki bi molčala o družini brez otroka samo zato, ker
  danes nima podatkov, bi se ustavila šele ob prvi njeni sliki — torej takrat,
  ko je na to najtežje odgovoriti.

Revision ID: 0009_otrok_na_zapisu
Revises: 0008_uporabniki
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_otrok_na_zapisu"
down_revision: str | None = "0008_uporabniki"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STOLPEC = "child_id"
UPORABNIKI = "users"

#: Tabele, ki dobijo otroka. `questions` ga **ne** dobi: vprašanja ostanejo
#: last družine, da sme starš iz snovi enega otroka sestaviti kviz za drugega
#: (kriterij `V3-R07`, `ADR-039` G). `quiz_items` ga izpelje iz kviza, po isti
#: logiki kot družino (`ADR-029` C).
TABELE = ("materials", "quizzes", "question_attempts")

#: Vloga otroka; dobesedno iz `app.models.VLOGA_OTROK`. Prepisana in ne
#: uvožena: migracija mora ostati veljavna tudi, ko se model premakne.
VLOGA_OTROK = "child"


def _kljuc(tabela: str) -> str:
    return f"fk_{tabela}_{STOLPEC}"


def _indeks(tabela: str) -> str:
    return f"ix_{tabela}_{STOLPEC}"


def _otrok(koliko: int) -> str:
    """„0 otrok", „2 otroka", „3 otroke", „5 otrok" — slovenska dvojina.

    Lastna in ne `app.besedilo.stevilo_z_besedo`: migracija se na aplikacijo
    ne veže, da ostane veljavna tudi, ko se moduli premaknejo. Sporočilo bere
    lastnik, ki bazo popravlja, in „ima 2 otrok" bi bilo vidno narobe vsak
    dan (`CLAUDE.md` §1b).
    """
    ostanek_100 = koliko % 100
    ostanek_10 = koliko % 10
    if ostanek_100 == 1 or (ostanek_10 == 1 and ostanek_100 != 11):
        return f"{koliko} otroka"  # „1 otroka" — rodilnik za „ima"
    if ostanek_100 == 2 or (ostanek_10 == 2 and ostanek_100 != 12):
        return f"{koliko} otroka"
    if ostanek_100 in (3, 4) or (ostanek_10 in (3, 4) and ostanek_100 not in (13, 14)):
        return f"{koliko} otroke"
    return f"{koliko} otrok"


def _otrok_na_druzino(povezava: sa.Connection) -> dict[str, str]:
    """Za vsako družino njen edini otrok, ali `RuntimeError` z razlago.

    Zavrne obe dvoumnosti hkrati in ju **našteje skupaj**: lastnik, ki bazo
    popravlja, naj dobi cel seznam in ne prve napake od petih.
    """
    vrstice = povezava.execute(
        sa.text(
            "SELECT f.id, f.name, u.id, u.display_name "
            "  FROM families f "
            "  LEFT JOIN users u ON u.family_id = f.id AND u.role = :vloga "
            " ORDER BY f.id"
        ),
        {"vloga": VLOGA_OTROK},
    ).all()

    otroci: dict[str, list[str]] = {}
    imena: dict[str, str] = {}
    for family_id, family_name, user_id, _display_name in vrstice:
        imena[family_id] = family_name
        if user_id is not None:
            otroci.setdefault(family_id, []).append(user_id)
        else:
            otroci.setdefault(family_id, [])

    tezave = [
        f"  — družina {imena[family_id]!r} ima {_otrok(len(seznam))}"
        for family_id, seznam in sorted(otroci.items())
        if len(seznam) != 1
    ]
    if tezave:
        raise RuntimeError(
            "Migracija 0009_otrok_na_zapisu pripiše obstoječe zapise edinemu "
            "otroku vsake družine in ne zna ugibati, kateremu:\n"
            + "\n".join(tezave)
            + "\nNič ni spremenjeno. Vsaka družina s podatki mora imeti natanko "
            "enega otroka; dodaj ga na /admin/family ali pa najprej razreši, "
            "čigavi so obstoječi zapisi."
        )

    return {family_id: seznam[0] for family_id, seznam in otroci.items()}


def upgrade() -> None:
    """Doda obvezen `child_id` in ga zapolni z edinim otrokom vsake družine."""
    povezava = op.get_bind()
    # Pred vsakim DDL — glej docstring modula.
    otroci = _otrok_na_druzino(povezava)

    for tabela in TABELE:
        # Najprej `NULL`-abilen, nato zapolnjen, šele nato obvezen: `NOT NULL`
        # brez privzetka nad polno tabelo bi `ADD COLUMN` zavrnil. Isti vzorec
        # kot `family_id` v `0007_druzine`.
        op.add_column(tabela, sa.Column(STOLPEC, sa.String(length=36), nullable=True))
        for family_id, child_id in otroci.items():
            povezava.execute(
                sa.text(
                    f"UPDATE {tabela} SET {STOLPEC} = :otrok WHERE family_id = :druzina"
                ),
                {"otrok": child_id, "druzina": family_id},
            )
        # Na SQLite paketni način tabelo prepiše (`ALTER` omejitve tam ni), na
        # Postgresu izvede navadne `ALTER`.
        with op.batch_alter_table(tabela) as paket:
            paket.alter_column(STOLPEC, existing_type=sa.String(length=36), nullable=False)
            paket.create_foreign_key(_kljuc(tabela), UPORABNIKI, [STOLPEC], ["id"])
            paket.create_index(_indeks(tabela), [STOLPEC])


def downgrade() -> None:
    """Vrne shemo v stanje `0008_uporabniki`.

    **Nobene vrstice ne izgubi**, izgubi pa dokončno podatek o tem, čigav je
    zapis — po istem vzorcu kot `0004_upokojena_vprasanja` (izgubi upokojitev)
    in za razliko od `0005_kvizi` (izgubi cele kvize). Vrnitev čezenj je zato
    smiselna samo nad bazo, v kateri ima vsaka družina enega otroka in je
    pripis izpeljiv nazaj.
    """
    for tabela in reversed(TABELE):
        with op.batch_alter_table(tabela) as paket:
            paket.drop_index(_indeks(tabela))
            paket.drop_constraint(_kljuc(tabela), type_="foreignkey")
            paket.drop_column(STOLPEC)
