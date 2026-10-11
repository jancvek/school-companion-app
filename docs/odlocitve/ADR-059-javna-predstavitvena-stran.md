# ADR-059: Javna predstavitvena stran na lastnem strežniku

- **Datum:** 2026-10-11
- **Nastalo pri:** `POC-03` (zahteva `V6-R03`)
- **Status:** Sprejeto
- **Stoji na:** `ADR-057` (samoregistracija z Googlom), `ADR-056` (nov
  videz, pisava z lastnega strežnika), `ADR-024` (JavaScript na admin
  strani), `ADR-026` (strežnik na javnem internetu), `ADR-053` (preizkus)

## Kontekst

Z `ADR-057` se starš registrira sam. Prvi stik neznanega starša s Šolskim
pomočnikom je zato naslov strežnika — ne več lastnik, ki mu aplikacijo
razloži v živo. Danes `/` ne vrne ničesar, `/admin` pa pelje na prijavo, ki
ne pove, kaj aplikacija je, za koga je in kam gredo slike.

Lastnik želi kratko stran, ki to pove, s poudarkom na sestavljanju testov
(to mu najbolj pomaga) in na kvizih, ter ponudi registracijo in prijavo
(`POC-03`).

## Možnosti

1. **Brez predstavitvene strani** — prijavna stran dobi gumb „Registracija".
   Za: nič novega. Proti: starš odda zahtevek in potrdi soglasje, ne da bi
   vedel, kaj dobi; besedilo soglasja nima konteksta.
2. **Statična stran na istem strežniku, na `/`** (izbrano). Za: en strežnik,
   ena domena, ista pisava in žetoni; povezave na registracijo in prijavo so
   lokalne. Proti: strežnik prvič streže stran brez prijave, ki ni prijavna.
3. **Ločeno gostovanje** (npr. statična stran pri tretjem ponudniku). Za: nič
   ne obremeni domačega strežnika. Proti: tretja stran in druga domena
   (`ADR-026`), besedilo se razide z aplikacijo, dva kraja za objavo.

## Odločitve

### A — stran živi na `GET /` istega strežnika

Javna, brez seje, predloga kot ostale. Ne bere baze in ne kaže podatkov
nobene družine. Vodi na registracijo (`V6-R02`) in na prijavo.

### B — brez skripte, sledenja, piškotkov in virov tretjih strani

`ADR-024` velja v celoti; izjema iz `ADR-054` se tu ne uporablja. Pisava,
slike in slog so z lastnega strežnika (`ADR-056`). Ni analitike, ni
vgrajenih vsebin, ni CDN-ja.

### C — vsebina: testi prvi, kvizi drugi

Vrstni red in vsebina razdelkov sta v `POC-03` (*Dogovorjeno*, *Ugotovitve*,
posnetki 01). Stran trdi samo, kar `main` na dan objave zna; edina izjava o
prihodnosti je zapisani namen „drugi predmeti sledijo" pri testih
(`ADR-053`). Datumov in trgovin ne obljublja.

### D — prikazi funkcij so statični

Urejevalnik, list A4, telefon in statistika so narisani s HTML in CSS z
izmišljenimi podatki. Niso posnetki pravih družin in niso žive komponente.

### E — o podatkih govori isto besedilo kot soglasje

Razdelek „Kako ravnamo s podatki" in soglasje ob registraciji (`ADR-057` D)
izhajata iz enega vira v `app/sistem.py`. Besedilo naravnost pove, da slike
gredo v OpenAI. Današnje `BESEDILO_ZASEBNOST` je napisano za lastnika, ki
odpira družino znancu, in trdi, da aplikacija ni objavljena — prepisati ga je
treba, preden je stran javna (`POC-03` *Pasti*).

## Posledice

- **Kaj to olajša:** neznan starš pred registracijo ve, kaj dobi in kam gredo
  slike; soglasje ni prvi stik s tem podatkom.
- **Kaj to oteži:**
  - Stran je obljuba javnosti. Vsaka sprememba funkcij jo lahko naredi
    neresnično, zato je trditev na strani del kriterijev zahteve, ki jo
    spremeni.
  - Strežnik prvič streže stran brez prijave, ki ni prijavna; `/` mora
    ostati izven vsega, kar zahteva sejo.
- **Na katere zahteve to vpliva:** `V6-R02` (gumb Registracija vodi s
  strani, besedilo soglasja), `V6-R03` (stran sama). `docs/00-namen.md`
  („Ni odprta platforma", „registracije ni") se popravi ob zaključku `V6-R02`
  oz. `V6-R03`.
- **Zavestno izpuščeno:** iskalniki (SEO), analitika, jezikovne različice,
  pravno besedilo pravil zasebnosti in lastna domena — vse so nove zahteve,
  če bodo.
