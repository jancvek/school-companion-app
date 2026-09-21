"""Pravila lastnika sistema: kaj je veljaven vnos in česa niti on ne sme.

Modul ne ve za FastAPI in ne za bazo — dobi vrednosti, vrne razlog ali `None`.
Isti razlog kot pri `app/clani.py`, `app/prijava.py` in `app/statistika.py`:
pravila se dajo preizkusiti brez zaganjanja strežnika, usmerjevalnik pa ostane
prenos.

Odločitve so v `docs/odlocitve/ADR-044` (izvedba `V3-R05`), `ADR-025`
(lastnik sistema je ločen od starša, registracija je zaprta) in `ADR-038`
(pravila o članih družine; ta modul jih **ne ponavlja**, ampak jih pusti
`app/clani.py`).

**Kar je skupno s starševo stranjo, ostane v `app/clani.py`.** Prikazno ime,
e-naslov in geslo novega starša preverjajo iste funkcije kot na
`/admin/family`, in kdo koga sme deaktivirati, odloča isto pravilo. Tu je samo
tisto, česar na starševi strani ni: ime družine in dve meji, ki varujeta
lastnika pred samim sabo.
"""

from app.clani import NAJDALJSE_IME

#: Predpona poti lastnika sistema.
#:
#: Živi tu in ne v usmerjevalniku, ker je ne potrebuje samo on: prestreznik
#: napak v `app/routers/admin.py` mora vedeti, katere poti se morajo delati
#: neobstoječe (`je_skrita_pot`). Ena vrednost na enem mestu, sicer se
#: zavrnitev in skrivanje nekoč razideta.
PREDPONA = "/admin/system"

#: Najdaljše ime družine — natanko širina stolpca `families.name`.
#:
#: Meja je v kodi in ne prepuščena bazi, iz istega razloga kot pri članih
#: (`app/clani.py`): testi tečejo nad SQLite, ki dolžine `VARCHAR` ne
#: uveljavlja, na Postgresu pa bi predolg vnos postal `DataError` in angleški
#: „Internal Server Error" sredi slovenske strani.
NAJDALJSE_IME_DRUZINE = NAJDALJSE_IME

SPOROCILO_PRAZNO_IME_DRUZINE = (
    "Ime družine manjka. Vpiši ime, po katerem boš družino prepoznal na seznamu."
)
SPOROCILO_PREDOLGO_IME_DRUZINE = (
    f"Ime družine je predolgo; največ {NAJDALJSE_IME_DRUZINE} znakov."
)

SPOROCILO_SVOJE_DRUZINE = (
    "Svoje družine ne moreš deaktivirati. Na njej stoji račun lastnika sistema, "
    "s katerim odpiraš in urejaš vse ostale."
)

SPOROCILO_ZE_UGASNJENA = "Ta družina je že deaktivirana."
SPOROCILO_ZE_PRIZGANA = "Ta družina je že aktivna."

#: Družino smo našli, stavek pa ni spremenil ničesar.
#:
#: **Varovalo in ne pričakovano stanje:** poti lastnika družino poiščejo, preden
#: jo prižgejo ali ugasnejo, in družine se ne brišejo, zato tega sporočila danes
#: ni mogoče doseči. Stoji, ker `nastavi_aktivnost` vrne `bool` in ker je izid
#: pisanja, ki ga klicatelj ne pogleda, slabši od sporočila, ki se ne pokaže.
#: Dvojček `clani.SPOROCILO_NI_SPREMENJENO`, ki dosegljiv je — tam račun brez
#: poverilnice obstaja.
SPOROCILO_NI_SPREMENJENO = (
    "Dejanja nisem izvedel — ta družina se je medtem spremenila. "
    "Osveži stran in poglej, v kakšnem stanju je."
)

SPOROCILO_NI_DRUZINE = (
    "Te družine ni. Morda je bil naslov napačno prepisan; na seznamu so vse, "
    "ki obstajajo."
)

