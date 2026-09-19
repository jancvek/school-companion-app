# ADR-035: Izvedba prijave, sej in CSRF v V3-R03

- **Datum:** 2026-09-17
- **Nastalo pri:** V3-R03 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-027` (poverilnice ločeno od uporabnika, neprozorni žetoni),
  `ADR-026` (`basic_auth` je čep, ki mora pasti), `ADR-029` A (začasna izbira
  družine, ki jo zamenja seja), `ADR-034` A (omejevanje po identifikatorju, ne
  po naslovu)
- **Razveljavlja:** `ADR-006` B1 (*„stran, ki je ne varuje geslo"*) in z njim
  kriterij `V1-R04` v `docs/verzije/v1.md`: *„Brez prijave in brez gesla. Meja
  je Tailscale."* Meja je odslej seja, ne omrežje.
- **Preglaša:** začasni `basic_auth` v `apps/server/Caddyfile` in spremenljivki
  `ADMIN_UPORABNIK` / `ADMIN_ZGOSTITEV` iz `okolje.primer` (`ADR-026`).

## Kontekst

`ADR-027` pove, *kaj* je model identitete: `users`, `credentials`, `sessions`,
neprozoren žeton, argon2. Ne pove, *kje* v strežniku se seja preveri, kako
nastane prvo geslo, od kod pride CSRF žeton, kaj se zgodi z otrokom pred
prijavo v admin in kdo pobriše potekle seje. Vse to je faza 1 in 2 zahteve
`V3-R03` našla kot mesta, kjer iz zapisanega ne sledi enolično.

Hkrati je `V3-R03` prva zahteva, ki se dotakne **vseh** poti naenkrat: pod
`/admin` je 27 poti v petih usmerjevalnikih in nanje kaže okoli 300 klicev v
testni zbirki.

## Odločitve

### A — kje se seja preveri

1. **Odvisnost (`Depends`) na vsakem usmerjevalniku.** Za: naravno v FastAPI,
   odvisnost lahko vrne uporabnika. Proti: novega usmerjevalnika je mogoče
   registrirati brez nje, in to je natanko napaka, ki je ne opaziš.
2. **Vmesna plast ASGI nad predpono `/admin`.** Za: pot, ki je nihče ni dodal
   na seznam, je varovana **po privzetku**; isti razlog, iz katerega je
   `ApiKeyMiddleware` plast in ne odvisnost (`app/security.py`). Proti: plast
   mora uporabnika podati naprej prek `scope["state"]`, sicer ga odvisnost
   prebere še enkrat.

**Izbrano: A2.** Generirani test dosegljivosti (kriterij `V3-R03`) pozabljeno
pot sicer ujame, a koda, ki napake ne dopusti, je boljša od testa, ki jo
prijavi. Izvzeti sta samo `GET/POST /admin/login`.

### B — oblika in življenje seje

- Žeton je `secrets.token_urlsafe(32)`, v bazi shranjen kot **SHA-256**
  zgostitev, ne argon2: žeton je naključnih 256 bitov, zato počasna zgostitev
  ne kupi ničesar, plača pa se ob **vsaki** zahtevi.
- Piškotek `seja`: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`,
  `Max-Age` 30 dni.
- **Rok je drseči**: 30 dni od zadnje uporabe. `last_used_at` se osveži
  največ enkrat na uro, sicer bi bila vsaka zahteva `UPDATE`.
- Absolutnega roka ni. Preklic je takojšen prek odjave, prek ponastavitve
  gesla (`V3-R06`) in prek deaktivacije računa.

### C — kdo čisti potekle seje

1. **Zanka `Obdelovalec`.** Proti: **brez `OPENAI_API_KEY` se ta zanka sploh
   ne zažene** (`ADR-009`, `app/main.py`). Čiščenje bi bilo vezano na
   nastavitev, ki z njim nima nobene zveze, in bi tiho izostalo prav v
   namestitvi brez ključa.
2. **Ob prijavi in ob naletu na potekel piškotek.** Za: brez nove niti, brez
   odvisnosti od druge nastavitve, in točka proženja je deterministična, zato
   testljiva brez ure.

