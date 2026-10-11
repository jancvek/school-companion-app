# ADR-058: Otrokov telefon se poveže s QR kodo, otrokovega gesla ni

- **Datum:** 2026-10-11
- **Nastalo pri:** pogovor pred V6 (zahteva `V6-R01`)
- **Status:** Sprejeto
- **Razveljavlja:** `ADR-036` E (otrokovo geslo 8 znakov); `V3-R04` kriterij
  1 (prijava z uporabniškim imenom in geslom) za otroka; `V3-R06` kriterij 2
  v delu „uporabniško ime, začetno geslo"; `ADR-038` C in D, kolikor veljata
  za otroka (začetno geslo, ponastavitev gesla).
- **Stoji na:** `ADR-027` (seje so neprozorni žetoni, poverilnica ni
  uporabnik), `ADR-036` A, B in D (prijava ne zapre aplikacije, lastnik je na
  vrstici, starš se na telefon ne prijavi), `ADR-038` A (deaktivacija je
  obrnljiva)

## Kontekst

Danes starš otroku izmisli uporabniško ime in geslo, otrok ju natipka na
telefonu. Družinske in šolske aplikacije (Seesaw, Rooster Money) mlajšim
otrokom gesel ne dajejo: starš pokaže QR kodo ali povezavo z omejenim rokom,
telefon jo prebere in je povezan.

Geslo kot edini faktor bi po NIST SP 800-63B-4 moralo imeti vsaj 15 znakov;
otrokovih 8 je pod to mejo, daljšega pa otrok ne bo tipkal.

## Možnosti

1. **Uporabniško ime in geslo** (danes). Proti: otrok tipka, pozablja; geslo
   je kratko; „pozabljeno geslo" pomeni starša, ki ga ponastavi in pove.
2. **QR in besedilna koda.** Besedilna koda pokrije tri primere: kamera ne
   dela, starš je drugje, družina ima en sam telefon. Prva dva tu nista
   ovira: brez kamere aplikacija nima smisla, sliko QR pa je mogoče poslati
   in skenirati z drugega zaslona.
3. **QR in povezava, ki odpre aplikacijo** (izbrano). Tretji primer (en
   telefon) reši gumb „Odpri na tem telefonu" brez tipkanja.

## Odločitve

### A — starš ustvari otroka samo s prikaznim imenom

Uporabniškega imena in gesla ni. Otrok nima poverilnice, s katero bi se
prijavil sam; telefon poveže starš.

### B — povezovalni žeton

Na `/admin/family` ima otrok dejanje „Poveži telefon". Strežnik ustvari žeton:
kriptografsko naključen, **enkraten**, s **kratkim rokom**, v bazi zgoščen,
vezan na otroka. Nov žeton razveljavi prejšnjega neporabljenega. Unovčenje
je omejeno po številu poskusov.

### C — QR nosi povezavo, ki odpre aplikacijo

QR vsebuje povezavo `school-companion://povezi?...`. Shema je že v
`app.json`, `expo-router` in `expo-linking` sta nameščena, branje kode zna
`expo-camera` — na telefonu nove odvisnosti ni. Pod QR je gumb „Odpri na tem
telefonu" z isto povezavo. **Besedilne kode ni.**

### D — unovčen žeton da sejo kot danes

Telefon žeton pošlje strežniku in dobi sejo otroka; ta se hrani v
`expo-secure-store` (`ADR-036`). Posvojitev zapisov brez lastnika, menjava
uporabnika na napravi in obnašanje ob potekli seji ostanejo po `ADR-036` in
`ADR-037`.

### E — „Prekliči prijave" nadomesti ponastavitev gesla

Otrok gesla nima, zato ponastavitve ni. Starš ima dejanje „Prekliči prijave",
ki izbriše vse seje otroka, z vmesno potrditvijo (`ADR-038` F). Nova
povezava obstoječih sej ne prekliče — dva telefona sta dovoljena.
Deaktivacija ostane po `ADR-038` A.

### F — mobilna prijava z geslom odpade

Starš se na telefon ne prijavi (`ADR-036` D), otrok gesla nima — mobilna
prijava z geslom nima več uporabnika. Otrokova geselna poverilnica (Maša) se
upokoji; njene obstoječe seje ostanejo veljavne.

### G — prijava aplikacije ne zapre

`ADR-036` A velja: brez povezave kamera, shranjevanje in zgodovina delajo,
prenos čaka. Na domači strani je namesto vnosa prijave „Poveži s QR kodo".

## Posledice

- **Kaj to olajša:** otrok ne tipka ničesar; ni kratkih gesel na javnem
  internetu; nov ali izgubljen telefon reši starš z eno kodo.
- **Kaj to oteži:**
  - Telefona brez starša ni mogoče povezati — namenoma.
  - Stari APK z zaslonom za prijavo po izteku seje ne more več noter; nov
    APK mora biti nameščen, preden seja poteče.
  - Izris QR na admin strani: brez skripte (`ADR-024`) to pomeni izris na
    strežniku in s tem **novo odvisnost na strežniku** — odloči faza 1, z
    odobritvijo lastnika.
- **Zavestno izpuščeno:** besedilna koda, Google za otroka, seznam
  povezanih naprav (`ADR-038` H velja naprej).
