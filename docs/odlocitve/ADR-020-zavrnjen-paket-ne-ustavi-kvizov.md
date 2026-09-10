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
   ničesar in ne blokira ničesar drugega (brez razbitja paketa to ne drži —
   glej „Popravek prve različice"); meja med začasnim in trajnim je že
   določena v `ADR-004`. Proti: zavrnjen poskus še vedno obtiči brez sledi in
   se pošilja znova ob vsakem obhodu.
3. **Stanje `failed` za poskuse z vidno oznako.** Za: sled je vidna. Proti:
   vmesnik in shema za primer, ki ga pričakujemo samo ob napaki v kodi; plan
   ga je izrecno izločil iz obsega.
4. **Zavrnjen poskus zavrzi.** Za: vrsta se sama očisti. Proti: izguba
   podatka, v nasprotju z `ADR-012`.

## Odločitev

**Možnost 2, z razbitjem zavrnjenega paketa na posamezne poskuse.**

- **Trajna zavrnitev** je odgovor 4xx razen 408 in 429 — ista meja, kot jo
  `ADR-004` določa za prenos slik.
- **Paket, zavrnjen s `422`, se v istem obhodu pošlje znova, po en poskus.**
  Sprejeti se označijo za prenesene; zavrnjeni ostanejo nepreneseni — kdaj se
  pošljejo znova, pove točka o pomnjenju spodaj. Paket z enim samim poskusom
  se ne ponavlja — njegova zavrnitev je že sodba o tem poskusu.
- **Razbija se samo ob `422`**, odgovoru na neveljavno vsebino paketa: slab
  poskus (neveljavna ocena, postavka, ki je ni) ali neusklajena pogodba med
  APK in strežnikom — v drugem primeru je zavrnjen vsak poskus. Ob 401, 403
  ali 404 ne gre za vsebino in bi strežnik zavrnil vsak poskus enako; poskusi
  takrat ostanejo, obhod pa gre brez ponavljanja naprej na seznam. Tudi med
  pošiljanjem po en poskus zavrnitev, ki ni `422`, razbijanje ustavi.
- **Posamič zavrnjen poskus si telefon zapomni za čas zagona aplikacije** in ga
  do naslednjega zagona ne pošilja več. Enako velja za paket z enim samim
  poskusom, zavrnjen s `422`. Pomnjenje je v pomnilniku in ne v bazi — isti
  vzorec kot odmik pri prenosu slik (odločitev 14 v `docs/plan/V1-R02.md`):
  ponoven zagon je znak, naj se poskusi znova. Ko je vzrok na strežniku
  odpravljen, gredo zavrnjeni gor sami ob naslednjem zagonu — ta je lahko čez
  več dni, če Android aplikacije v ozadju ne ubije. Nov zagon sprožijo tudi
  prisilno zaprtje aplikacije, ponovni zagon telefona in namestitev novega
  APK. Zavrnitve, ki niso `422` (401, 403, 404), se
  ne zapomnijo, ker krivda ni v poskusu: taki poskusi gredo znova ob vsakem
  obhodu, v enem paketu — en zahtevek na paket.
- `413` strežnik ne vrača: paket je v shemi omejen na 1000 poskusov, telefon
  jih pošlje največ 500, posrednika pred strežnikom ni. Če bi ga kdaj, bi
  razbitje pomagalo; ta odločitev ga ne pokriva.
- **Paketi so med sabo neodvisni.** Zavrnjen paket ne ustavi naslednjih paketov
  istega obhoda, in obhod gre naprej do branja seznama.
- **Omrežna napaka, potekel čas, 5xx, 408 in 429** obhod še naprej končajo
  pred branjem seznama, kot doslej: strežnik je nedosegljiv ali preobremenjen
  in branje seznama bi spodletelo ali ga dodatno obremenilo.
- **Neuspeh branja seznama** obhod konča kot doslej.
- `401` (napačen ključ) je trajna zavrnitev; seznam bo takrat zavrnjen enako
  in obhod se konča tam.
- Če med pošiljanjem po en poskus strežnik postane nedosegljiv, se obhod konča
  kot vsak drug: kar je bilo do takrat sprejeto, ostane označeno.

## Popravek prve različice

Prva različica tega ADR je izbrala možnost 2 **brez** razbitja paketa in o njej
trdila, da zavrnjen poskus „ne blokira ničesar drugega". To ni držalo, kar je
odkril pregled v tretjem krogu. Telefon pošlje najstarejših 500 neprenesenih
poskusov v enem paketu, strežnik pa paket sprejme vsega ali nič
(`resevanje.py`). Trajno zavrnjen poskus je zato vedno v prvem paketu, in vsak
poskus, ki ga Maša da za njim, pade v isti zavrnjeni paket. Kvizi bi prihajali
na telefon, ocene pa ne na strežnik — noben kviz ne bi bil več rešen in
`V2-R03` bi ostala brez rezultatov.

Lastnik se je za možnost 2 odločil na podlagi tega nepopolnega opisa. Ko je
dobil pravega, je izbral razbitje paketa.

Druga različica je razbijala ob **vsaki** trajni zavrnitvi. Četrti pregled je
pokazal, da bi ob napačnem ključu (401) ali manjkajoči poti (404) vsak obhod
poslal en paket in še vsak poskus posebej — do 501 zahtevek vsakih 5 minut,
vsi z istim odgovorom —, opis stroškov pa je govoril o „nekaj zahtevkih".
Lastnik je razbitje omejil na `422`.

Tretja različica je trdila, da je `422` edini odgovor o vsebini poskusov in da
razbitje stane „nekaj zahtevkov". Peti pregled je pokazal, da oboje ne drži:
razbitje se sproži, kadar ima paket vsaj dva poskusa, ne le ob novih ocenah,
zato bi z N obtičalimi poskusi vsak obhod poslal 1 + N zahtevkov, za vedno —
ravno ob obnovitvi strežniške baze, ki jo kontekst navaja kot vzrok. Ob
neusklajeni pogodbi pa FastAPI vrne `422` za vsak poskus, in vrsta bi rasla z
vsako oceno. Lastnik je izbral pomnjenje zavrnjenih za čas zagona aplikacije.

Plan in ta ADR ostajata sled vseh štirih korakov; velja besedilo zgoraj.

## Posledice

- **Kaj to olajša:** napaka v enem poskusu ne odreže telefona od novih kvizov
  in ne ustavi prenosa ostalih ocen. Nobeni drugi odločitvi ne nasprotuje:
  poskus se ne zavrže (`ADR-012`), neprenesen poskus se ne pobriše nikoli
  (`ADR-019` C), pogodba s strežnikom ostane ista.
- **Kaj to oteži:**
  - Zavrnjen poskus ostane na telefonu brez vidne sledi. **Stroški ob `422`:**
    ob vsakem zagonu aplikacije enkrat vsak paket in še vsak poskus posebej —
    za N obtičalih največ ceil(N/500) + N zahtevkov; paket z enim samim
    poskusom se ne razbija, zato en obtičal poskus stane en zahtevek —, nato
    do naslednjega zagona samo novi poskusi. Ob neusklajeni pogodbi je
    zavrnjen tudi vsak nov poskus: k novih ocen v enem obhodu stane 1 + k
    zahtevkov (en sam nov poskus en zahtevek), N pa raste z vsako oceno. Val
    ob zagonu je zato vse večji; obhod medtem drži zaporo in branje seznama
    kvizov se zamakne (vsak zahtevek ima 30 s omejitve). Android aplikacijo v
    ozadju pogosto ubije, zato se to ponovi ob vsakem ponovnem zagonu —
    omejeno, ne pa nič. **Ob 401, 403 ali 404** se nič ne zapomni: vsak obhod
    pošlje en zahtevek na paket. To ostaja znana omejitev; če se kdaj zgodi, je
    pravi popravek svoja zahteva (vidna sled ali popravek vzroka), ne tiho
    brisanje.
  - Kviz, ki mu pripada zavrnjen poskus, na strežniku ostane nerešen in se na
    seznamu vrača. Na telefonu ne čaka, če ima poskus za vsako postavko;
    napol rešen čaka naprej kot vsak drug.
- **Na katere zahteve to odslej vpliva:** `V2-R02` (nov kriterij), `V2-R03` in
  `V2-R04` ne.
