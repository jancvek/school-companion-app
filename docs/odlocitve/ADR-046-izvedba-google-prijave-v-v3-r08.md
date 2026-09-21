# ADR-046: Izvedba Google prijave — identifikator, kje stojijo poti, vezivo povratnega klica

- **Datum:** 2026-09-21
- **Nastalo pri:** V3-R08 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-027` (poverilnica ni uporabnik), `ADR-026` (HTTPS na
  lastni domeni), `ADR-025` (registracije ni), `ADR-035` (`SejaMiddleware`,
  dvojno oddan CSRF žeton prijavnega obrazca), `ADR-024` (JavaScript samo kot
  nadgradnja posamezne strani)
- **Ne razveljavlja ničesar.**

## Kontekst

`ADR-027` je Google napovedal in zanj pripravil model: *„Google je pozneje
nova vrsta poverilnice, ne nova shema."* Zahteva `V3-R08` to napoved unovči in
njen prvi kriterij jo naredi za preizkus — če bi Google terjal migracijo
`users` ali `sessions`, je bil `ADR-027` napačen in se ustavimo.

Preverba v fazi 2 pove, da napoved drži: `users` in `sessions` se ne dotakneta.
Odprta ostanejo štiri vprašanja, ki jih `ADR-027` ni mogel predvideti, ker so
podrobnosti protokola, ne modela — in eno od njih (D) je edina točka te
zahteve, kjer napaka ne pomeni nedelovanja, ampak tihi vdor v tujo družino.

## Odločitve

### A — `identifier` Google poverilnice je Googlov `sub`, e-naslov je zraven za prikaz

`credentials.identifier` je **enoličen čez celo namestitev** (`V3-R06`). Če bi
bil pri Googlu e-naslov, bi starš, ki ima geslo *in* Google na istem naslovu,
podrl `UNIQUE` — torej natanko tisto, kar kriterij 2 (`isti starš ima lahko
hkrati geslo in Google`) zahteva kot običajno stanje.

Možnosti:

1. **`identifier` = e-naslov.** Za: v nastavitvah je takoj berljiv. Proti:
   podre `UNIQUE` pri prvem staršu, ki ima oboje; Googlov e-naslov se lahko
   spremeni in prijava bi s tem odpadla.
2. **`identifier` = `sub`, brez e-naslova.** Za: stabilen ključ, brez
   migracije. Proti: v nastavitvah piše „Povezan je Google račun
   `104829…`", kar človeku ne pove ničesar in ga ne more prepoznati kot svojega.
3. **`identifier` = `sub`, e-naslov v novem stolpcu samo za prikaz.**

**Izbrano 3.** `sub` je edina vrednost, za katero Google jamči, da se ne
spremeni; e-naslov ni ključ in se zato ne uporabi kot ključ. Nov stolpec
`credentials.label` (`VARCHAR(320) NULL`) nosi e-naslov, ki ga je Google vrnil
ob povezovanju, in služi **izključno izrisu** — po njem se nikoli ne išče in
nikoli ne prijavlja. Pri geselnih poverilnicah ostane `NULL`.

Stolpec se ob vsaki prijavi z Googlom osveži na zadnji znani naslov. Vrednost
je zato lahko zastarela do naslednje prijave; to je prikaz in ne pravica, zato
je zastarel prikaz cenejši od poizvedbe brez razloga.

**Kriterij 1 to dovoljuje:** prepovedana je sprememba `users` in `sessions`.
`credentials` je tabela, ki po `ADR-027` prav *nosi* raznolikost načinov
prijave, in nov `NULL`-abilen stolpec na njej je dodatek, ne prepis.

### B — povezovanje stoji pod `/admin`, prijava in povratni klic zunaj njega

V fazi 1 je bilo dogovorjeno „vse Googlove poti zunaj `/admin`", ker povratni
klic ob **prijavi** pride brez seje in bi pod `/admin` terjal drugo izjemo v
`SejaMiddleware` poleg prijavne strani. Za povratni klic to drži.

Za **povezovanje** pa ne: tega sproži starš, ki *je* prijavljen. Pot zunaj
`/admin` bi morala sama prebrati piškotek, sama razrešiti sejo in sama
preveriti CSRF — torej ponoviti plast, katere vrednost je izrecno zapisana v
`app/security.py`: *„odvisnost je mogoče pozabiti pri novem usmerjevalniku,
predpone pa ne."*

**Izbran razcep po tem, kdo klic sproži:**

| Pot | Metoda | Plast | Kdo jo sproži |
|---|---|---|---|
| `POST /admin/racun/google` | začetek povezovanja | `SejaMiddleware`, **brez izjeme** | prijavljen starš |
| `POST /admin/racun/google/odstrani` | odstranitev povezave | `SejaMiddleware`, **brez izjeme** | prijavljen starš |
| `POST /auth/google/login` | začetek prijave | izvzeta iz `ZetonMiddleware` | neprijavljen obiskovalec |
| `GET /auth/google/callback` | povratek od Googla | izvzeta iz `ZetonMiddleware` | Googlova preusmeritev |

Cena je, da `IZVZETE_POTI` v `app/main.py` zraste za **dve točni poti**. To ni
nova predpona: opozorilo *„tu ne dodajaj ničesar brez ADR"* velja za
`IZVZETE_PREDPONE`, ki ostane enočlanska (`/admin`), in ta ADR je vseeno tisti,
ki novi točni poti dovoli.

`POST /auth/google/login` CSRF žeton preveri **sam**, z istim dvojno oddanim
piškotkom `csrf_prijava`, ki ga prijavni obrazec že ima (`ADR-035` D). Gumb
na prijavni strani je torej obrazec v istem obrazcu strani, ne povezava:
povezava bi pomenila, da lahko tuja stran prijavni tok sproži z `GET`.

### C — povratna pot je ena sama in loči primera po piškotku, ne po naslovu

Google dovoli le vnaprej vpisane povratne naslove. Dva naslova (en za prijavo,
en za povezovanje) bi pomenila dva vpisa v konzoli in dve poti, ki delata
skoraj isto.

**Izbrana ena pot.** Kaj se dogaja, pove piškotek stanja (D), ne naslov.
Povratni naslov je natanko `https://<DOMENA>/auth/google/callback` in je edini
vpisan v Googlovi konzoli.

