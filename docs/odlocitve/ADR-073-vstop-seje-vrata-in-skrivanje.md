# ADR-073: Vstop — seje, žetoni, CSRF, vrata in skrivanje poti (zapis za nazaj)

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (zapis za nazaj; izvorne zahteve so pri točkah)
- **Status:** Sprejeto — zapis za nazaj

## Kontekst

Razlogi iz `docs/01-arhitektura.md`, razdelki o prijavi, seji na telefonu,
povezavi s QR, lastniku sistema, Google prijavi in registraciji, ki jih
`ADR-027`, `ADR-035`, `ADR-036`, `ADR-038`, `ADR-043`–`ADR-047`, `ADR-057`,
`ADR-061` in `ADR-062` ne nosijo ali jih nosijo brez razloga (`ADR-070`).

## Odločitve in razlogi

### A. Plasti (V3-R03, V3-R04)

1. **`ZetonMiddleware` in `SejaMiddleware` sta plasti, ne odvisnosti.** FastAPI
   telo zahteve prebere pred razreševanjem odvisnosti, zato bi strežnik
   večmegabajtno sliko najprej prebral in šele nato ugotovil, da prijava ne
   velja. Pri seji: pot, ki je nihče ni dodal na noben seznam, je varovana po
   privzetku.
2. **Izvzetje predpone `/admin` je varnostna meja, ne priročnost:** ujame se na
   `/admin` in `/admin/...`, nikoli na `/administration`. Razred
   `TestPrijavaOstajaZahtevanaDrugod` to dokazuje — brez njega bi bila
   sprememba te vrstice nevidna do dneva, ko bi bilo prepozno.
3. **`next` dobi samo varna metoda.** `POST` brez seje pelje na `/admin`, ker bi
   vrnitev nanj z `GET` dala 404.
4. **CSRF žeton zahteva vsaka metoda razen `GET` in `HEAD`**, ne le `POST`, ker
   je V3-R06 dodajal akcije. Prijavni obrazec seje še nima, zato nosi dvojno
   oddan piškotek `csrf_prijava`.
5. **`poti_s_svojim_csrf` je enočlanski in to varuje test**, da druga taka pot
   ne zaide tiho (`ADR-043`).
6. **Na telefonu CSRF-ja ni treba:** brez piškotka ni zahteve, ki bi jo
   brskalnik poslal sam od sebe.

### B. Seja in vrata (V3-R03 do V3-R06)

1. **Omejevanje ugibanja je upočasnitev, ne zaklep** — zaklep bi pomenil, da
   lahko kdorkoli z znanim e-naslovom starša tega izklopi iz admina
   (`ADR-034` A, `ADR-035`). Zgoščevanje teče v niti, da ~60 ms argon2 ne ustavi
   zanke dogodkov.
2. **Sporočila ne izdajo, ali račun obstaja;** ob neznanem identifikatorju se
   zgostitev preveri proti lažni vrednosti, da je tudi odzivni čas enak.
   Ugasnjena družina da isto besedilo kot vsaka neuspela prijava — da je
   ugasnjena, ni podatek za tistega, ki ugiba.
3. **Potekle seje in stari poskusi se čistijo ob vsakem poskusu prijave**, ne le
   ob uspešnem (računa brez gesla ni mogoče uspešno prijaviti), in ne v zanki
   obdelave, ki brez `OPENAI_API_KEY` ne teče (`ADR-009`).
4. **Seja pade ob treh rečeh** (rok, deaktiviran račun, ugasnjena družina) in vse
   tri se preverijo **ob vsaki uporabi seje**, ne le ob prijavi, ker seje
   ustvarja tudi telefon.
5. **Vrata vloge se preverijo ob vsaki uporabi seje.** Do V3-R04 otrokove seje
   ni bilo mogoče ustvariti in je preverba ob prijavi zadoščala; odkar jih
   telefon ustvarja, bi isti žeton, prilepljen v piškotek `seja`, sicer odprl
   celoten `/admin`.
6. **`PrijavaRepository` je brez družine, neizogibno:** prijava pozna samo
   identifikator in družino šele izve. Nobene tabele s podatki družine ne bere.
7. **Odjava telefona je najprej lokalna;** nedosegljiv strežnik ne sme pustiti
   otroka prijavljenega na napravi (`ADR-037`).

### C. Povezava telefona (V6-R01)

