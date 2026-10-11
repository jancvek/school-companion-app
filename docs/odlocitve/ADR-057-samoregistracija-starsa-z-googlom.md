# ADR-057: Starš se registrira sam z Googlom, družino odobri lastnik sistema

- **Datum:** 2026-10-11
- **Nastalo pri:** pogovor pred V6 (zahteva `V6-R02`)
- **Status:** Sprejeto
- **Razveljavlja:** `ADR-025` alinejo „Registracija je zaprta"; `V3-R08`
  kriterij 3 v delu „Prijava z Googlom ne ustvari uporabnika in ne ustvari
  družine"; `ADR-044` C v delu „ni obrazca soglasja".
- **Stoji na:** `ADR-025` (družina je lastnik, ločnica lastnik sistema /
  starš), `ADR-027` (poverilnica ni uporabnik), `ADR-044` (pogled lastnika;
  meja B ostane), `ADR-046` (Google prijava, `sub`, `email_verified`)

## Kontekst

Danes družino in prvega starša odpre lastnik sistema na `/admin/system`
(`V3-R05`): vpiše e-naslov in začetno geslo ter ju staršu preda sam. Lastnik
želi, da se starš registrira **sam**, lastnik pa ga le **odobri ali zavrne**.

Pregledana praksa: zaprte aplikacije uporabljajo vabila (enkratna povezava z
rokom), družinske in šolske aplikacije pa skrbnika, ki odobri; nobena ne
pošilja začetnih gesel. Za žetone v povezavah veljajo pravila OWASP
(naključni, enkratni, z rokom, vezani na uporabnika, brez samodejne prijave).

## Možnosti

1. **Vabilo, registracija ostane zaprta.** Za: standardno, nič javnega.
   Proti: lastnik mora pred prvim stikom vsakega starša nekaj narediti; tega
   lastnik izrecno noče.
2. **Samoregistracija z e-naslovom in geslom, nato odobritev.** Proti: brez
   potrditve e-naslova si kdorkoli zasede tuj naslov (`credentials.identifier`
   je enoličen čez namestitev). S potrditvijo pride SMTP, za tem lastna
   domena (SPF, DKIM, DMARC — DuckDNS tega ne zmore), ponudnik pošiljanja,
   žetoni, predloge in pozabljeno geslo — zahteva velikosti `V3-R08`. Pošta z
   domačega IP-ja ne pride skozi.
3. **Samoregistracija samo z Googlom, nato odobritev** (izbrano). Za: Google
   e-naslov potrdi sam (`email_verified`, `ADR-046`); gesla, pozabljenega
   gesla in pošte ni; prijava z Googlom je že zgrajena. Proti: starš brez
   Google računa se sam ne more registrirati — zanj ostane ročna pot (I).

## Odločitve

### A — registracija je samo z Googlom

Na prijavni strani je „Registracija z Google računom". Ko Google vrne `sub`,
ki ga še nihče nima, starš izpolni obrazec (ime družine, prikazno ime,
soglasje — D); šele oddan obrazec ustvari družino, starša, poverilnico
`google` in sejo. Povratni klic sam ne ustvari ničesar.

**Registracije z e-naslovom in geslom ni.** Obstoječi računi z geslom
ostanejo, kot so.

Če se Googlov e-naslov ujema z obstoječo geselno poverilnico, se računa
samodejno **ne** združi (pot do prevzema računa); sporočilo pove, naj se
starš prijavi z geslom in Google poveže v nastavitvah (`V3-R08`). Da tak
naslov obstaja, s tem izve — enaka cena kot pri `ADR-038` E.

### B — stanje je na družini: `čaka`, `odobrena`, `zavrnjena`

Odobri se **družina**, ne oseba: drugi starš in otroci nastanejo v že
odobreni družini in lastnika ne potrebujejo. Stanje je ločeno od
`families.is_active` (deaktivacija, `ADR-044` A) — gre za dve različni
vprašanji: ali je bila družina sprejeta in ali je trenutno prižgana.

Obstoječe družine dobijo z migracijo `odobrena`. Družina, ki jo odpre lastnik
ročno (I), nastane `odobrena`.

### C — starš neodobrene družine vidi samo stran „Moj račun"

Zapora je **odvisnost usmerjevalnika**, ne `if` v vsaki poti — vzorec
`ADR-044` G: vsaka pot pod `/admin`, razen strani računa in odjave, za sejo
neodobrene družine preusmeri na „Moj račun". Pot, dodana jutri, je zaprta
sama od sebe; test se generira iz seznama poti.

- `čaka`: prikazno ime, Googlov e-naslov, ime družine in besedilo, da mora
  račun odobriti administrator.