**Izbrano: C2.** To je popravek predpostavke iz faze 1 (*„čisti obstoječa
zanka `Obdelovalec`"*); razlog je zgoraj in je bil najden v fazi 2.

### D — CSRF žeton

Žeton je naključen niz, zapisan **v vrstici seje** (`sessions.csrf_token`), in
ne izpeljava iz skrivnosti v okolju: nova spremenljivka okolja bi bila nova
stvar, ki je lahko narobe ali je ni, vrstica seje pa že obstaja in z sejo tudi
pade. Primerja se s `secrets.compare_digest`; neujemanje je `403` kot stran.

Prijavni obrazec seje še nima, zato nosi **dvojno oddan piškotek**: pot `GET
/admin/login` postavi piškotek `csrf_prijava` (`HttpOnly`, `Secure`,
`SameSite=Lax`) in isto vrednost izriše v skrito polje. Brez tega je prijava
sama odprta za CSRF (napadalec te prijavi v **svoj** račun).

Žeton pride v predloge prek `context_processors` izrisovalnika, ne prek 27
klicev `TemplateResponse`. Vsak obrazec dobi eno vrstico `<input type="hidden">`.

### E — omejevanje ugibanja gesla

- Šteje se **samo identifikator**, ne naslov odjemalca. Tako je odločil
  `ADR-034` A: Docker Desktop naslova odjemalca ne ohrani, zato bi štetje po
  naslovu v tej namestitvi upočasnilo **vse** hkrati. Naslov se v tabelo
  vseeno zapiše — za pogled nazaj, ne za odločitev. To je popravek
  predpostavke iz faze 1, kjer je bilo štetje po naslovu predvideno.
- Prag: **5 neuspelih poskusov v 15 minutah**. Nato vsak nadaljnji poskus na
  isti identifikator čaka **2 sekundi**, preden se geslo sploh preveri.
- **Upočasnitev, ne zaklep.** Zaklep bi pomenil, da kdorkoli z znanim
  e-naslovom starša tega starša izklopi iz lastnega strežnika (`ADR-034` A to
  vprašanje izrecno preloži sem). Pravilno geslo torej uspe tudi v
  upočasnitvi; ugibanje pa pade na 0,5 poskusa na sekundo.
- Uspešna prijava izbriše števce tega identifikatorja.
- **Znana omejitev:** vzporedne zahteve čakajo vzporedno, zato upočasnitev ne
  omejuje napadalca, ki ugiba v 100 hkratnih povezavah. Pri tem obsegu
  namestitve je to sprejeto; prava meja bi bila omejevalnik pred aplikacijo.

### F — sporočila ob neuspeli prijavi

- Neznan identifikator, napačno geslo in nenastavljeno geslo dajo **isto**
  sporočilo. Ob neznanem identifikatorju se zgostitev vseeno preveri proti
  lažni vrednosti, da odzivni čas ne izda obstoja računa.
- **Izjema je otrok:** ko se poverilnica ujame, a je vloga `child`, prijava
  pove *„Ta račun je otrokov in se prijavi v mobilni aplikaciji."* Seja ne
  nastane. Cena je zapisana: sporočilo izda vlogo računa, čigar geslo napadalec
  že pozna. Izbrano zavestno — Maša mora razumeti, zakaj ne gre, in kdor pozna
  njeno geslo, ima večjo težavo od razkrite vloge.

### G — prvo geslo

Migracija `0008` ustvari **uporabnika in poverilnico brez tajnosti**
(`secret_hash` je `NULL` = geslo ni nastavljeno; prijava z njim ne uspe
nikoli). Geslo nastavi lastnik z ukazom v vsebniku:

```
docker compose exec api python -m app.ukazi nastavi-geslo <identifikator>
```

Ukaz geslo prebere z `getpass` (dvakrat), nikoli iz argumenta — argument
ostane v zgodovini lupine in v `docker inspect`. Spremenljivka okolja je bila
druga dovoljena možnost po kriteriju in je zavrnjena iz istega razloga.

**Najkrajše geslo je odvisno od vloge:** starš 12 znakov, otrok 4. Staršev
račun je admin družine na javnem internetu; otrokov je za mobilno prijavo,
varuje ga omejevanje iz E in do `/admin` ne pride. `ADR-026` je kratko
otrokovo geslo že predvidel.

> **Razveljavljeno z `ADR-036` E (18. 9. 2026):** otrokovo geslo je odslej
> najmanj **8** znakov. Utemeljitev zgoraj je stala na tem, da otrokov račun
> služi mobilni prijavi, ki je takrat še ni bilo; z `V3-R04` nastane in je
> dosegljiva z javnega interneta. Ostalo v tej točki (starš 12, ukaz z
> `getpass`, migracija brez gesla) velja naprej.

### H — družina iz seje

`daj_druzino` (`ADR-029` A, edina družina v bazi) ostane **samo za poti
telefona**, dokler je `V3-R04` ne odstrani. Poti pod `/admin` dobijo družino iz
seje. Posledica: druga družina v bazi od zdaj ustavi samo telefonske poti, ne
več admin strani.

## Posledice

- **Kaj to olajša:** `V3-R04` doda k isti tabeli `sessions` samo drug
  prenosnik (`Authorization: Bearer`); `V3-R06` dobi tabele in ukaz za geslo že
  postavljene; `V3-R05` podeduje vmesno plast, ki novo pot varuje brez dodatka.
- **Kaj to oteži:**
  - Vsaka zahteva pod `/admin` prebere vrstico seje. Pri tem obsegu nepomembno.
  - Testna zbirka se dotakne v vsakem admin testu: `odjemalec` je odslej
    prijavljen, `POST` nosi CSRF žeton, `TestClient` teče na `https://testserver`
    (sicer piškotka s `Secure` ne pošlje).
  - `tests/test_tesnjenje.py` druge družine ne more več podtakniti z
    `dependency_overrides[daj_druzino]`; prijaviti se mora kot starš družine B.
    Test s tem postane resničnejši, a njegova postavitev je predelana.
  - Po namestitvi te veje je `/admin` nedosegljiv, dokler lastnik ne požene
    ukaza iz G. To je namen: privzeto geslo v migraciji bi bilo javno geslo.
- **Na katere zahteve to vpliva:** `V3-R04` (isti žeton, druga glava),
  `V3-R06` (seje se ob ponastavitvi gesla prekličejo), `V3-R05` (stran
  lastnika), `V1-R04` (kriterij „brez prijave in brez gesla" odpade).

## Popravki po prvem pregledu (17. 9. 2026)

Pregledovalec je našel dve kritični in nekaj manjših točk; spodnje odločitve so
nastale ob popravkih in **spreminjajo tekst zgoraj**, ne razveljavljajo ga.

- **Cilj `next` gre skozi `urlencode`, ne skozi `quote` s širokim `safe`.** Pot
  z dvema parametroma (`/admin/quizzes/new?subject=MAT&vstop=rocna` — tak
  naslov proizvede obrazec v `predmeti.html`) se je ob neubeženem `&` odrezala
  pri prvem parametru in uporabnica je po prijavi pristala na **drugem
  zaslonu**, ne le brez parametra.
- **Cilj dobi samo varna metoda** (`GET`, `HEAD`). Pot, ki obstaja le kot
  `POST`, po prijavi z `GET` vrne 404, vsebine obrazca pa vrnitev ne obnovi;
  zato gre `POST` brez seje na `/admin`.
- **CSRF žeton zahteva vsaka metoda razen `GET` in `HEAD`**, ne samo `POST`.
  Danes je `POST` edina nevarna metoda pod `/admin`, a `V3-R06` bo dodajal
  akcije, in plast, ki bi naštevala metode, bi novo spustila brez žetona.
- **Čiščenje (točka C) teče ob vsakem poskusu prijave, ne le ob uspešnem**, in
  ob naletu na potekel piškotek pobriše vse potekle seje, ne samo tiste. Sicer
  bi v natanko tistem stanju, ki ga pusti migracija — račun brez gesla, torej
  brez uspešne prijave — tabela poskusov rasla brez meje.
- **Zgoščevanje gesla teče v niti** (`run_in_threadpool`), ne na zanki
  dogodkov. argon2 je sinhronih ~60 ms; na zanki bi vsak poskus prijave za
  toliko časa ustavil vse ostale zahteve, tudi prenos slike s telefona.
