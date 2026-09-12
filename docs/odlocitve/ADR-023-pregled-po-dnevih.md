# ADR-023: Pregled po dnevih je svoja pot pod `/admin`; teden je zadnjih sedem dni

- **Datum:** 2026-09-12
- **Nastalo pri:** V2-R07 (faza 1 — razumevanje)
- **Status:** Sprejeto
- **Stoji na:** `ADR-006` (vsaka nova pot pod `/admin` je javna znotraj
  omrežja in terja svoj ADR), `ADR-011` (arhiv je svoja os), `ADR-016` B
  (meja dneva je lokalna polnoč), `ADR-017` A (brez ostranjevanja in brez
  tihega krajšanja)

## Kontekst

`V2-R07` hoče pogled, ki ga danes ni: vse slike izbranega dne ali tedna, čez
vse predmete, grupirane po predmetu. `ADR-006` zahteva, da vsaka nova pot pod
`/admin` dobi svoj zapis, ker je znotraj omrežja javna in ker je `BIND_ADDRESS`
edina meja pred njo.

Ob zasnovi so se pokazala štiri mesta, kjer zahteva dopušča opazno različne
izvedbe. Tri so bila razčiščena z lastnikom pred izvedbo, četrto je posledica
primerjave z obstoječo stranjo statistike.

## Možnosti

### A — nova pot ali razširitev obstoječe

1. **Datumski filter na `/admin/subjects/{koda}`.** Za: brez nove poti, torej
   brez nove javne površine. Proti: stran predmeta je en predmet čez vso
   zgodovino; vprašanje „kaj je bilo ta teden" je čez **vse** predmete in bi
   zahtevalo izbirnik predmeta z vrednostjo „vsi" — kar je nova stran v
   preobleki stare.
2. **Razširitev vstopa „Kaj smo se danes učili".** Za: tam že obstaja pogled
   čez vse predmete za en dan. Proti: to je vstop v sestavljalnik kviza in ne
   pregled — seznam je urejen po času, nosi kljukice in vodi v objavo.
   Pregled bi mu moral odvzeti prav to, kar ga dela sestavljalnik.
3. **Svoja pot `GET /admin/days`.** Za: pogled je svoj namen (nadzor nad
   tekočim dnem), svoja ureditev (po dnevu, po predmetu) in svoja poizvedba.
   Proti: nova javna pot znotraj omrežja.

### B — kaj pomeni „teden"

1. **Koledarski teden ponedeljek–nedelja.** Za: bližje besedi „teden".
   Proti: v ponedeljek zvečer pokaže en sam dan; pogled je takrat prazen prav
   takrat, ko ga najbolj potrebuješ.
2. **Zadnjih sedem dni, ki se končajo z današnjim.** Za: obseg je vedno enak
   in vedno vsebuje današnji dan. Proti: „teden" ne pomeni koledarskega tedna,
   kar mora biti na strani napisano.

### C — prazni dnevi

1. **Dan brez slik molče izpade.** Za: enako kot prazni predmeti, ki se po
   zahtevi ne izpišejo. Proti: prav prazen dan je odgovor na vprašanje „ali je
   Maša poslikala". Teden s slikami v torek in petek bi izgledal kot teden z
   dvema dnevoma in ne bi bilo videti, da sreda manjka.
2. **Vsi dnevi obdobja se izpišejo, prazni z oznako.** Za: manjkajoč dan je
   viden. Proti: do sedem vrstic več.

### D — neveljaven datum v naslovu

1. **Pade na današnji dan in stran to pove** — tako ravna `?leto=` na
   statistiki (`V2-R04`).
2. **400 z razumljivim sporočilom.**

## Odločitev

**A3 + B2 + C2 + D2.**

**`GET /admin/days`** je nova pot pod `/admin`. Kot vse ostalo pod to predpono
je znotraj omrežja javna in brez ključa (`ADR-006`); to je dopustno, ker
**samo bere** in ne pokaže ničesar, česar ne pokažeta že `/admin/subjects/{koda}`
in `/admin/materials/{id}`. Nobene poti s ključem ta zahteva ne doda in
telefonu ne pokaže ničesar novega — pogled je lastnikov, na telefonu slik po
arhiviranju ni več (`ADR-011`).

