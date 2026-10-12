# ADR-061: Izvedba povezave telefona s QR kodo v V6-R01

- **Datum:** 2026-10-12
- **Nastalo pri:** V6-R01 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-058` (otrokov telefon s QR, gesla ni), `ADR-027`
  (neprozorni žetoni, v bazi zgostitev), `ADR-036` in `ADR-037` (seja na
  telefonu, posvojitev, oznaka odjave), `ADR-038` (vmesna potrditev, tri kode
  zavrnitve), `ADR-034` A (naslov odjemalca ni podatek), `ADR-024` (stran brez
  skripte)
- **Dopolnjuje:** `ADR-058` — ta pove *kaj*, ta ADR pove *kako* in zapre, kar
  je `docs/verzije/v6.md` pustil odprto za fazo 1.

## Kontekst

`ADR-058` je sprejel povezovalni žeton, QR s povezavo `school-companion://povezi?...`
in ukinitev otrokovega gesla. Odprto je pustil: s čim se QR izriše, rok žetona
in mejo poskusov, kaj vidi stari APK, kaj pomeni „upokoji" za obstoječo
poverilnico in kaj naredi telefon, ki sejo že ima. Lastnik je predloge iz faze 1
potrdil 12. 10. 2026.

## Odločitve

### A — QR izriše strežnik s paketom `segno`

Nova odvisnost na strežniku (`CLAUDE.md` §2, rob 5 — odobreno). `segno` je
čisti Python brez lastnih odvisnosti, vrne SVG, ki gre **vgrajen v stran**: brez
skripte, brez zunanjega vira in brez nove poti, ki bi stregla sliko z žetonom.
Različica je pripeta z zgornjo mejo, kot SQLAlchemy.

Zavrnjeno: lasten kodirnik (napaka pomeni kodo, ki je telefon ne prebere, in
je test ne ujame) in skripta v brskalniku s prepisano knjižnico (nova izjema
od `ADR-024`).

### B — tabela `link_tokens`, žeton se ob unovčenju izbriše

```
link_tokens (id, family_id NOT NULL, child_id NOT NULL, token_hash UNIQUE,
             created_at, expires_at)
```

- Žeton je `secrets.token_urlsafe(32)`; v bazi samo SHA-256, kot pri seji.
- **Rok je 10 minut.**
- **Otrok ima največ en žeton.** Nov žeton prejšnjega izbriše v isti
  transakciji.
- **Unovčenje je pogojni `DELETE`** (zgostitev se ujema, rok ni potekel);
  seja nastane samo, če je bila izbrisana natanko ena vrstica, v isti
  transakciji. Enkratnost je tako lastnost stavka, ne branja pred njim — dva
  hkratna poskusa z istim žetonom ne dobita dveh sej.
- Vrstice `used_at` ni: porabljen, potekel in neznan žeton so za telefon isto
  stanje z istim sporočilom, zato sledi, ki bi jih ločila, nihče ne bere.
  Žeton je kot seja, ne kot vprašanje — načelo „nič se ne briše" (`ADR-012`)
  velja za podatke družine, ne za poverila.
- Potekli žetoni se čistijo ob vsakem ustvarjanju in vsakem poskusu unovčenja.
- `family_id` je na vrstici, čeprav je izpeljiv iz otroka: ustvarja in
  preklicuje jo `ClaniRepository` z družino v konstruktorju (`ADR-025`).
  Unovči jo `PrijavaRepository`, ki družine ne pozna — pozna samo žeton, kot
  prijava pozna samo identifikator.

### C — povezava nosi samo žeton

`school-companion://povezi?z=<žeton>`. Naslov strežnika ima aplikacija iz
gradnje; povezava, ki bi ga nosila, bi bila način, kako telefon poslati k
tujemu strežniku.

### D — poti

| Pot | Metoda | Kaj |
|---|---|---|
| `/admin/family/members/{id}/link` | POST | ustvari žeton in izriše stran s QR in gumbom „Odpri na tem telefonu"; `Cache-Control: no-store` |
| `/admin/family/members/{id}/link` | GET | 303 na `/admin/family` — stran ni zaznamek in pot ne sme biti videti kot 405 |
| `/admin/family/members/{id}/revoke` | GET, POST | vmesna stran in „Prekliči prijave" |
| `/auth/link` | POST | JSON `{token}` → isti odgovor kot dosedanja prijava (`token`, `user_id`, `display_name`, `expires_at`) |
| `/auth/login` | POST | **ostane kot škrbina**: vedno `401` s slovenskim sporočilom, baze ne bere |

