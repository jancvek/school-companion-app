# Izkušnje — pasti, ki so nas že stale časa

Bere se ob potrebi, ne ob vsaki zahtevi (`CLAUDE.md` §0). Vsaka past: kaj se
zgodi, zakaj, kako se ji izogneš.

## Strežnik za Caddyjem (V3-R02)

### `basic_auth` in ikona zavihka
**Kaj:** Chrome in Edge sta geslo za `/admin` zahtevala ob vsakem kliku.
**Zakaj:** brskalnik geslo pošlje vnaprej tudi na `/favicon.ico`. Ta pot ni bila
pod `basic_auth`, prišla je do `api`, ta pa je vrnil 401 (API ključ). Brskalnik
401 na zahtevo z geslom razume kot zavrnjeno geslo in ga pozabi.
**Kako:** Caddy na `/favicon.ico` odgovori sam (204). Vsaka pot na isti domeni,
ki vrne 401 brez `basic_auth`, ima isti učinek — tudi koren `/`. V dnevniku se
vidi kot `GET /favicon.ico 401` v isti sekundi kot vsaka stran pod `/admin`.

### Docker Desktop ne ohrani naslova odjemalca
**Kaj:** vse zahteve s telefona so v dnevniku `api` imele naslov `172.18.0.1`.
**Zakaj:** preslikana vrata na Windows tečejo skozi Dockerjev posredniški proces.
**Kako:** naslova odjemalca v tej postavitvi ni; ne gradi ničesar, kar bi nanj
računalo (`ADR-034` A). Preveri z zahtevo z **druge** naprave — zahteva z
istega stroja pokaže prehod v vsaki postavitvi.

### Compose ustvari vsa omrežja, ne le potrebnih
**Kaj:** `docker compose -p drug-projekt up db` je padel s
`Pool overlaps with other one on this address space`.
**Zakaj:** omrežje s stalnim podomrežjem (`spredaj`) nastane ob vsakem projektu
iz iste datoteke, tudi če ga zagnani servis ne rabi.
**Kako:** drugi primerek iz iste datoteke na istem stroju ni mogoč, dokler teče
prvi. Preizkus obnove zato teče z navadnim `docker` (`ADR-034`, dopolnitev).

### Nova vrstica v `sh -c` je nov ukaz
**Kaj:** zastavica, prestavljena v naslednjo vrstico ukaza `command: >` v
Compose, bi tekla kot svoj ukaz; `uvicorn` bi tekel brez nje, brez napake.
**Kako:** zastavice ostanejo v isti vrstici kot program. Test v
`test_postavitev.py` to preverja.

### Zgostitev gesla v `.env`
**Kaj:** bcrypt zgostitev vsebuje `$`, ki ga Compose razume kot spremenljivko.
**Kako:** vrednost v `.env` v enojnih narekovajih. `docker compose config` jo
izpiše z `$$` — to je le ubežni zapis izpisa, ne napaka.

## Prijava in seje (V3-R03)

### `context_processors` prepišejo kontekst klicatelja
**Kaj:** prijavni obrazec je imel prazen CSRF žeton in vsak poskus prijave je
vrnil 403 — čeprav ga pot v kontekst izrecno poda.
**Zakaj:** Starlette obdelovalce konteksta izvede **za** klicateljem in z
`context.update(...)` njegove vrednosti prepiše. Obdelovalec je brez seje
vračal prazen `csrf` in s tem pobrisal žeton prijavne strani.
**Kako:** obdelovalec ključa, ki ga ne pozna, ne vrne (`app/strani.py`). Velja
za vsak `context_processor`: kar vrne, je močnejše od tega, kar poda pot.

### `app.routes` ne pokaže poti vključenih usmerjevalnikov
**Kaj:** generirani test dosegljivosti je našel nič poti pod `/admin`.
**Zakaj:** ta različica FastAPI `include_router` shrani kot ovoj
(`_IncludedRouter`), ne kot razgrnjen seznam `APIRoute`; usmerjanje dela
normalno, introspekcija prek `app.routes` pa ne.
**Kako:** seznam poti se bere iz `app.openapi()["paths"]` — javni vmesnik, ki
ovoje razgrne. Tako ga berejo `test_prijava.py` in `test_tesnjenje.py`.

### Piškotek s `Secure` in `TestClient`
**Kaj:** vsak admin test je po uvedbi seje dobil 303 na prijavo.
**Zakaj:** `TestClient` privzeto govori `http://testserver`, piškotka z
zastavico `Secure` pa odjemalec čez `http` ne pošlje — enako kot brskalnik.
**Kako:** testni odjemalec teče na `https://testserver` (`tests/conftest.py`).
V brskalniku je `http://localhost` izjema in `Secure` piškotke sprejme, zato
razvojni zagon mimo Caddyja deluje.

## Preverba (V3-R09)

### `mypy` nad `app/` ni isto kot nad `apps/server`

Zagon `python -m mypy app/` iz mape `apps/server` preveri **samo produkcijsko
kodo**; testi ostanejo zunaj. Ograja poganja `mypy apps/server` iz korena
repozitorija (`ADR-005`) in s tem 68 datotek namesto 32.

V `V3-R09` je bilo zaradi tega dvakrat poročano „typecheck čist", ko je bilo v
testih osem napak. Zbirka je bila ves čas zelena — `pytest` tipov ne preverja,
zato razlike ni pokazalo nič drugega kot neodvisen pregled.

**Poganjaj ga tako, kot ga požene ograja**, iz korena repozitorija:

```powershell
python -m mypy apps/server
```

Isto velja za `ruff`: `ruff check app/` izpusti `tests/` in `alembic/`.

## Orodja na tem stroju

- **`scripts/` je del ograje** in agentu ni dovoljena za pisanje. Nove skripte
  gredo k modulu, ki mu pripadajo (npr. `apps/server/varnostna-kopija/`).
- **`powershell.exe` (5.1) skript ne požene** (pravilnik izvajanja), a tudi ne
  pozna `$PSNativeCommandUseErrorActionPreference`. Skripte zahtevajo
  PowerShell 7.3 (`#Requires`) in se kličejo s `pwsh`.
- **Preusmeritev `>` v PowerShellu pokvari binarni izhod** (npr. `pg_dump -Fc`).
  Binaren izhod nastane v vsebniku in gre ven z `docker cp`.
- **Orodja `eas` na stroju ni.** Gradnja gre z `npx eas-cli@latest build`,
  spremenljivke EAS pa se urejajo na expo.dev.
