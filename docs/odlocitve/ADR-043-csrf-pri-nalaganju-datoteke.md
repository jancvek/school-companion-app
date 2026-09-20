# ADR-043: Pot z datoteko preveri CSRF sama; plast telesa ne bere

- **Datum:** 2026-09-20
- **Nastalo pri:** V3-R09 (faza 5)
- **Status:** Sprejeto
- **Zoži:** `ADR-035` D — *„CSRF žeton na vsakem `POST` pod `/admin`"* velja
  naprej; kar se spremeni, je **kdo ga preveri** na eni sami poti.
- **Preglaša:** `docs/plan/V3-R09.md` v delu, ki je nalaganje datoteke
  obravnaval kot navaden obrazec. Plan se za nazaj ne popravlja (`CLAUDE.md` §3).
- **Stoji na:** `ADR-041` A (urnik se naloži v adminu), `ADR-042` (slika se
  zapiše ob nalaganju)

## Kontekst

`V3-R09` prinese prvi obrazec z datoteko pod `/admin`. `SejaMiddleware` takega
obrazca ne prepusti, in to dvakrat:

- `_csrf_iz_telesa` prizna **izključno** `application/x-www-form-urlencoded`.
  Pri `multipart/form-data` vrne `None`, `zetona_se_ujemata(None, …)` je
  `False`, odgovor je **403**. Datoteke ni mogoče poslati drugače kot z
  `multipart`.
- `NAJVECJE_TELO_OBRAZCA` je **1 MiB** in plast celo telo prebere v pomnilnik,
  da v njem najde žeton. Fotografija urnika je večja; odgovor bi bil 413.

Oboje je bilo ob nastanku pravilno. Docstring to pove izrecno: *„Obrazci pod
`/admin` so kratki; nalaganja datotek tam ni."* Od te zahteve naprej to ni več
res, zato mora odločitev nastati znova.

## Možnosti

### A — plast se nauči `multipart`

Razčleni tudi `multipart/form-data`, poišče polje `csrf` in dvigne mejo telesa.

Za: pravilo ostane na enem mestu; nobena pot ne dobi izjeme.
Proti: **plast, skozi katero gre vsak `POST` pod `/admin`**, dobi drugo vejo
razčlenjevanja. Napaka v njej ne zadene le urnika, ampak tudi prijavo, brisanje,
objavo kviza in ponastavitev gesla. Meja telesa bi morala zrasti na velikost
slike, in teh 10 MB bi plast držala v pomnilniku **poleg** tistega, kar
Starlette tako ali tako spoolira na disk.

### B — ena pot preveri žeton sama

Plast za to eno pot telesa ne bere in CSRF ne preverja; **sejo zahteva naprej,
kot za vsako pot pod `/admin`**. Žeton primerja pot sama, iz obrazca, ki ga je
že razčlenila.

Za: shared plast ostane nedotaknjena. Telo se ne pufra — datoteka gre skozi
Starlettejev spool na disk in v pomnilniku nikoli ni cela.
Proti: nastane mesto, kjer je mogoče pot izvzeti in nanjo pozabiti dodati
preverbo. Jamstvo `ADR-035` D odslej ne stoji več na eni sami vrstici.

### C — urnik vendarle s telefona

Prekliče `ADR-041` A in se izogne datoteki pod `/admin`.

Proti: podvoji obseg zahteve (zaslon, lokalna shema, `src/sync/`, APK) za
dejanje, ki se zgodi dvakrat na leto. Razlogi so isti kot v `ADR-041` A.

## Odločitev

**B**, z dvema varovaloma, ki nadomestita izgubljeno enovrstično jamstvo:

1. **Test, da izvzeta pot žeton res zahteva.** `POST` nanjo brez veljavnega
   žetona vrne `403`. Brez tega bi izvzetje pomenilo odprto pot.
2. **Test, da je izvzeti nabor natanko enočlanski.** Nova pot vanj ne more
   zaiti tiho; kdor bo dodal drugo, bo moral podreti ta test in s tem prebrati
   ta zapis.

Izvzetje je **svoje polje** (`poti_s_svojim_csrf`) in ne obstoječe
`izvzete_poti`: to drugo izvzame pot iz **cele** plasti, vključno s sejo, in je
namenjeno prijavni strani. Dve različni stvari z istim imenom bi se nekoč
zamenjali, in zamenjava bi odprla pot brez seje.

## Posledice

- **Kaj to olajša:** nalaganje slike urnika deluje, ne da bi se karkoli
  spremenilo za obstoječih devetindvajset poti pod `/admin`.
- **Kaj to oteži:**
  - `ADR-035` D ne drži več na enem mestu. Odslej velja: *CSRF preveri plast,
    razen na poteh v `poti_s_svojim_csrf`, ki ga preverijo same.*
  - Vsaka prihodnja pot z datoteko bo morala isto preverbo napisati znova, ali
    pa bo takrat čas za A. Meja je tu: pri **drugi** taki poti se odločitev
    pretehta, ne pri prvi.
- **Na kaj to vpliva:** `V3-R05` razširja test tesnjenja na vse poti V3; nova
  pot z datoteko gre vanj kot vsaka druga.