### D — `state` je vezan na brskalnik in pri povezovanju še na uporabnika

To je varnostno jedro te zahteve in edini razlog, da je ta ADR daljši od
petih vrstic.

Povratni klic je navaden `GET` iz tujega konteksta. Brez veziva obstaja napad,
ki ga je pri Google prijavi lahko spregledati, ker „deluje" povsem normalno:
napadalec pripravi svoj Googlov tok in pripravi žrtvin brskalnik, da ga
dokonča.

- **V prijavnem toku** se žrtev znajde prijavljena v napadalčev račun. Vse, kar
  tam naredi, naredi v tuji družini.
- **V toku povezovanja je posledica hujša in trajna:** napadalčev Google račun
  se prilepi na žrtvin obstoječi račun, in napadalec od takrat vstopa v žrtvino
  družino kadarkoli hoče, brez gesla in brez sledi, ki bi žrtvi karkoli
  povedala. Ponastavitev gesla tega ne odpravi.

**Odločitev:**

- Ob začetku obeh tokov nastane naključen `state` (`secrets.token_urlsafe(32)`).
  Ob povratku se mora ujemati z vrednostjo iz piškotka `google_state`
  (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, življenjska doba 10 minut),
  primerjano s `secrets.compare_digest`. `SameSite=Lax` je tu pravi: Googlova
  preusmeritev je **vrhnja navigacija**, zato piškotek pride nazaj — strožji
  `Strict` bi tok pokvaril, `None` pa bi vezivo izničil.
- Piškotek nosi poleg `state` še **namen** (`prijava` ali `povezava`) in, pri
  povezovanju, **`user_id` starša, ki je tok sprožil**. Ob povratku se mora ta
  `user_id` ujemati s sejo, ki je takrat dejavna. Povezovanje, ki se je začelo
  pod eno sejo in vrnilo pod drugo, se zavrne.
- Piškotek se pobriše ob vsakem izidu povratnega klica, uspešnem ali ne.
  Enkratna raba je del veziva, ne pospravljanje.
- Od Googla se zahteva `email_verified`; račun brez potrjenega e-naslova se
  zavrne. Nepotrjen naslov ni dokaz o ničemer.
- `state` **ni** nadomestek za CSRF žeton na `POST /admin/racun/google`: prvi
  veže povratek na začetek, drugi veže začetek na našo stran. Oba sta potrebna
  in noben ne pokrije drugega.

### E — brez nove zunanje odvisnosti; `httpx` se prizna kot to, kar že je

Za Authorization Code flow potrebujemo odjemalca HTTP. Možnosti:

1. **`authlib`.** Za: manj naše kode. Proti: nov paket **v avtentikacijski
   poti** — prav tam, kjer je cena napačne ali zastarele različice najvišja
   (trdi rob 5).
2. **Ročno, z `httpx`.** Menjava kode na `https://oauth2.googleapis.com/token`,
   nato branje `sub`, `email` in `email_verified` z
   `https://openidconnect.googleapis.com/v1/userinfo`.

