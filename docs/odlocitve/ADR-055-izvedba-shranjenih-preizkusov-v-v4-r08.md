# ADR-055: Izvedba shranjenih preizkusov v V4-R08; ogled je druga predloga s skripto

- **Datum:** 2026-10-10
- **Nastalo pri:** V4-R08 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-053` (E, F, G), `ADR-054`, `ADR-039` A in F3, `ADR-051`,
  `ADR-011`, `ADR-025`, `ADR-035` D
- **Spreminja:** `ADR-054` — izjema od `ADR-024` odslej velja za **dve**
  predlogi (urejevalnik in ogled shranjenega preizkusa), skripta pa kliče
  strežnik na **dveh** naslovih (generiranje in shranjevanje). Vse ostale meje
  `ADR-054` veljajo naprej.

## Kontekst

Kriteriji `V4-R08` povedo, kaj se shrani in kaj se vidi, ne pa osmih stvari,
ki določijo kodo: kje je pregled, od kod naslov in model, ali ogled sme imeti
skripto, kaj poleg naštetega nosi tabela, ali se sme shraniti nespremenjena
kopija, kako Shrani pride do strežnika in kaj se zgodi ob ponovljenem kliku.
Faza 2 je pokazala še, da dve od teh odločitev spremenita trditve v prej
zelenih testih.

## Odločitve

### A — pregled je svoja stran, na predmetu samo povezava

Razdelek „Testi" na `/admin` vodi na `GET /admin/assessments`. Stran predmeta
z navodilom (danes `MAT`) dobi povezavo „Shranjeni testi (N)" na isti pregled
s filtrom `?predmet=<koda>`. Seznama testov na strani predmeta ni: stran je
že dolga, povezava stane eno štetje.

Pregled kaže teste vseh otrok družine, brez izbirnika otroka; ime samo pri
več otrocih (`ADR-051`, `ADR-039` F3). Neznana koda v filtru da prazen
seznam. Ostranjevanja ni.

### B — naslov prebere strežnik iz testa

Prva vrstica oblike `# …` v `test_md`, obrezana na 200 znakov. Če je ni, je
naslov `Test — <koda> — <datum>`. Polja za ročni vnos naslova ni: navodilo
modelu naslov že zahteva, in `v4.md` pravi, da ročnega urejanja besedila ni.

### C — model pove storitev, nosi ga brskalnik

`POST /admin/assessments/generate` vrača poleg treh polj še `model` (ime, kot
ga je vrnila storitev). Skripta ga hrani pri koraku in ob shranjevanju pošlje
model zadnjega veljavnega koraka.

Zavrnjeno: strežnik ob shranjevanju zapiše nastavitev
`OPENAI_MODEL_PREIZKUSI`. To je ime, ki smo ga zahtevali, ne ime, ki je
odgovorilo, in je napačno, če se nastavitev med delom zamenja.

Model je s tem trditev brskalnika. Iz njega ne izhaja nobena pravica;
ponarediti ga zna samo prijavljen starš v svoji družini.

**Posledica za teste:** `TestGeneriranje.test_odgovor_modela_gre_nazaj_kot_json`
in `TestPrazenTest.test_prazen_test_je_odgovor_s_sporocilom_modela` trdita
natančno enakost odgovora in dobita polje `model`. Pogodba se spreminja
namerno; trditvi jo pripenjata naprej.

### D — ogled je druga predloga, skripta izrisa je skupna

Shranjen test je markdown z LaTeX-om in ga izriše ista skripta kot v
urejevalniku. Ogled je nova predloga; del skripte, ki izrisuje in tiska
(`pripravi`, merilnik, tisk), živi v delni predlogi, ki jo z `include`
vključita obe. Skripta ostane vgrajena v izris, gradnje ni (`ADR-054`,
meja 1).

Zavrnjeno: ena predloga s tremi načini (že zdaj 816 vrstic) in izris na
strežniku (nova odvisnost, zavrnjena v `ADR-054`).

Ogled strežnika iz skripte **ne kliče** in ničesar ne pošilja. Besedilo iz
baze gre skozi isto čiščenje kot odgovor modela: shranjen test je še vedno
besedilo modela.

### E — tabela nosi še `base_id`, ID-jev slik pa ne

