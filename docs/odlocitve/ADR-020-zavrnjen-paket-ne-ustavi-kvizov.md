# ADR-020: Trajno zavrnjen paket poskusov ne ustavi prenosa kvizov

- **Datum:** 2026-09-10
- **Nastalo pri:** V2-R02 (odkril pregled v fazi 7, odločeno v fazi 9b)
- **Status:** Sprejeto
- **Preglasi:** odločitev 9 v `docs/plan/V2-R02.md` — stavek *„Napaka v koraku 1
  konča obhod (strežnik je nedosegljiv)"*, kolikor se nanaša na **trajno
  zavrnitev** paketa. Za omrežno napako in 5xx velja naprej.
- **Stoji na:** `ADR-004` (meja med začasnim in trajnim neuspehom), `ADR-012`
  (poskus je dogodek in se ne zavrže), `ADR-019` (reševanje na telefonu)

## Kontekst

En obhod usklajevanja kvizov na telefonu najprej pošlje neprenesene poskuse in
šele nato prebere seznam čakajočih kvizov. Plan je določil, da vsak neuspeh
pri pošiljanju obhod konča — razlog je bil nedosegljiv strežnik, pri katerem
branje seznama tako ali tako ne uspe.

Pregled je pokazal posledico, ki je plan ni zapisal. Strežnik lahko paket
**trajno** zavrne (`422`): neveljaven poskus ali postavka, ki je na strežniku
ni. Tak paket se na telefonu ne pobriše (`ADR-012`), zato ga vsak obhod pošlje
znova in vsak obhod se konča pred branjem seznama. **Od tega trenutka na telefon
ne pride noben nov kviz več**, in to brez vidne sledi. Nastane lahko ob napaki
v kodi ali ob obnovitvi strežniške baze iz starejše kopije.

## Možnosti

1. **Ostane, kot je.** Za: nič dela. Proti: napaka v enem samem poskusu ustavi
   vse nadaljnje kvize, brez sledi — škoda je nesorazmerna z vzrokom.
2. **Ob trajni zavrnitvi poskuse obdrži, seznam pa vseeno preberi.** Omrežna
   napaka in 5xx obhod še naprej končata. Za: zavrnjen poskus ne izgubi
   ničesar in ne blokira ničesar drugega; meja med začasnim in trajnim je že
   določena v `ADR-004`. Proti: zavrnjen poskus še vedno obtiči brez sledi in
   se pošilja znova ob vsakem obhodu.
3. **Stanje `failed` za poskuse z vidno oznako.** Za: sled je vidna. Proti:
   vmesnik in shema za primer, ki ga pričakujemo samo ob napaki v kodi; plan
   ga je izrecno izločil iz obsega.
4. **Zavrnjen poskus zavrzi.** Za: vrsta se sama očisti. Proti: izguba
   podatka, v nasprotju z `ADR-012`.

## Odločitev

**Možnost 2.**

- **Trajna zavrnitev** je odgovor 4xx razen 408 in 429 — ista meja, kot jo
  `ADR-004` določa za prenos slik. Takrat se poskusi paketa **ne** označijo za
  prenesene in ostanejo za naslednji obhod; obhod pa gre naprej.
- **Paketi so med sabo neodvisni.** Zavrnjen paket ne ustavi naslednjih paketov
  istega obhoda.
- **Omrežna napaka, potekel čas, 5xx, 408 in 429** obhod še naprej končajo
  pred branjem seznama, kot doslej: strežnik je nedosegljiv ali preobremenjen
  in branje seznama bi spodletelo ali ga dodatno obremenilo.
- **Neuspeh branja seznama** obhod konča kot doslej.
- `401` (napačen ključ) je trajna zavrnitev; seznam bo takrat zavrnjen enako
  in obhod se konča tam.

## Posledice

- **Kaj to olajša:** napaka v enem poskusu ne odreže telefona od novih kvizov.
  Nobeni drugi odločitvi ne nasprotuje: poskus se ne zavrže (`ADR-012`),
  neprenesen poskus se ne pobriše nikoli (`ADR-019` C).
- **Kaj to oteži:**
  - Zavrnjen poskus ostane na telefonu in se pošilja vsakih 5 minut, brez
    vidne sledi. To ostaja znana omejitev; če se kdaj zgodi, je pravi popravek
    svoja zahteva (vidna sled ali popravek vzroka), ne tiho brisanje.
  - Kviz, katerega poskusi so zavrnjeni, na strežniku ostane nerešen in se na
    seznamu vrača; na telefonu pa ne čaka, ker ima lokalne poskuse.
- **Na katere zahteve to odslej vpliva:** `V2-R02` (nov kriterij), `V2-R03` in
  `V2-R04` ne.
