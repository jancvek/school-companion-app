# ADR-027: Poverilnice so ločene od uporabnika; neprozorni žetoni; API ključ odpade

- **Datum:** 2026-09-14
- **Nastalo pri:** V3 (pogovor pred verzijo)
- **Status:** Sprejeto
- **Stoji na:** `ADR-025` (družina je lastnik), `ADR-026` (HTTPS obstaja)
- **Razveljavlja:** vgrajen `API_KEY` kot način avtentikacije telefona
  (`docs/01-arhitektura.md`, `ADR-006` — regresijski test „401 brez ključa")

## Kontekst

Telefon se danes izkaže z enim samim ključem, ki pride v aplikacijo ob gradnji
in je zapisan v APK (`ADR-010` to izrecno beleži kot vidno ceno). Dokler je
APK ena sama datoteka na enem samem telefonu v zaprtem omrežju, je to
sprejemljivo.

Z `ADR-025` to preneha držati: vse družine dobijo **isti** APK, torej isti
ključ. Prvi prijatelj, ki datoteko odpakira, ima ključ vseh. Ključ neha biti
skrivnost in postane samo še stvar, ki jo je treba vzdrževati.

Hkrati je znano, da bo Google prijava prišla pozneje — najprej za starše, nato
morda za otroke. Če geslo zdaj zapišemo v tabelo `users`, bo Google pozneje
zahteval migracijo te tabele. To je edina odločitev v V3, ki jo je treba
sprejeti zdaj prav zato, ker bi se je pozneje ne dalo sprejeti poceni.

## Možnosti

### A — kje živi geslo

1. **Stolpca `username` in `password_hash` na `users`.** Za: najkrajša pot do
   prve prijave. Proti: Google pomeni nove stolpce, ki so za del uporabnikov
   `NULL`; en uporabnik ne more imeti hkrati gesla in Googla brez tretje
   oblike iste tabele.
2. **Ločena tabela poverilnic.** `credentials(user_id, vrsta, identifikator,
   tajnost_hash)`. Za: Google pozneje ni sprememba modela, ampak nova vrstica;
   isti uporabnik ima lahko oboje; odjava ene poverilnice ne briše osebe.
   Proti: en `JOIN` več in ena tabela več že v prvi zahtevi.

### B — oblika seje

1. **JWT.** Za: strežnik ne hrani stanja. Proti: preklica ni brez seznama
   preklicanih, kar je spet stanje; potrebuje osveževalni ples med kratkim in
   dolgim žetonom; ura veljavnosti postane nastavitev, ki jo je treba usklajevati
   med telefonom in strežnikom.
2. **Neprozoren naključni žeton v bazi.** Za: takojšen preklic („odjavi vse
   naprave"), en sam pojem, brez osveževanja; ustreza načelu „kar bi lahko
   bila mikrostoritev, naj bo funkcija". Proti: vsaka zahteva prebere vrstico
   iz baze — pri obsegu tega projekta nepomembno.

### C — API ključ

1. **Ostane kot druga plast.** Za: ključ pove „ta APK je naš", žeton pove „ta
   otrok je Maša"; menjava ene skrivnosti ne zahteva menjave druge.
   Proti: ena od obeh skrivnosti je javna, kar ni globinska obramba, ampak ena
   plast in eno vzdrževanje več.
2. **Odpade.** Za: en sam pojem avtentikacije; nič, kar bi bilo videti kot
   zaščita, a to ni. Proti: star APK neha delovati takoj, ko strežnik ključa ne
   sprejema več.

## Odločitev

**A2 + B2 + C2.**

```
users       (id, family_id, vloga: parent|child, prikazno_ime, ...)
credentials (id, user_id, vrsta: password|google, identifikator, tajnost_hash)
sessions    (id, user_id, zgostitev_zetona, ustvarjena, poteče, zadnja_uporaba, oznaka_naprave)
```

- **Poverilnica ni uporabnik.** V V3 nastane samo vrsta `password`, kjer je
  `identifikator` uporabniško ime (otrok) ali e-naslov (starš). Google je
  pozneje nova vrsta, ne nova shema.
- **Žeton je naključen, hranjen kot zgostitev.** Brskalnik ga nosi v piškotku
  (`HttpOnly`, `Secure`, `SameSite=Lax`), telefon v glavi `Authorization:
  Bearer`. Ista tabela, dva prenosnika.
- **Prehod z API ključa je oster, ne postopen.** Strežnik ne sprejema obojega.
  Uporabnikov je malo in en APK jih pokrije vse; obdobje, ko veljata oba
  načina, bi bilo daljše od same zamenjave.
- **Regresijski test iz `ADR-006` se ne izbriše, ampak prepiše**: „`POST
  /materials` brez ključa vrne 401" postane „brez veljavnega žetona vrne 401".
  Namen testa je bil vedno isti — dokazati, da izvzetje ene poti ni izvzelo
  vseh.
- **Obnovitve gesla po e-pošti ni**, ker ni SMTP in ga ta verzija ne uvaja.
  Staršu geslo ponastavi lastnik sistema, otroku njegov starš. To je zavestna
  meja, ne pomanjkljivost.
- **CSRF žeton na vsakem `POST` pod `/admin`.** `ADR-006` je to izrecno
  napovedal: *„Žeton bi zahteval sejo; seja bi zahtevala prijavo… Če kdaj
  pride možnost B3, naj z njo pride tudi žeton."* Zdaj je prišla.

Nove odvisnosti, ki jih ta odločitev zahteva (trdi rob 5 — vprašano vnaprej):

| Kje | Paket | Za kaj | Zakaj ne brez njega |
|---|---|---|---|
| `apps/server` | `argon2-cffi` | zgoščevanje gesel | lastne izvedbe zgoščevanja gesel se ne piše |
| `apps/mobile` | `expo-secure-store` | shramba žetona na telefonu | `expo-sqlite` in `AsyncStorage` nista šifrirana; žeton ne sme ležati ob slikah |

## Posledice

- **Kaj to olajša:** Google prijava je pozneje ena nova vrsta poverilnice in
  ena nova pot, brez migracije uporabnikov. Odjava naprave je brisanje ene
  vrstice.
- **Kaj to oteži:**
  - Telefon dobi stanje, ki ga doslej ni imel: kdo je prijavljen. To trči ob
    načelo *„aplikacija nikoli ne čaka na strežnik"*. Meja je zapisana v
    `V3-R04`: **fotografiranje in lokalno shranjevanje delujeta tudi s
    poteklim žetonom**; čaka prenos, ne kamera.
  - Vsaka obstoječa pot na strežniku dobi novo odvisnost od seje. To je
    dotik vseh usmerjevalnikov naenkrat, ne dodatek ob strani.
  - Star APK po zamenjavi ne deluje več. Lastnik mora zgraditi in razdeliti
    nov, preden stari ključ ugasne.