Obdobje nosita dva parametra: `?dan=YYYY-MM-DD` (privzeto današnji) in
`?obdobje=dan|teden` (privzeto `dan`).

**„Ta teden" je zadnjih sedem dni, ki se končajo z današnjim** — torej današnji
dan in šest pred njim. Sidro je **današnji dan in ne izbrani**: teden je
pogled na tekoče stanje, ne pot v zgodovino po tednih. Zato je gumb navadna
povezava brez datuma, kombinacija `?obdobje=teden&dan=...` pa ni tiho
prezrta, ampak zavrnjena — parameter, ki v obsegu ne sodeluje, ne sme izgledati,
kot da nanj vpliva.

**Vsi dnevi obdobja se izpišejo, tudi prazni.** To ni v nasprotju z zahtevo,
da se prazni predmeti ne izpišejo: praznih predmetov bi bilo pri tednu
sedemdeset, praznih dni je največ sedem, in prav dan je enota, ki jo lastnik
primerja z urnikom v glavi.

**Neveljaven datum vrne 400.** Tu se ta pot **namenoma razlikuje** od
statistike, kjer nerazberljiv `?leto=` pade na tekoče šolsko leto in stran to
pove. Razlika ni nedoslednost: na statistiki je okno pripomoček nad istimi
podatki, tu pa je datum **celoten pomen strani**. Tih padec na današnji dan bi
pomenil, da lastnik gleda današnje slike in misli, da gleda torkove — in prav
to zahteva izrecno prepoveduje. Isto ravnanje velja za neznano vrednost
`obdobje`.

Grupiranje po lokalnem koledarskem dnevu teče **v Pythonu**, ne v SQL: izraz za
lokalni dan v SQL ni prenosljiv med SQLite (testi) in Postgresom
(produkcija). Poizvedba dobi par UTC trenutkov, kot jih že dobiva
sestavljalnik kvizov (`app/casi.py`).

**„Nazadnje prejeto" v glavi šteje samo slike** — `max(materials.received_at)`
čez vse zapise, tudi arhivirane. Poskusi reševanja kvizov se ne štejejo: glava
stoji nad seznamom slik in mora odgovoriti na „ali je telefon slike že
prenesel", ne na „ali je telefon živ".

## Posledice

- **Kaj to olajša:** vprašanje „ali je Maša danes poslikala snov in kaj" dobi
  en naslov. Prazen dan v tednu je viden kot prazen dan in ne kot odsotnost
  vrstice.
- **Kaj to oteži:**
  - Še ena javna pot znotraj omrežja. `BIND_ADDRESS` ostaja edina meja
    (`ADR-006`).
  - **Teden pomeni prenos vseh slik tedna v izvirni velikosti.** Sličic ni in
    se s to zahtevo ne uvajajo; edino varovalo je `loading="lazy"`, isto kot na
    strani predmeta. Teden je zato zgornja meja obsega in daljšega obdobja ta
    pot ne dobi, dokler ne bo sličic.
  - **Dan, ki je bil arhiviran, za nazaj izgleda kot dan brez dela.** Pogled
    kaže samo nearhivirane slike (`ADR-011`); je nadzor nad tekočim dnem in ne
    zgodovinski zapis. Lastnik to sprejema.
  - Dve različni ravnanji z neveljavnim parametrom pod isto predpono. Zapisano
    zgoraj, da razlika ne bo odkrita kot nedoslednost in „popravljena" v
    napačno smer.
- **Na katere zahteve to odslej vpliva:** nobene obstoječe. Vsaka prihodnja
  zahteva, ki bo hotela daljše obdobje ali arhivirane slike v tem pogledu, se
  mora najprej srečati s sličicami oziroma z `ADR-011`.
