# ADR-028: Urnik je množica predmetov po dnevih; manjki so vrstica v pregledu po dnevih

- **Datum:** 2026-09-14
- **Nastalo pri:** V3 (pogovor pred verzijo)
- **Status:** Sprejeto
- **Preglaša:** `docs/verzije/v2.md`, `V2-R07`, razdelek „Razčiščeno pred
  izvedbo", alineja *„Urnika aplikacija ne pozna in ta zahteva ga ne uvaja.
  Primerjava »kateri predmeti so danes bili« bi zahtevala nov pojem in novo
  tabelo."* Tisti stavek ni bil omejitev za vedno, ampak meja tiste zahteve.
- **Stoji na:** `ADR-025` (družina je lastnik podatkov, otrok je uporabnik),
  `ADR-023` (pot `/admin/days`, teden je zadnjih sedem dni, prazni dnevi se
  izpišejo), `ADR-011` (arhiv je svoja os), `ADR-016` B (meja dneva je lokalna
  polnoč), `ADR-006` (vsaka pot pod `/admin` je znotraj omrežja javna),
  `ADR-017` A (brez ostranjevanja in tihega krajšanja)

## Kontekst

`/admin/days` odgovori na „kaj je Maša poslikala". Ne odgovori na **„česa ni
poslikala"** — za to bi moral sistem vedeti, kaj tisti dan sploh je bilo. Danes
to ve samo lastnik v glavi, kar je `V2-R07` izrecno zapisala kot mejo.

Lastnik hoče zdaj oboje: urnik poslikati (ne pretipkavati) in v pregledu po
dnevih videti, za katere predmete tistega dne **ni nobene slike**.

Odločitev nastaja **pred** izvedbo `ADR-025`, ker urnik brez lastnika ni
smiseln zapis: en strežnik, več družin, v družini več otrok — urnik je last
otroka, ne namestitve.

## Možnosti

### A — kako iz slike nastane zapis

1. **Popolnoma samodejno.** Kar vision model prebere, to velja. Za: nič dela.
   Proti: imena na šolskem urniku se s kodami (`SLJ`, `TJA`, `DKE`) redko
   ujemajo; ena napačno prebrana celica pomeni **tedensko ponavljajoč se lažni
   alarm** ali, huje, tiho odsotnost alarma.
2. **Model predlaga, starš potrdi.** Za: napaka prepisa se ujame enkrat, ob
   potrditvi, in ne vsak teden. Proti: en zaslon več (urejevalna mreža).
3. **Samo ročni vnos.** Za: brez tveganja prepisa. Proti: fotografiranje je
   celoten smisel te aplikacije; ročno tipkanje urnika je v njej tujek.

### B — vrstni red glede na V3

1. **Zdaj, brez lastnika.** Za: hitreje. Proti: takojšnja migracija ob `ADR-025`.
2. **Kot del V3, po uporabnikih.** Za: urnik se rodi z lastnikom. Proti: čaka.

### C — komu se manjko javi

1. **Samo `/admin/days`.** Za: nobene nove javne površine, nobene nove poti z
   API ključem; vzorec `ADR-021` F. Proti: Maša manjka ne vidi in ga isti dan
   ne more popraviti.
2. **Tudi na telefonu.** Za: edina pot, da manjko popravi še isti večer.
   Proti: nova pot z API ključem in novo vedenje na telefonu.

### D — kaj se zgodi ob novem urniku (polletje)

1. **Zgodovina z `velja_od`/`velja_do`.** Za: dan se sodi po urniku, ki je
   takrat veljal. Proti: dvakrat več sheme in poizvedbe z obdobjem.
2. **Nov nadomesti starega.** Za: en veljaven urnik, trivialna poizvedba.
   Proti: pregled za nazaj sodi po današnjem urniku.

### E — dan brez nobene slike

1. **Naštej vse predmete tistega dne.** Za: eno pravilo brez izjem. Proti:
   vsak praznik in vsak dan počitnic je vrstica s petimi manjki; stran postane
   šum in se neha brati.
2. **Ena vrstica „ta dan ni nobene slike".** Za: manjki se naštejejo samo tam,
   kjer je podatek nov — pri **delno** poslikanem dnevu. Proti: dan pouka brez
   slik ni razločen od praznika.
