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
