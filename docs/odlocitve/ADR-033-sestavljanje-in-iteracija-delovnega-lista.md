# ADR-033: Sestavljanje in iteracija delovnega lista

- **Datum:** 2026-09-15
- **Nastalo pri:** V4 (pred verzijo)
- **Status:** Sprejeto

## Kontekst

`ADR-032` pove, kaj delovni list **je**. Ta ADR pove, kako njegova vsebina
**nastane** in kako se popravlja, dokler lastnik ni zadovoljen.

Tok, ki ga lastnik hoče: izberem predmet in slike snovi, sistem sam priloži
opombe preteklih listov, jaz dodam še prosto navodilo, kliknem generiraj.
Osnutek preberem, napišem, kaj naj se popravi, in to ponovim, kolikorkrat je
treba. Šele ko sem zadovoljen, kliknem „kreiraj Word".

Odprta so bila štiri vprašanja: kaj je vhod, kaj vidi model ob popravku, kdo
pozna posebnosti posameznega predmeta, in kaj z nalogami, ki brez slike ne
delujejo.

## Možnosti

Za vhod ob popravku:

1. **Celotna zgodovina pogovora** — Za: model vidi, kaj si že zavrnil. Proti:
   cena desetega popravka je večkratnik prvega; stanje je razpršeno med
   sporočili, čeprav ga dokument že nosi v celoti.
2. **Trenutna vsebina in zadnje navodilo** — Za: cena vsakega popravka je
   enaka; resnica je na enem mestu. Proti: model ne ve, kaj si prej zavrnil,
   in lahko predlog ponovi.

Za navodila po predmetih:

1. **Eno splošno navodilo, vgrajeno na klicnem mestu** — Za: najmanj kode
   danes. Proti: ko se pokaže, da slovenščina terja drugačen pristop kot
   matematika, se navodilo razraste v zid besedila, ki ga ni mogoče razpletti.
2. **Navodilo, poiskano po predmetu, danes za vse enako** — Za: cena je nič,
   kasnejša razlika je ena veja. Proti: videti je kot nepotrebna plast.

## Odločitev

**A. Vhod v generiranje** so: prepisi izbranih snovi, zadnje tri opombe,
razred otroka, izbrani obseg in neobvezno prosto navodilo lastnika.

**B. Jemlje se prepis, ne slika.** Snov je že obdelana in prepis obstaja
(`docs/00-namen.md`). Ponovno branje slik bi bilo drugo branje iste stvari,
z drugim rezultatom in dodatnim stroškom.

**C. Ob popravku model vidi trenutno vsebino in zadnje navodilo**, ne
zgodovine pogovora (možnost 2). Vrne celoten dokument; pred shranjevanjem se
lastniku pokaže razlika, ker popravek ene naloge lahko tiho premakne ostale.
Zaporedje navodil se hrani kot zapis poti, prejšnje vsebine pa ne — hrani se
zadnja.

**D. Navodilo se poišče po predmetu** (možnost 2); danes vsi predmeti dobijo
isto besedilo. Vgrajeno besedilo na klicnem mestu je kršitev te odločitve,
tudi kadar je besedilo eno samo.

**E. Razred se ob generiranju prepiše v list.** Razred je lastnost otroka
(`V4-R02`) in se vsako jesen spremeni; brez prepisa bi lanski list čez leto
trdil, da je bil pisan za letošnji razred. Isti prijem kot pri vsebini:
zamrzne se, kar je bilo takrat res.

**F. Grafičnih nalog ni.** Geometrijske konstrukcije, zemljevidi in grafi
terjajo sliko, ki je iz besedila ni mogoče sestaviti. Navodilo modelu to
izrecno pove — sicer nastane „poglej sliko spodaj" brez slike.

**G. Prazen osnutek je dovoljen izid.** Če iz izbrane snovi po točki F ne
ostane dovolj za naloge, osnutek to pove in obsega ne zapolni z nepovezanimi
nalogami. Pošten prazen osnutek je boljši od polnega, ki zgreši snov.

**H. Opombe so vhod, ne le zapiski.** Ob generiranju se priložijo **zadnje
tri** opombe istega otroka pri istem predmetu. Prosto besedilo za to zadošča,
ker je porabnik jezikovni model in ne poizvedba — zato tabela rezultatov po
nalogah ni potrebna (`ADR-032` E). Število tri je ena sama konstanta na enem
mestu; da se bo spremenilo, je vprašanje časa.

## Posledice

- Kaj to olajša: cena popravka je konstantna; zanka „kaj je šlo narobe →
  naslednji list" deluje brez ene same nove tabele; razlika pokaže, kaj se je
  ob popravku še premaknilo.
- Kaj to oteži: model ob popravku ne ve, kaj si prej zavrnil, in lahko isti
  predlog ponovi — takrat mu to pove navodilo. Prosto besedilo opomb se ne da
  šteti in iz njega ni statistike.
- Na katere zahteve to odslej vpliva: `V4-R02` (razred), `V4-R04`
  (generiranje), `V4-R05` (iteracija), `V4-R06` (opombe kot vhod).
- Izbirnik snovi sledi `ADR-016`: brez naključja, brez shranjenega osnutka
  izbire, arhivirana snov v izbirniku ne nastopa.