#: Besedilo, ki ga lastnik pošlje staršu, preden se družina pridruži.
#:
#: `ADR-025` zahteva, da je zasebnostna cena povedana **izrecno** vsakemu
#: staršu, in da je to dogovor med znanci in ne pravni dokument. Stoji kot
#: konstanta in ne kot prosto besedilo v predlogi, ker kriterij 7 zahteva, da
#: besedilo obstaja — in trditev testa naj velja o besedilu, ne o zapisu HTML
#: (`ADR-044` C).
#:
#: Piše se v drugi osebi in brez pravniškega besednjaka: naslovnik je znanec,
#: ne stranka. Pove troje — kam gre slika, zakaj tja in kaj to pomeni.
BESEDILO_ZASEBNOST = (
    "Preden odpreš družino, to povej staršu:\n\n"
    "Slike zvezkov, ki jih otrok posname v aplikaciji, se s telefona prenesejo "
    "na domači strežnik, od tam pa gredo v zunanjo storitev (OpenAI), ki jih "
    "prepiše in iz njih sestavi vprašanja. Brez tega prepisa aplikacija ne zna "
    "narediti ničesar — slovenske pisave noben domači program ne prebere dovolj "
    "dobro. Slike torej ne ostanejo samo doma.\n\n"
    "Kar nastane iz njih — prepis, vprašanja, kvizi in odgovori — ostane na tem "
    "strežniku in ga vidi samo vaša družina. Nihče drug, tudi druge družine na "
    "istem strežniku ne. Aplikacija ni objavljena in ni namenjena širšemu krogu; "
    "če ti to ne ustreza, družine ne odpiram."
)


def je_skrita_pot(pot: str) -> bool:
    """Ali pot sodi pod predpono, ki se mora delati neobstoječa.

    Ujame se na `/admin/system` in na tem, kar mu sledi za poševnico, nikoli na
    `/admin/systematic` — isto ujemanje kot pri `security.je_izvzeta` in
    `admin.je_admin_pot`. Golo `startswith` bi zajelo vsako pot, ki se slučajno
    začne enako, in bi bilo videti pravilno do dneva, ko taka pot nastane.
    """
    return pot == PREDPONA or pot.startswith(f"{PREDPONA}/")


def preveri_ime_druzine(ime: str) -> str | None:
    """Razlog, zakaj ime družine ni veljavno, ali `None`.

    Enoličnosti **ne** preverja: družina ni identiteta za prijavo, zato dve
    družini z istim priimkom nista dvoumnost, ki bi jo bilo treba preprečiti.
    Enoličnost nosi `credentials.identifier` in jo razsodi baza (`ADR-038` E).
    """
    if not ime.strip():
        return SPOROCILO_PRAZNO_IME_DRUZINE
    if len(ime.strip()) > NAJDALJSE_IME_DRUZINE:
        return SPOROCILO_PREDOLGO_IME_DRUZINE
    return None


def zakaj_ne_sme_deaktivirati_druzine(
    *, druzina_id: str, lastnikova_druzina_id: str
) -> str | None:
    """Razlog, zakaj lastnik te družine ne sme ugasniti, ali `None`.

    Eno samo pravilo: **svoje družine ne**. Na njej stoji račun z
    `is_system_owner`, in ugasnjena družina pomeni, da se noben njen član ne
    more prijaviti (`ADR-044` A) — lastnik bi se s tem z enim klikom izklopil
    iz lastnega strežnika, brez poti nazaj skozi vmesnik.

    Isto sklepanje kot `ADR-038` G, le stopnjo višje: dejanje, ki ga vmesnik
    ponuja, mora biti dejanje, ki ga je mogoče preživeti. To ni zaščita pred
    zlonamernostjo — stroj je lastnikov in dostop do baze ima — ampak pred
    zmoto.

    Pravilo varuje **družino klicatelja** in ne „vsake družine, v kateri je
    kakšen lastnik sistema". Zastavica je last osebe, ne družine, in šteti
    lastnike po vseh družinah bi bila poizvedba čez družine za primer, ki ga
    danes ni: `V3-R05` zastavice nikomur ne podeli, zato je lastnik sistema en
    sam in je v tej družini. Če jih bo kdaj več, je to nova zahteva in s tem
    nov pogoj — ne tiha razširitev tega pravila.
    """
    if druzina_id == lastnikova_druzina_id:
        return SPOROCILO_SVOJE_DRUZINE
    return None