- **Žeton nastane s `POST` in CSRF, brez vmesne potrditve.** Razveljavi
  prejšnjega, zato ni `GET`; vmesna stran pa je po `ADR-038` F za posledice, in
  posledica je tu samo, da prejšnja, neporabljena koda neha veljati. Osvežitev
  strani ustvari nov žeton.
- **„Poveži telefon" velja samo za aktivnega otroka te družine.** Tuj in
  neobstoječ `id` sta `404` z istim besedilom, starš in deaktiviran otrok `403`
  (`ADR-038`, tri kode).
- **`/auth/link` je točna pot v `IZVZETE_POTI`**, ne predpona: žeton seje na
  njej šele nastane, kot na `/auth/login`.
- **Škrbina `/auth/login`** obstaja zaradi starega APK, ki besedilo zavrnitve
  izpiše dobesedno; brez nje bi otrok videl „Not Found". Odstranitev je svoja
  zahteva, ko starega APK ni več na nobenem telefonu.
- **Pot ponastavitve gesla za otroka** vrne `403` z razlago in je seznam ne
  ponudi; odloči isto pravilo (`clani.zakaj_ne_sme_ponastaviti_gesla`).

### E — meja poskusov je upočasnitev, skupna za namestitev

Neuspel poskus unovčenja nima identifikatorja, naslov odjemalca pa ni podatek
(`ADR-034` A). Meja je zato ena za vso namestitev: po **5 neuspehih v
15 minutah** vsak nadaljnji poskus čaka **2 s**, preden se žeton sploh
preveri — isti prag in isti zamik kot pri prijavi (`ADR-035` E).

- Neuspehi se beležijo v `login_attempts` pod stalno oznako, ki ne more biti
  identifikator računa. Nove tabele ni.
- **Uspeh števca ne pobriše**, za razliko od prijave: števec je skupen, zato
  bi tuj uspeh pobrisal napadalčeve poskuse.
- **Zaklepa ni.** Zaklep bi pomenil, da kdorkoli z interneta ustavi
  povezovanje vsem družinam. Žeton ima 256 bitov; meja je tu zaradi kriterija
  in zaradi obremenitve, ne zato, ker bi bil žeton ugibljiv.

### F — eno sporočilo za vsak neveljaven žeton

Potekel, porabljen, neznan, žeton deaktiviranega otroka in žeton ugasnjene
družine dajo `401` z istim besedilom: *„Koda ne velja več. Prosi starša za
novo."* Razlika bi povedala, da žeton obstaja ali je obstajal.

### G — „Prekliči prijave" izbriše seje **in** neporabljen žeton

V eni transakciji. Preklic, po katerem bi še deset minut veljala koda na
zaslonu, ne bi bil preklic. Isto naredi deaktivacija otroka. Nova povezava
obstoječih sej **ne** prekliče (`ADR-058` E).

### H — otrokove geselne poverilnice migracija izbriše

Migracija `0014` izbriše vrstice `credentials` vrste `password` vseh
uporabnikov z vlogo `child`, v vseh družinah. `ADR-058` F pravi „se upokoji";
shema poverilnic takega stanja nima in novi otroci poverilnice sploh ne bodo
imeli (`ADR-058` A), zato vrstica, ki je nihče ne more uporabiti, ne ostane.
Uporabniško ime (npr. `masa`) se s tem sprosti.

Seje visijo na `users`, ne na `credentials`, zato **ostanejo veljavne**.
`downgrade` tabelo `link_tokens` spusti, poverilnic pa **ne vrne** — otrok se
po vrnitvi ne more prijaviti, dokler mu poverilnica ne nastane znova. To je
zapisana cena.

### I — telefon, ki sejo že ima, jo ob povezavi zamenja

Povezava je pot po „Prekliči prijave" (telefon še hrani mrtev žeton) in pot
menjave otroka na skupnem telefonu. Zaporedje: unovči → `shraniSejo(nova)`
(prepiše staro pod istim ključem) → posvojitev → počisti oznako odjave →
`setSeja` → odjava prejšnje seje na strežniku kot najboljši poskus.

- Unovčenje je **prvo**: če spodleti, ostane vse, kot je bilo.
- Oznake iz `ADR-037` ta pot ne postavlja: stari žeton ne ostane na disku, ker
  ga novi prepiše v enem zapisu.
- Zapisi prejšnjega otroka ostanejo njegovi (`ADR-036` B); zapise brez lastnika
  posvoji novi — ista, že zapisana posledica kot pri prijavi.

### J — en zaslon za kamero in za odprto povezavo