1. **Povezava nosi samo žeton**; naslov strežnika ima aplikacija iz gradnje.
2. **Oznaka `POVEZAVA-TELEFONA` je z velikimi črkami**, ker je identifikator
   prijave vedno z malimi.
3. **Ponovitev iste kode se ponudi samo po nedosegljivem strežniku:** zavrnjena
   koda je mrtva in ponovitev bi štela v skupno mejo poskusov.

### D. Skrivanje `/admin/system` (V3-R05)

1. **`404`, ne `403`** — `403` bi povedal, da stran obstaja.
2. **`405` se pod to predpono prevede v `404` in glava `Allow` se zavrže**, ker
   razlika med `405` in `404` pove, da pot obstaja, `Allow` pa našteje, kaj
   sprejema. Brez razlike po vlogi: lastnik ob ročno vtipkanem naslovu izgubi
   le točnejše sporočilo. **Drugje pod `/admin` ostane `405`** — tam obstoj poti
   ni skrivnost.
3. **`POST /admin/system/families` ima tudi `GET`**, ki pelje na seznam, da pot
   ni slepa ulica.
4. **Lastnik ne more ugasniti svoje družine in ne sebe:** na njej stoji
   `is_system_owner`; dejanje, ki ga vmesnik ponuja, mora biti preživeto (isto
   sklepanje kot `ADR-038` G).

### E. Google in registracija (V3-R08, V6-R02)

1. **Primerjava žetonov gre skozi `prijava.zetona_se_ujemata` in primerja
   bajte.** `compare_digest` nad `str` zahteva ASCII; žeton iz obrazca je vhod
   od zunaj, zato je bila izjema `500` z golim angleškim besedilom na vsakem
   `POST` pod `/admin` (pogodba je ostala: tak žeton ni bil nikoli veljaven). Pri
   `state` bi izjema ušla pred brisanjem piškotka in podrla enkratno rabo.
   Svoja dvojnica je bila prvi popravek in je razhajanje povzročila
   (`ADR-047`, `docs/02-izkusnje.md`).
2. **Povratni naslov se sestavi iz `DOMENA`, ne iz `request.url`:** za Caddyjem
   je gostitelj v zahtevi notranje ime vsebnika.
3. **Skozi naslov potuje oznaka, nikoli besedilo:** prosto besedilo bi
   omogočilo s pripravljeno povezavo narisati poljubno sporočilo prav na
   prijavno stran, kjer je tako sporočilo vabilo.
4. **Napaka pove tam, kjer jo bralec vidi:** prijavljen dobi stran s pojasnilom
   (`409`), ker bi ga preusmeritev na prijavo prepričala, da je bil odjavljen.
   Dva slovarja nad istimi oznakami (`SPOROCILA_POVEZAVE`, `SPOROCILA_PRIJAVE`),
   ker nasvet „prijavi se z geslom" prijavljenemu ne pove ničesar.
5. **Vsak pogoj veziva `state` ima svoj test**, ki dokaže tudi, da poverilnica
   ni nastala in da do Googla ni prišlo — brez veziva bi napadalec svoj Google
   račun prilepil na starševega (`ADR-046` D).
6. **Obsegi so samo `openid`, `email`, `profile`:** obseg je tisto, kar starš na
   Googlovem zaslonu prebere o nas.
7. **Klic Googlu ima mejo 15 s in teče v niti**, iz istega razloga kot argon2:
   sinhron klic bi ustavil vse ostale zahteve, tudi prenos slike.
8. **`httpx` ni nov paket** (nameščen prek `openai`), a je od V3-R08 izrecno v
   `dependencies`.
9. **`credentials.label` se osveži samo ob prijavi z Googlom:** vrednost je
   prikaz, iz nje ne izhaja pravica, zato je zastarel izpis cenejši od poizvedbe
   brez razloga.
10. **Brez Googla je vseh pet Googlovih poti `404`, ne `503`:** pot, ki je ta
    namestitev nima, za obiskovalca ne obstaja. Strežnik se zažene normalno —
    manjkajoča nastavitev ustavi eno zmožnost, ne strežnika (drža `ADR-009`).
11. **Meje po IP pri registraciji ni,** ker naslov odjemalca v tej postavitvi ni
    podatek (`ADR-034` A).

## Posledice

- `01-arhitektura.md` nosi poti, plasti in pravila; razlogi so tu in v
  navedenih ADR-jih.
