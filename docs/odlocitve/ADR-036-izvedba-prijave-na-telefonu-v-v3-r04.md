# ADR-036: Izvedba prijave na telefonu; lastnik na lokalnem zapisu; otrokovo geslo

- **Datum:** 2026-09-18
- **Nastalo pri:** V3-R04 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-027` (poverilnice ločeno od uporabnika, neprozorni žetoni,
  API ključ odpade), `ADR-035` (prijava, seje in CSRF na admin strani),
  `ADR-004` (migracije lokalne sheme), `ADR-012` (poskus se ne izgubi)
- **Razveljavlja:** `ADR-029` A (začasna izbira družine za poti telefona —
  `daj_druzino_telefona`), in v `ADR-035` G najkrajše otrokovo geslo
  (`4` znaki) skupaj z njegovo utemeljitvijo *„otrokov je za mobilno prijavo
  in do `/admin` ne pride"*.
- **Preglaša:** `ApiKeyMiddleware`, `Settings.api_key` in `API_KEY` v
  `docker-compose.yml` ter `okolje.primer`.

## Kontekst

`ADR-027` pove, *kaj* telefon odslej pošilja: neprozoren žeton iz iste tabele
`sessions`, v glavi `Authorization: Bearer`, in API ključ odpade ostro, ne
postopno. `ADR-035` je isti model izvedel za brskalnik. Nepovedano ostane
četvero, kar je faza 1 zahteve `V3-R04` našla kot mesta, kjer iz zapisanega ne
sledi enolično — in ena stvar, ki jo je našla faza 2.

Telefon se od brskalnika loči v eni točki, ki vse ostalo obarva: **naprava je
skupna, identiteta pa ne.** Brskalnik ima piškotek na profil in lokalne vrste
nima. Telefon ima lokalno bazo s posnetki, kvizi in poskusi, ki so nastali
*prej* — morda pod drugo osebo, morda pod nobeno.

## Odločitve

### A — prijava ne zapre aplikacije, zapre samo prenos

1. **Prijava so vrata.** Za: preprosto, en zaslon pred vsem. Proti: otrok s
   svežim APK in brez omrežja tisti dan ne more poslikati ničesar. To podre
   načelo iz `docs/00-namen.md` (*„aplikacija nikoli ne čaka na strežnik"*)
   prav na prvem zaslonu in prav v primeru, zaradi katerega obstaja.
2. **Aplikacija dela naprej, prijava je vnos na domači strani.** Vrstica
   stanja pove „Nisi prijavljena. Posnetki se shranjujejo na telefon." — po
   istem vzorcu kot današnji „Prenos ni nastavljen".

**Izbrano: A2.** Kriterij `V3-R04` je isto pravilo že zapisal za potekel
žeton (*„kamera dela, slika se shrani lokalno, zapis ostane `pending`"*);
odsotnost žetona ni strožji primer od poteklega.

### B — lastnik je zapisan na vrstici, ne na napravi

1. **Naprava ima eno identiteto.** Ob prijavi z drugim uporabnikom se lokalna
   baza počisti. Za: brez migracije sheme. Proti: neposlana snov prejšnjega
   otroka je izgubljena, kar je pri telefonu, ki si ga delita dva otroka,
   najbolj pričakovan primer, ne najbolj redek.
2. **Vsak zapis nosi svojega lastnika.** `materials.user_id` in
   `attempts.user_id` v lokalni bazi (migracija sheme **3**, `ADR-004`).
   Prenaša se izključno, kar je last prijavljenega. Tuje ostane na telefonu,
   nevidno in nepreneseno, dokler se ta oseba ne prijavi nazaj.

**Izbrano: B2.** Cena je stolpec in migracija; kupi pa to, da menjava
uporabnika ni dogodek, ki karkoli uniči.

**Posvojitev:** zapis z `user_id IS NULL` je zapis, ki je nastal, ko ni bil
prijavljen nihče. Ob **uspešni prijavi** ga posvoji uporabnik, ki se je
prijavil — z eno posodobitvijo, takoj, ne šele ob prenosu. Brez tega bi
nadgradnja Mašinega telefona (vsi obstoječi zapisi so po migraciji brez
lastnika) pomenila vrsto, ki ne odide nikoli. Posledica, ki je zapisana
zavestno: posnetki, nastali med odjavo enega in prijavo drugega, pripadejo
drugemu. Deterministično je in v družini razumljivo.

### C — kvize in poskuse je treba filtrirati po lastniku, ne samo posnetke

To je ugotovitev faze 2, ne izbira. `pobrisiKvizeRazen` pobriše kvize, ki jih
strežnik ne vrača več, **neprenesenih poskusov pa namenoma ne** (`ADR-012`,
`ADR-019` B). Po menjavi uporabnika je seznam s strežnika seznam *novega*
otroka, zato gredo kvizi prejšnjega ven, njegovi neposlani poskusi pa ostanejo
kot sirote — in `neprenesenePoskuse` bi jih poslala pod žetonom novega otroka.
To je natanko tisto, kar kriterij `V3-R04` prepoveduje.

Zato: `attempts` dobi `user_id`, usklajevanje kvizov pa gleda **samo vrstice
prijavljenega uporabnika** — tako pri brisanju kot pri branju neprenesenih.
Poskus tujega lastnika ni ne poslan ne pobrisan.

### D — starš se v mobilno aplikacijo ne prijavi

Zrcalno `ADR-035` F: kot admin stran zavrne otroka z razlago, mobilna prijava
zavrne starša z razlago (*„Ta račun je starševski; prijavi se na spletni
strani."*). Seja ne nastane.

Razlog ni le simetrija. `V3-R07` bo snovi pripisal otroka, ki jo je poslikal;
snov, ki bi nastala pod starševskim žetonom, tega otroka ne bi imela in bi
bila v tisti zahtevi poseben primer, ki ga ni treba ustvariti.

Cena je ista kot pri `ADR-035` F in se prizna enako: sporočilo izda vlogo
računa, čigar geslo tisti, ki ga vidi, že pozna.

### E — najkrajše otrokovo geslo je 8 znakov, ne 4

`ADR-035` G je otroku dovolil 4 znake z izrecno utemeljitvijo, da je *„otrokov
račun za mobilno prijavo in do `/admin` ne pride"*. Mobilne prijave takrat ni
bilo. S to zahtevo nastane in je dosegljiva z vsakega naslova na svetu, hkrati
pa `ADR-035` E priznava, da upočasnitev ne velja za napadalca z vzporednimi
povezavami. Štirimestno geslo iz malih črk je v takem napadu vprašanje ur.

**`NAJKRAJSE_GESLO[child]` je odslej 8.** Starševskih 12 ostane.

Ta sprememba ne razveljavi nobenega obstoječega gesla: na produkciji otrokovo
geslo še ni nastavljeno, `credentials.secret_hash` je `NULL`. Dolžina se
preverja ob nastavitvi (`app/ukazi.py`), ne ob prijavi, zato tudi ni poti, po
kateri bi kdo ostal zaklenjen.

### F — žeton preverja vmesna plast, ne odvisnost

`ZetonMiddleware` stopi na mesto `ApiKeyMiddleware`, z istima razlogoma, ki
sta zapisana v `app/security.py` in `ADR-035` A: FastAPI telo prebere pred
razreševanjem odvisnosti, zato bi odvisnost pomenila, da strežnik
večmegabajtno sliko najprej prebere in šele nato ugotovi, da žetona ni — in
pot, ki je nihče ni dodal na noben seznam, mora biti varovana po privzetku.

Plast razreši sejo enkrat in jo poda v `scope["state"]`, od koder družino
prebere odvisnost. S tem odpade `daj_druzino_telefona` in z njim `ADR-029` A:
druga družina v bazi od zdaj ne ustavi ničesar več.

### G — poti prijave telefona

`POST /auth/login` in `POST /auth/logout`, JSON, **zunaj `/admin`** (piškotka
in CSRF žetona tam ni) in izvzeti iz preverbe žetona. Prijava teče skozi
obstoječi `prijava.preveri_prijavo`: isto omejevanje ugibanja, ista tabela
`login_attempts`, ista sporočila. Seja telefona je ista kot brskalnikova —
30 dni drsečega roka, `device_label`, takojšen preklic.

**Odjava je najprej lokalna.** Žeton se izbriše iz `expo-secure-store` v
vsakem primeru; klic na strežnik je najboljši poskus. Nedosegljiv strežnik ne
sme pustiti otroka prijavljenega na napravi.

### H — `401` ne pomeni `failed`

Danes `upload.ts` po `ADR-004` pošlje `401` in `403` v `failed` s sporočilom o
ključu. Odslej `401` pomeni „prijava je potekla": zapis **ostane `pending`**,
aplikacija pove *„Prijava je potekla, prijavi se znova"*, prenos počaka na
prijavo. To je izjema od pravila „4xx je sodba o vsebini zahteve" in je
izjema zato, ker se to stanje **more** spremeniti samo od sebe — s prijavo.

## Posledice

- **Kaj to olajša:** `V3-R07` dobi na telefonu že zapisanega lastnika zapisa
  in mu ga ni treba uvajati; `V3-R06` preklic sej velja za telefon brez
  dodatka, ker je tabela ista.
- **Kaj to oteži:**
  - Lokalna shema gre na verzijo **3** in z njo pride zamrznjena kopija
    `SHEMA_VERZIJE_2` za migracijski test (`ADR-004`).
  - Star APK neha delovati v trenutku, ko strežnik neha sprejemati ključ.
    **Vrstni red uvedbe ni poljuben:** na strežniku mora biti geslo za `masa`
    nastavljeno in nov APK nameščen, preden gre veja v produkcijo.
  - `Settings.api_key` odpade; z njim se dotaknemo `docker-compose.yml`,
    `okolje.primer`, `test_settings.py` in `test_postavitev.py`.
- **Na katere zahteve to vpliva:** `V3-R06` (ponastavitev gesla prekliče tudi
  sejo telefona), `V3-R07` (lastnik zapisa na telefonu že obstaja),
  `V1-R02` (`ADR-004`: `401` ni več `failed`), `V1-R04` / `ADR-006`
  (regresijski test ključa je prepisan, ne izbrisan).