`app/povezi.tsx` je cilj povezave (`expo-router` ga razreši iz sheme) in hkrati
bralnik: s parametrom `z` unovči takoj, brez njega odpre kamero
(`expo-camera`, samo vrsta `qr`). Prebrana koda, ki ni naša povezava, da
*„To ni koda Šolskega pomočnika."* in bralnik teče naprej. Nove odvisnosti na
telefonu ni in lokalna shema se ne spremeni.

Zaslon `app/prijava.tsx` ostane samo kot odjava. Besedila, ki so otroka
pošiljala k prijavi, ga odslej pošiljajo k staršu („prosi starša za novo
kodo").

## Posledice

- **Kaj to olajša:** otrok ne tipka ničesar; izgubljen ali nov telefon reši
  starš z eno kodo; mobilna prijava z geslom in njena meja dolžine odpadeta.
- **Kaj to oteži:**
  - Nova odvisnost na strežniku in nova tabela z migracijo, ki briše podatke
    in se ne da vrniti.
  - Prej zeleni testi otrokove prijave z geslom, dodajanja otroka z
    uporabniškim imenom in ponastavitve otrokovega gesla se prepišejo — dokazovali
    so vedenje, ki ga `ADR-058` ukinja. Seznam je v `docs/plan/V6-R01.md`.
  - Stran s QR nosi žeton v izrisu (v `href` in v SVG). Zato `no-store`, rok
    10 minut in enkratna raba.
  - Skupna meja poskusov pomeni, da lahko tujec povezovanje vsem upočasni za
    2 s. Sprejeto; zaklep bi bil hujši.
- **Na katere zahteve to vpliva:** `V3-R04` (prijava na telefonu — vnos
  nadomesti povezava), `V3-R06` (obrazec za otroka, ponastavitev gesla),
  `V6-R03` (predstavitvena stran omenja povezavo s QR).

## Dopolnitve med izvedbo in po pregledih (12. 10. 2026)

Spodnje odločitve so nastale ob izvedbi in ob dveh pregledih. **Dopolnjujejo**
tekst zgoraj, ne razveljavljajo ga.

### Ukaz `nastavi-geslo` otroka zavrne

Plan je predvidel, da ukaz otroka „ne najde", ker poverilnice nima. Vrstica,
ki je v bazi ostala mimo migracije `0014`, bi pa geslo vseeno dobila. Ukaz
zato račun z vlogo, ki ni starš, zavrne izrecno in po geslu sploh ne vpraša.

### Aplikacija pokaže besedilo strežnika samo ob `401`

`401` je edini odgovor, za katerega aplikacija ve, da ga je napisala pot
povezave in da je v slovenščini. Vsak drug 4xx — `404` strežnika, ki poti še
nima, ali `422` — bi na zaslon prinesel angleško besedilo ogrodja, kar merilo
dokončanosti prepoveduje. Takrat aplikacija pokaže svoje sporočilo.

### Ponovitev iste kode samo po nedosegljivem strežniku

Prvi pregled je našel, da „Poskusi znova" pri odprti povezavi žetona ne pošlje
znova — in prav to je pot družine z enim telefonom. Drugi pregled je našel,
da ga popravek pošlje znova tudi po zavrnitvi, kjer vsak pritisk šteje v
skupno mejo iz E. Sklep: napaka nosi podatek, ali je poskus ponovljiv; to je
samo nedosegljiv strežnik (omrežje, 5xx, 408, 429). Po zavrnjeni odprti
povezavi gumba za ponovitev ni; ostane kamera, če je na voljo.

### Seja, ki je telefon ne more shraniti

Če varna shramba po unovčenju odpove, je koda porabljena, seje pa telefon
nima. Aplikacija takrat pove, da je potrebna **nova koda**, in pravkar
ustvarjeno sejo na strežniku odjavi (najboljši poskus). Prejšnja seja, če je
bila, ostane nedotaknjena.

### Povezava počaka na branje žetona ob zagonu

Povezava, ki aplikacijo šele odpre, sproži unovčenje, še preden je steklo
branje žetona z diska. Brez čakanja bi to branje novo sejo v stanju prepisalo
s staro, ob oznaki iz `ADR-037` pa pravkar shranjen žeton pobrisalo. `povezi`
zato počaka na konec branja ob zagonu in šele nato pogleda, katero sejo
zamenjuje. Najdeno s testom, ne z branjem.

### Zavestno neodpravljeno

Zapisano kot znane omejitve v `docs/01-arhitektura.md`: sočasnost unovčenja
je utemeljena z zasnovo in ne dokazana s testom; „največ en žeton na otroka"
drži zaporedno; nova povezava med zahtevo, ki še teče, sproži drugo zahtevo.