- `zavrnjena`: samo, da je bil zahtevek zavrnjen, in gumb „Izbriši moj
  račun" (G).

Telefona se to ne dotakne: starš se tja ne prijavi (`ADR-036` D), otrok v
neodobreni družini ne more nastati.

### D — soglasje je potrditveno polje ob registraciji

`ADR-044` C je obrazec soglasja zavrnil, ker je bil krog znancev. Z javno
registracijo ta predpostavka ne drži več. Ob registraciji je besedilo o
zunanjem vision API-ju (`app/sistem.py`) in potrditveno polje; brez potrditve
registracija ne nastane. Čas potrditve se zapiše pri družini.

Za družine, ki jih odpre lastnik ročno, velja `ADR-044` C naprej.

### E — lastnik odloča na `/admin/system`

Ni nove strani, ampak razširitev obstoječe — meja „samo lastnik, za vse
ostale 404" (`ADR-044` G, `ADR-045`) velja brez dodatnega dela.

- **Čaka na odobritev:** ime družine, ime starša, Googlov e-naslov, datum.
  „Odobri" in „Zavrni" sta `POST` s CSRF in vmesno potrditvijo (`ADR-038` F).
- **Družine:** obstoječi seznam s stanjem.
- **Uporabniki:** tabela staršev vseh družin (ime, e-naslov, družina, način
  prijave, stanje, datum). **Otroci samo kot število** — `ADR-044` B ostane.
- Število čakajočih je vidno v navigaciji lastnika.

Odločitev je obrnljiva: zavrnjeno družino lahko lastnik pozneje odobri.
Obvestil (e-pošta, push) ni — lastnik pogleda stran.

### F — zahtevki čakajo, dokler lastnik ne odloči

Zahtevek ne poteče. Zaščita pred zlorabo javnega obrazca: omejevanje po IP
(vzorec `login_attempts`) in zgornja meja čakajočih družin; ob doseženi meji
obrazec pove, naj starš poskusi pozneje. CAPTCHA-e ni (tretja stran v poti,
`ADR-026`).

### G — izbris zavrnjenega računa je izjema od „nič se ne briše"

Zavrnjena družina nima vsebine: otrok, slik in kvizov v njej ni mogel
ustvariti nihče. Izbris odstrani družino, starša, poverilnice in seje ter
sprosti Google račun za ponovno registracijo. Brisanje odobrenih družin ostane
izven obsega (`ADR-044`).

### H — Google ostane v načinu Testing, lastne domene ni

Googlova dokumentacija (*Manage App Audience*): če aplikacija zahteva samo
ime, e-naslov in profil, *„your users do not need to be in the trusted user
list, they will not see a warning message, and their authorizations will not
expire after 7 days"*. Naša zahteva samo `openid`, `email`, `profile`.
Trditev v `docs/01-arhitektura.md`, da se lahko prijavijo samo ročno vpisani
preizkusni računi, je zato napačna in se popravi v `V6-R02`. Preizkus z
računom, ki ni na seznamu, je pogoj pred mergem.

Lastna domena bo potrebna šele za Trgovino Play (politika zasebnosti,
spletna povezava za izbris računa) — to ni ta odločitev.

### I — ročna pot lastnika ostane

Obrazec „nova družina" na `/admin/system` (`V3-R05`) ostane za starša brez
Google računa. Družina nastane `odobrena`.

## Posledice

- **Kaj to olajša:** vstop nove družine ne potrebuje lastnika pred prvim
  stikom; gesel ni treba predajati; e-naslov je potrjen brez pošte.
- **Kaj to oteži:**
  - Prvič obstaja javni obrazec, ki ustvarja vrstice v bazi. Zgornja meja
    čakajočih in omejevanje po IP sta pogoj, ne izboljšava.
  - Vsaka pot pod `/admin` mora poznati stanje družine; zato odvisnost
    usmerjevalnika in generiran test, ne preverba po poteh.
  - Prijava z Googlom dobi tretji izid (ni računa → registracija) poleg
    „prijavljen" in „ni povezan".
- **Zavestno izpuščeno:** registracija z geslom, e-pošta in SMTP, lastna
  domena, obvestila lastniku in staršu, potek zahtevkov, samodejna
  odobritev, izbris odobrene družine, Trgovina Play. Vse to so nove zahteve,
  če bodo.

## Viri

- OWASP Forgot Password Cheat Sheet — pravila za žetone v povezavah.
- Google Cloud, *Manage App Audience* — izjema za `openid`/`email`/`profile`.
- Google Play, *app-account deletion requirements* — za poznejšo objavo.
