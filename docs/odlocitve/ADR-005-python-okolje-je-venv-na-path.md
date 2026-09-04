# ADR-005: Python okolje je venv v `apps/server/.venv`, dodan na uporabniški PATH

- **Datum:** 2026-09-04
- **Nastalo pri:** V1-R02 (faza 4 — postavitev okolja pred implementacijo)
- **Status:** Sprejeto

## Kontekst

`scripts/verify.ps1` kliče strežniške korake kot **gola ukaza iz korena
repozitorija**:

```
ruff check apps/server
mypy apps/server
pytest apps/server
```

Nikjer ne aktivira venv-a in nikjer ne uporabi absolutne poti. Skripte model ne
sme spreminjati (trdi rob 4), zato se mora okolje prilagoditi njej, ne obratno.
Ker `pytest` uvozi aplikacijo, mora **isti** Python videti tudi `fastapi`,
`sqlalchemy` in ostale odvisnosti — ni dovolj, da so orodja dosegljiva.

Ob preverbi se je pokazalo tudi, da je Python 3.12.10 na tem stroju **že
nameščen** (`C:\Users\PC\AppData\Local\Programs\Python\Python312\`) in že v
uporabniškem PATH. Prva ugotovitev v fazi 1, da ga ni, je bila napačna: seja je
brala `PATH`, podedovan ob zagonu — torej izpred namestitve — pregled
datotečnega sistema izven mape projekta pa je vračal prazen izpis namesto
napake. Oboje je bilo videti enako kot „ni najdeno".

## Možnosti

1. **Globalna namestitev** — vse odvisnosti strežnika in orodja v sistemski
   Python. Za: natanko se ujame s tem, kako skripta kliče orodja; nič dodatnih
   nastavitev. Proti: en sam nabor paketov za vse, kar bo kdaj na tem stroju;
   ob drugem Python projektu se različice zaletijo, rešitve pa ni razen
   selitve v venv-e.
2. **Venv brez posega v PATH, aktiviran ročno pred vsakim `verify`** — Za:
   nič globalnega. Proti: `verify.ps1` venv-a ne aktivira, torej bi bilo
   treba nanjo misliti ob vsakem zagonu, in ograja bi bila zelena ali rdeča
   glede na to, ali je človek pozabil. To ni preverba, to je obred.
3. **Venv v `apps/server/.venv`, njegov `Scripts` na začetku uporabniškega
   PATH** — Za: odvisnosti so ločene od sistemskega Pythona, gola imena pa se
   vseeno razrešijo, tudi ko skripta venv-a ne aktivira. Proti: PATH je last
   uporabniškega računa, ne projekta.

## Odločitev

Izbrana je možnost 3, po lastnikovi izbiri.

Postavljeno:

- venv `apps/server/.venv` nad Python 3.12.10;
- vanj nameščene odobrene odvisnosti — `fastapi`, `uvicorn[standard]`,
  `python-multipart`, `sqlalchemy`, `psycopg[binary]`, `alembic`,
  `pydantic-settings`, ter razvojno `ruff`, `mypy`, `pytest`, `pytest-asyncio`,
  `httpx`;
- `C:\projects\school_companion_app\apps\server\.venv\Scripts` je vpisan na
  **začetek** uporabniškega PATH.

Vrednost PATH je bila prebrana in zapisana neposredno v register, brez
razširjanja — vnosa `%USERPROFILE%\...` sta ostala takšna, kot sta bila, in tip
zapisa `ExpandString` je ohranjen. Prejšnja vrednost je shranjena v
`%USERPROFILE%\path-uporabnik-pred-venv.txt`.

Vrstni red je pomemben: venv je pred globalnim `Python312\Scripts`. Zato so
gola imena nedvoumna tudi, če bi kdaj kdo namestil `pytest` še globalno.

## Posledice

- **Kaj to olajša:** `verify.ps1` teče brez predpriprave in brez aktivacije.
  Odvisnosti tega projekta ne onesnažijo sistemskega Pythona.
- **Kaj to oteži:**
  - **Na tem računu `python` in `pip` odslej kažeta v venv tega projekta.**
    To je najbolj presenetljiv del in edini razlog, da ta zapis obstaja: kdor
    bo čez pol leta v poljubni mapi pognal `pip install`, bo nameščal sem.
    Za drug Python projekt na tem stroju je treba ta vnos umakniti ali
    postaviti za njegovega.
  - Venv je vezan na absolutno pot. Premik ali preimenovanje mape projekta ga
    pokvari; takrat se venv naredi znova, pot v PATH pa popravi.
  - Venv ni v repozitoriju (`.gitignore`), zato ga na svežem klonu ni. Postopek
    postavitve mora biti zapisan v `docs/01-arhitektura.md` (faza 8), sicer je
    zahteva „zeleno na svežem klonu" neizpolnljiva za koga drugega.
- **Na katere zahteve to odslej vpliva:** na vse, ki se dotaknejo
  `apps/server` — V1-R02 in V1-R03.

## Stranski učinek, ki ni posledica te odločitve, a nastane hkrati

Mapa `apps/server` zdaj obstaja, zato `verify.ps1` strežniških korakov ne
preskoči več. Na praznem modulu `mypy` vrne 2 in `pytest` 5, torej **`verify`
ne more biti zelen, dokler V1-R02 ni implementirana.** To je pričakovano
stanje med `V delu`; razreši se v fazi 6.