**Izbrano 2.** Podpisa ID žetona **ni treba preverjati** in ga namerno ne
preverjamo: podatke dobimo neposredno od Googla prek TLS, po zadnji preverbi
(`https://accounts.google.com/.well-known/openid-configuration`, dosežena po
HTTPS), ne prek brskalnika. Preverba podpisa je potrebna takrat, ko žeton pride
po nezaupani poti — kar tu ni primer. S tem odpade tudi `pyjwt[crypto]` z
JWKS predpomnilnikom, ki bi bil druga nova odvisnost.

`httpx` **ni nov paket:** nameščen je že kot odvisnost paketa `openai`
(preverjeno 21. 9. 2026: `openai 3.8.0`, `httpx 0.28.1`) in je v
`[project.optional-dependencies] dev`. Premakne se v `dependencies`, ker se
na tranzitivno odvisnost ne zanašamo — dan, ko `openai` zamenja odjemalca, ne
sme biti dan, ko pade prijava.

### F — odjemalec Googla je vbrizgljiv, kot `vision.Klicalec`

Isti vzorec in isti razlog kot pri `app/vision.py` (`create_app` ga sprejme kot
argument): testi ne smejo na omrežje, sicer zbirka ni ponovljiva na svežem
klonu in `verify.ps1` ni zelen brez interneta (`CLAUDE.md` §1b).

Brez `GOOGLE_CLIENT_ID` in `GOOGLE_CLIENT_SECRET` odjemalca ni. Takrat:

- gumba „Prijava z Google" na prijavni strani **ni**,
- razdelka o Googlu v `/admin/racun` **ni**,
- vse štiri poti vrnejo **404**.

Strežnik se zažene normalno — ista drža kot pri manjkajočem `OPENAI_API_KEY`
(`ADR-009`): manjkajoča nastavitev ustavi eno zmožnost, ne strežnika. 404 in
ne 503, ker pot, ki je ta namestitev nima, za obiskovalca ne obstaja.

### G — odstranitev povezave se zavrne, če bi račun ostal brez vsake prijave

Kriterij 6 pravi, da odstranitev ne izbriše uporabnika in ne odstrani gesla.
Ne pove, kaj se zgodi, ko gesla **ni** — in tako stanje ni izmišljeno:
migracija `0008_uporabniki` ustvari račune prav brez gesla (`secret_hash IS
NULL`, `ADR-035` G).

**Odločitev:** odstranitev, po kateri bi na računu ne ostala nobena poverilnica,
s katero se je mogoče prijaviti, se **zavrne** s slovenskim pojasnilom
(„Najprej nastavi geslo, sicer se ne boš mogel več prijaviti."). Račun, ki se
je zaklenil sam iz sebe, bi terjal lastnika sistema za nekaj, kar je bil en
klik — in to je tisto, čemur `V3-R06` pravi, da dejanja, ki bi bilo zavrnjeno,
seznam sploh ne ponudi: gumba tam ni in isto pravilo ga tudi zavrne.

### H — Google velja izključno za starša, in to pove `Vrata`, ne nov `if`

Vloga `child` skozi ta tok ne pride. Preverba ni nova: `prijava.vloga_sodi` z
`Vrata.ADMIN` je ista, ki jo uporabljata geselna prijava in `SejaMiddleware`.
Zrcalne veje za Google ni — dve pravili o isti stvari se prej ali slej
razideta, kar je v `prijava.Vrata` že zapisano.

Poverilnica `kind='google'` na otrokovem računu zato nastane ne more: povezovanje
teče pod `/admin`, kamor otrok ne pride. Kriterij 7 (`otroci so izven obsega`)
je s tem posledica obstoječega pravila, ne nova izjema.

## Posledice

- **Kaj to olajša:** `ADR-027` je preverjen in drži — nadaljnje vrste
  poverilnic (šolski račun, Family Link) so spet nova vrstica, ne nova shema.
  Vzorec za tretjo vrsto je odslej napisan.
- **Kaj to oteži:**
  - Nastavitev zunaj repozitorija je zdaj tretja (poleg domene in OpenAI
    ključa): Googlov odjemalec v konzoli, s točnim povratnim naslovom. Postopek
    mora biti v `01-arhitektura.md` tako, da ga je mogoče ponoviti na drugem
    stroju (`V3-R02`).
  - Aplikacija prvič govori z zunanjo storitvijo **med zahtevo uporabnika**, ne
    v ozadju. Nedosegljiv Google mora dati slovensko sporočilo in ne izjeme —
    in mora imeti časovno omejitev, kot jo ima klic vision modela.
  - Zbirka dobi ponaredek odjemalca Googla, ki ga je treba vzdrževati skupaj s
    pravim.
- **Na katere zahteve to odslej vpliva:** `V3-R03` (prijavna stran dobi drugi
  vstop), `V3-R06` (`/admin/racun` je četrta stran, ki se dotika identitete),
  vsaka prihodnja zahteva o poverilnicah otroka.