3. **Molk.** Za: nič šuma. Proti: skrije prav tisti dan, ki bi ga bilo treba
   videti.

### F — predmeti, ki se ne slikajo

Nekateri predmeti (LUM, GUM, TIT) so na urniku, slike pa iz njih praviloma ne
nastanejo. Brez varovalke bi ti predmeti manjko javljali vsak teden.

1. **Lastnost predmeta** v `PREDMETI`. Proti: seznam je trdo zapisan in
   podvojen v TypeScriptu in Pythonu, veljal bi za **vse** družine, pri
   `ADR-025` pa je predmet skupen, pričakovanje pa ne.
2. **Lastnost vnosa na urniku.** Proti: isto zastavico postaviš pri vsakem
   dnevu, kjer predmet nastopa.

## Odločitev

**A2 + B2 + C1 + D2 + E2 + F2.** Poleg tega:

**Urnik je množica predmetov na posamezen dan v tednu, brez ur in brez
zaporedja.** Dve uri istega predmeta v istem dnevu sta za to zahtevo ista reč:
zahteva se **vsaj ena** slika. Ure se lahko preberejo s slike zaradi
razporeditve v mreži, a v pogoju ne nastopajo. Izmeničnih (sodih/lihih) tednov
urnik ne pozna — v tej družini jih ni; če se kdaj pojavijo, je to nova
dimenzija zapisa in nova zahteva, ne popravek te.

**Slika urnika ni snov.** Živi v svoji tabeli in svoji mapi, nikoli v
`materials`. Sicer bi se pojavila v izbirniku kvizov (`ADR-016`), v statistiki
(`ADR-021`) in na strani predmeta — in iz ponedeljkove mreže bi nastalo pet
vprašanj o urniku.

**Manjki štejejo samo nearhivirane slike**, enako kot prikaz (`ADR-011`,
`ADR-023`). Stanje obdelave in berljivost na manjko ne vplivata: slika je
slika, tudi če je model z nje ni znal prebrati.

**Zamika ni.** Slika šteje k lokalnemu koledarskemu dnevu svojega `taken_at`
(`ADR-016` B). Snov, poslikana naslednje jutro, včerajšnjega manjka ne zapre in
načina „to je od včeraj" ta odločitev ne uvaja.

**Predmet, ki je poslikan, a ga tistega dne na urniku ni, ni napaka** in se ne
javlja. Urnik je pričakovanje, ne pravilo.

## Posledice

- **Kaj to olajša:** vprašanje „česa danes ni" dobi odgovor na strani, ki jo
  lastnik itak gleda zvečer. Nove poti ni — `/admin/days` dobi vrstico.
- **Kaj to oteži:**
  - **Pregled za nazaj sodi po trenutno veljavnem urniku** (D2). Po polletni
    menjavi bo november ocenjen po februarskem urniku. Sprejeto zavestno:
    stran je nadzor nad tekočim dnem in ne zgodovinski zapis — isto sklepanje
    kot `ADR-023` pri arhivu.
  - **Arhiviran dan izgleda kot dan s samimi manjki**, ker se arhivirane slike
    ne štejejo. Isti kompromis kot v `V2-R07`, le glasnejši. Kdor bo kdaj hotel
    manjke za nazaj, se mora najprej srečati z `ADR-011`.
  - **Dan pouka brez slik in praznik sta na strani videti enako** (E2). Cena
    tišine ob počitnicah; koledarja počitnic ta odločitev ne uvaja.
  - Nastane prvo mesto, kjer aplikacija hrani **pričakovanje** in ne dejstva.
    Napačen urnik odslej laže vsak teden, dokler ga nihče ne popravi — zato
    potrditev iz A2 ni prijaznost do uporabnika, ampak varovalka.
- **Na katere zahteve to vpliva:** `V2-R07` ostane v veljavi, razen zgoraj
  preglašene alineje. Vsaka prihodnja zahteva, ki bo hotela manjke po urah, po
  izmeničnih tednih, za arhivirane dneve ali za nazaj po starem urniku, je nova
  zahteva in ne popravek te.
