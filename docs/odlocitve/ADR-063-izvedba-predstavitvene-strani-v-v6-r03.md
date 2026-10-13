# ADR-063: Izvedba predstavitvene strani — pot, slog, povezave, popravki trditev

- **Datum:** 2026-10-13
- **Nastalo pri:** V6-R03 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-059` (javna predstavitvena stran), `ADR-060` A (slog in
  pisave kot točne javne poti), `ADR-062` B in C (odložene povezave, javno
  besedilo o zunanji storitvi), `ADR-036` F (popis poti brez žetona),
  `ADR-024` (brez skripte), `ADR-057` H (Google v načinu Testing)
- **Spreminja:** `ADR-062` B — povezave, ki jih je odložil, zdaj nastanejo
  (glej C); popis poti brez žetona iz `ADR-036` F dobi točno pot `/` (glej A);
  nabor javnih datotek iz `ADR-060` A dobi šesto točno pot (glej B).

## Kontekst

`ADR-059` pove, da stran živi na `GET /`, da je brez skripte in piškotkov in
da o podatkih govori isto besedilo kot soglasje. Štiri vprašanja je `v6.md`
pustil fazi 1, ob branju kode in posnetkov 01 pa so se pokazala še tri mesta,
kjer posnetek trdi nekaj, česar `main` ne zna ali imenuje drugače. Lastnik je
predloge faze 1 potrdil 13. 10. 2026.

## Odločitve

### A — `/` je točna pot brez žetona in brez seje; stran je za vse ista

`GET /` vrne predstavitveno stran vsakomur, tudi prijavljenemu staršu;
preusmeritve na `/admin` ni. Stran ne bere ne seje ne baze, zato je odgovor
neodvisen od piškotkov zahteve in sam ne postavi nobenega.

`/` gre v `IZVZETE_POTI` plasti `ZetonMiddleware` kot **točna pot**, ne
predpona — brez tega plast odgovori `401`, ker `/` ni pod `/admin`. Varovalni
test s popisom (`tests/test_security.py`) se zato **spremeni z lastnikovim
soglasjem**: popis dobi `/`, trditev o predponah ostane. `SejaMiddleware` se
ne spremeni; ujame se samo na `/admin`.

Zavrnjeno: preusmeritev prijavljenega na `/admin` — stran bi morala brati
sejo, in starš, ki želi stran pokazati drugemu staršu, je ne bi mogel odpreti.

### B — slog strani je svoja datoteka in šesta javna pot

Slog je `app/static/javno/slog.css`, postrežen pod `/admin/static/javno/slog.css`
in dodan v `JAVNE_DATOTEKE` kot točna pot, po vzorcu `ADR-060` A. Pisave so
iste štiri datoteke, ki so javne že od `V5-R01`. Žetone barv in pisave stran
prepiše iz `admin/slog.css`; skupne datoteke žetonov ni.

Zavrnjeno: (1) pravila strani v `admin/slog.css` — brez nove javne poti, a
vsaka stran pregleda bi nosila slog predstavitve in obratno; (2) predpona
`/static` zunaj `/admin` — nova izvzeta predpona je širša izjema kot ena
točna pot (`main.IZVZETE_PREDPONE`: „tu ne dodajaj ničesar brez ADR").

### C — „pravila zasebnosti" je sidro; odložene povezave nastanejo

Ločene strani s pravili ni. Razdelek „Kako ravnamo s podatki" ima sidro
`#zasebnost`; nanj kažejo meni, noga in povezava „pravila zasebnosti" ob
soglasju. Okno registracije dobi „← Domača stran", stran „Moj račun"
neodobrene družine „Na domačo stran" (`ADR-062` B). Celotno besedilo ob
soglasju (`<details>`) ostane: soglasje mora biti berljivo tam, kjer se da.

### D — poudarjena kartica nosi dobesedno javno besedilo

Kartica „Slike gredo v zunanji model" izpiše `sistem.BESEDILO_ZASEBNOST_JAVNO`
nespremenjeno; besedila s posnetka („Za prepis rokopisa uporabljamo model v
oblaku …") ni. Tako kriterij „en vir besedila" velja dobesedno in ga test
preveri z enakostjo niza, ne s podobnostjo.

### E — gumbi registracije so povezave; brez Googla jih ni

„Registracija" in „Registriraj se z Googlom" sta `<a href="/admin/register">`,
ne obrazec: obrazec bi terjal CSRF piškotek, stran pa piškotkov ne postavlja
(`ADR-059` B). Prijava je povezava na `/admin/login`. Na namestitvi brez
Googla (`google_na_voljo` ni res) gumbov registracije ni in plošča „Kako do
računa" ponudi samo Prijavo — okno registracije tam ne more ničesar.

### F — prikazi so HTML in CSS

Urejevalnik, list A4, telefon, izbor vprašanj in pas statistike so narisani s
HTML in CSS (`ADR-059` D), brez slik in brez KaTeX; ulomki so števec nad
imenovalcem. Edine slike na strani so vgrajeni SVG znaki.

### G — popravki trditev glede na posnetek 01

Stran trdi samo, kar `main` zna (`ADR-059` C). Kjer posnetek in aplikacija
govorita različno, velja aplikacija:

1. »Sestavi test« → »Kreiraj test« v besedilu in v glavi prikaza
   urejevalnika (naslov razdelka „Sestavi test v pogovoru" ostane, ker je
   opis in ne ime gumba).
2. Trije predlogi-gumbi v prikazu klepeta odpadejo: urejevalnik jih po prvem
   testu ne kaže.
3. „Nič se ne izgubi" → „Umaknjeno gre v arhiv".
4. Kartica „Podatki so družinski" dobi stavek, da skrbnik sistema vidi ime
   družine, imena in e-naslove staršev ter število otrok (`ADR-044` B,
   `ADR-062` P).
5. „Testi za matematiko, drugi predmeti sledijo" ostane (`ADR-059` C,
   `ADR-053`).
6. „Registracija vzame minuto" ostane: račun zunaj preizkusnih uporabnikov
   pride do obrazca in registracija na produkciji dela (preverjeno
   13. 10. 2026).

### H — `docs/00-namen.md` in stavek o načinu Testing

`00-namen.md` ne trdi več „ni odprta platforma" in „registracije ni";
nadomesti ju opis, ki drži: starš se registrira sam, lastnik vsako družino
odobri. `01-arhitektura.md` ne trdi več, da preizkus z računom zunaj
preizkusnih uporabnikov „še ni preverjen".

## Posledice

- **Kaj to olajša:** stran nima stanja; test jo preveri kot niz.
- **Kaj to oteži:** žetoni barv so na dveh mestih; sprememba palete pregleda
  strani ne spremeni sama.
- **Na katere zahteve to vpliva:** `V6-R02` (okno registracije in „Moj račun"
  dobita povezave), `V3-R04` (popis poti brez žetona), `V5-R01` (nabor javnih
  datotek).
- **Zavestno izpuščeno:** pravno besedilo pravil zasebnosti, SEO, ikona
  zavihka (Caddy na `/favicon.ico` še naprej odgovori `204`).