`base_id` (tuji ključ na `preizkusi.id`, `NULL` pri testu iz snovi) pove, iz
katerega shranjenega testa je nastal. Kasnejša migracija starim vrsticam tega
ne bi mogla več dati.

ID-jev slik snovi tabela ne hrani: slike se arhivirajo in brišejo, zamrznjeno
besedilo prepisov ostane (`ADR-053` F). Ogled in „nov test na tej osnovi"
zato kažeta snov kot besedilo, brez sličic.

### F — nespremenjena kopija se ne shrani

Pri „Nov test na tej osnovi" je Shrani onemogočen, dokler kazalec ne stoji
na vsaj enem novem koraku. Brisanja ni (`ADR-011`), zato bi vsak tak klik
pustil trajen dvojnik. Strežnik isto pravilo uveljavi sam: test, enak
izhodišču, zavrne.

### G — Shrani gre s `fetch`; identifikator zapisa izriše strežnik

`POST /admin/assessments`, telo je obrazec s CSRF žetonom kot pri
generiranju, odgovor je JSON z naslovom ogleda ali s slovensko napako. Ob
napaki delo ostane v oknu — pri navadnem obrazcu bi ga vsaka napaka
izbrisala.

Identifikator novega zapisa (UUID) nastane na strežniku ob izrisu
urejevalnika. Ponovljen `POST` z istim identifikatorjem v isti družini vrne
obstoječi zapis in ne naredi drugega; isti identifikator v drugi družini je
`409` (kot `POST /materials`, `ADR-029` D). „Zavrzi" identifikatorja ne
zamenja — do shranjevanja ne pomeni ničesar.

V skripti je `fetch` na **enem mestu** (pomožna funkcija), oba naslova izriše
strežnik v `data-` atributih.

**Posledica za teste:**
`TestSkriptaUrejevalnika.test_skripta_klice_streznik_na_enem_mestu_in_z_obrazcem`
je trdil dobesedni klic na `data-pot`. Prepiše se tako, da trdi lastnost, ki
jo je varoval: en `fetch`, naslovi samo iz atributov, ki jih izriše strežnik,
telo je obrazec.

### H — snov in naslovljenec ob shranjevanju

- **Test iz snovi:** strežnik snov sestavi iz identifikatorjev z
  `admin.prepisi_izbora`, kot pri vsakem klicu modela. Slika, arhivirana med
  delom, izpade; če ne preživi nobena, shranjevanje zavrne. Naslovljenec je
  edini otrok preživele snovi; pri več otrocih ga pošlje brskalnik in strežnik
  preveri, da je med njimi.
- **Test na osnovi:** snov, predmet in naslovljenec se prepišejo iz
  izhodišča; brskalnik pošlje samo njegov identifikator. Isto velja za klic
  modela: `generate` dobi `osnova=<id>` namesto identifikatorjev slik.
- Deaktiviran otrok je dovoljen naslovljenec: test je na papirju.

### I — opozorila

„Neshranjeno delo" je vsaj en korak v seznamu, tudi razveljavljen. Besedilo
v polju za željo ne šteje. Brskalnikovo opozorilo je `beforeunload`; lastno
okno je `<dialog>` na strani in ga sprožijo „Zavrzi", „← Nazaj" in povezave
ter odjava v glavi. „Prepisi te snovi" ne — odpre nov zavihek. „Zavrzi"
ostane v urejevalniku in počisti korake; pri testu na osnovi se vrne na
izhodišče.

## Posledice

- **Olajša:** nov predmet ali nov pogled na shranjen test uporabi isto delno
  predlogo za izris.
- **Oteži:** `TestBrezJavaScripta.IZVZETE` dobi dve predlogi (ogled in delno
  predlogo izrisa, ki leži v isti mapi in ni skrita v podmapi); meje ogleda
  je treba preverjati izrecno, kot pri vsaki izjemi. Obnašanje opozoril in
  shranjevanja dokaže samo ročni preizkus (faza 9b).
- **Vpliva na:** `V4-R07` (odgovor `generate` z `model`, skripta urejevalnika),
  `docs/01-arhitektura.md`, `test_tesnjenje.py` (nova tabela, nove poti, nov
  repozitorij).
