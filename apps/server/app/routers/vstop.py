"""Prijava in odjava — v brskalniku (V3-R03) in na telefonu (V3-R04, V6-R01).

Oboje je tu in ne v dveh usmerjevalnikih, ker je pod obojim ista tabela
`sessions` in isto omejevanje ugibanja. Razlikuje se, s čim se kdo izkaže,
prenosnik in oblika odgovora:

| | brskalnik | telefon |
|---|---|---|
| poti | `/admin/login`, `/admin/logout` | `/auth/link`, `/auth/logout` |
| izkaže se z | geslom ali Googlom | povezovalnim žetonom iz QR kode |
| žeton seje potuje v | piškotku `seja` | glavi `Authorization: Bearer` |
| vsebina | obrazec in HTML | JSON |
| CSRF | da (dvojno oddan piškotek) | **ne** — brez piškotka ga ni treba |
| vloga, ki sme skozi | starš | otrok |

`POST /auth/login` od `V6-R01` ni več prijava, ampak škrbina za stari APK
(`docs/odlocitve/ADR-061` D).

Poti brskalnika sta pod `/admin`, ker sta del operaterske strani; poti telefona
sta zunaj nje, ker bi ju `SejaMiddleware` sicer zahteval s piškotkom in CSRF
žetonom (`docs/odlocitve/ADR-036` G).

Nobena od odjav ni izvzeta iz svoje plasti: obe zahtevata veljavno sejo.
Odjava prek `GET` bi pomenila, da te lahko tuja stran s sliko odjavi.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse, Response

from app import google, prijava, registracija, sistem
from app.db import IdentifikatorZaseden, PrijavaRepository, SejaUporabnika
from app.dependencies import daj_nastavitve, daj_prijavo, daj_repozitorij_prijave
from app.prijava import Izid, Vrata
from app.schemas import OdjavaOpravljena, PovezavaTelefona, ZetonPrijave
from app.settings import Settings
from app.strani import daj_predloge, ni_dovoljeno, ni_najdeno

router = APIRouter(tags=["prijava"])

#: Koliko časa velja piškotek v brskalniku. Enako kot seja v bazi — krajši bi
#: pomenil, da se uporabnica odjavi sama od sebe, daljši pa piškotek, ki nima
#: več seje.
PISKOTEK_SEKUND = int(prijava.TRAJANJE_SEJE.total_seconds())

SPOROCILO_CSRF = (
    "Prijavni obrazec je potekel ali ni prišel s te strani. Osveži stran in poskusi znova."
)


def _postavi_piskotek(odgovor: Response, ime: str, vrednost: str, sekund: int) -> None:
    """Piškotek s tremi zastavicami iz kriterija `V3-R03`.

    `secure=True` velja tudi v razvoju: strežnik je od `V3-R02` za Caddyjem in
    govori izključno `https`. Testi zato tečejo na `https://testserver`.
    """
    odgovor.set_cookie(
        ime,
        vrednost,
        max_age=sekund,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _stran_prijave(
    predloge: Jinja2Templates,
    request: Request,
    *,
    cilj: str,
    sporocilo: str | None = None,
    koda: int = 200,
) -> Response:
    """Izriše prijavno stran in postavi CSRF piškotek obrazca.

    Žeton je nov ob vsakem izrisu; stari piškotek se prepiše. Dvojno oddan
    žeton (piškotek + skrito polje) je edina možnost, dokler seje še ni
    (`docs/odlocitve/ADR-035` D). **Isti žeton velja za oba gumba** — geselni
    obrazec in Googlov (V3-R08); dva bi pomenila dva piškotka, od katerih bi
    drugi prvega prepisal.

    Ali je Googlov gumb izrisan, pove `google_na_voljo` iz obdelovalca
    konteksta (`app/strani.py`) in **ne** ta funkcija: obdelovalec ključe, ki
    jih poda pot, prepiše, zato ima vsak ključ enega samega lastnika
    (`docs/02-izkusnje.md`). Ponudba, ki v tej namestitvi ne bi delovala, je
    slabša od odsotnosti (`ADR-046` F).
    """
    zeton = prijava.nov_zeton()
    odgovor = predloge.TemplateResponse(
        request,
        "prijava.html",
        {"cilj": cilj, "sporocilo": sporocilo, "csrf": zeton},
        status_code=koda,
    )
    _postavi_piskotek(odgovor, prijava.PISKOTEK_CSRF_PRIJAVE, zeton, PISKOTEK_SEKUND)
    return odgovor


@router.get(prijava.POT_PRIJAVE)
def stran_prijave(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    # V naslovu je `next`, v kodi `cilj`: ime parametra v Pythonu bi sicer
    # zasenčilo vgrajeno funkcijo `next`.
    cilj: Annotated[str | None, Query(alias="next")] = None,
    napaka: Annotated[str | None, Query()] = None,
) -> Response:
    """Prijavni obrazec. Cilj `next` se sanira že tu, ne šele po prijavi.

    `napaka` je **oznaka**, ne besedilo (V3-R08): izriše se samo, če jo pozna
    `google.SPOROCILA_PRIJAVE`. Neznana oznaka ne pokaže ničesar — sicer bi
    lahko kdorkoli s pripravljeno povezavo narisal poljubno sporočilo na to
    stran, in prav prijavna stran je tista, kjer je tako sporočilo vabilo.
    """
    return _stran_prijave(
        predloge,
        request,
        cilj=prijava.varen_cilj(cilj),
        sporocilo=google.SPOROCILA_PRIJAVE.get(napaka or ""),
    )


@router.post(prijava.POT_PRIJAVE)
async def prijavi(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    identifikator: Annotated[str, Form()] = "",
    geslo: Annotated[str, Form()] = "",
    csrf: Annotated[str, Form()] = "",
    cilj: Annotated[str, Form()] = prijava.PRIVZETI_CILJ,
) -> Response:
    """Preveri poverilnico in ob uspehu postavi sejo.

    Vrstni red korakov ni poljuben: najprej CSRF (zahteva, ki ni prišla s te
    strani, se ne šteje v omejevanje), nato zamik, šele nato geslo. Zamik pred
    preverbo in ne po njej — po njej bi bila razlika v času še vedno merljiva.
    """
    varen = prijava.varen_cilj(cilj)

    if not prijava.zetona_se_ujemata(csrf, request.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE)):
        return _stran_prijave(predloge, request, cilj=varen, sporocilo=SPOROCILO_CSRF, koda=403)

    zdaj = datetime.now(UTC)
    zamik = prijava.koliko_cakati(repo, identifikator, zdaj)
    if zamik:
        await asyncio.sleep(zamik)

    # V nit in ne v zanko dogodkov: argon2 je namenoma počasen (~60 ms) in
    # sinhron. Na zanki bi vsak poskus prijave za toliko časa ustavil **vse**
    # ostale zahteve strežnika, tudi prenos slike s telefona.
    izid = await run_in_threadpool(
        prijava.preveri_prijavo,
        repo,
        identifikator,
        geslo,
        ip=request.client.host if request.client else None,
        ko=datetime.now(UTC),
    )

    if izid.izid is not Izid.USPEH or izid.poverilnica is None:
        return _stran_prijave(predloge, request, cilj=varen, sporocilo=izid.sporocilo, koda=401)

    zeton = prijava.ustvari_sejo(
        repo,
        izid.poverilnica,
        ko=datetime.now(UTC),
        oznaka_naprave=request.headers.get("user-agent", "")[:200] or None,
    )
    odgovor = RedirectResponse(varen, status_code=303)
    _postavi_piskotek(odgovor, prijava.PISKOTEK_SEJE, zeton, PISKOTEK_SEKUND)
    odgovor.delete_cookie(prijava.PISKOTEK_CSRF_PRIJAVE, path="/")
    return odgovor


# --- Google (V3-R08) -------------------------------------------------------
#
# Tu sta **samo** tisti dve poti, ki ju sproži nekdo brez seje: začetek
# prijave in Googlov povratni klic. Povezovanje in odstranitev sta pod
# `/admin` v `app/routers/racun.py`, ker ju sproži prijavljen starš in ju zato
# varuje `SejaMiddleware` brez izjeme (`docs/odlocitve/ADR-046` B).
#
# Obe poti sta zunaj `/admin` in izvzeti iz `ZetonMiddleware` (`app/main.py`).
# Izvzetje iz žetona telefona ne pomeni, da sta odprti: prvo varuje dvojno
# oddan CSRF žeton prijavnega obrazca, drugo pa vezivo stanja (`ADR-046` D).


def _na_prijavo(oznaka: str) -> Response:
    """Neuspel tok pelje na prijavno stran, ki pojasni z **oznako**.

    V naslovu je oznaka in nikoli besedilo (`app/google.py`): prosto besedilo
    bi pomenilo, da lahko kdorkoli s pripravljeno povezavo nariše poljubno
    sporočilo na našo prijavno stran.
    """
    return RedirectResponse(
        f"{prijava.POT_PRIJAVE}?{urlencode({'napaka': oznaka})}", status_code=303
    )


@router.post(google.POT_PRIJAVE, tags=["google"])
def zacni_google_prijavo(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    csrf: Annotated[str, Form()] = "",
    namen: Annotated[str, Form()] = "",
) -> Response:
    """Začne prijavo z Googlom. Seje še ni, zato CSRF žeton preveri pot sama.

    Isti dvojno oddani piškotek kot prijavni obrazec (`ADR-035` D): gumb je
    zato obrazec in ne povezava — povezava bi pomenila, da lahko tuja stran
    tok sproži z `GET` in brskalnik odnese h Googlu brez vednosti uporabnice.

    Isto pot uporablja okno registracije (V6-R02), s poljem `namen`. Polje
    pove **samo**, na kateri strani se pokaže morebitna napaka; kaj se zgodi,
    odloči `sub`, ki ga vrne Google (`ADR-062` H). Zato sme priti iz obrazca:
    kdor ga ponaredi, vidi svojo napako na drugi strani in nič drugega.
    """
    if not nastavitve.google_je_nastavljen:
        return ni_najdeno(predloge, request, google.SPOROCILO_NI_STRANI)

    registrira = namen == google.Namen.REGISTRACIJA.value

    if not prijava.zetona_se_ujemata(csrf, request.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE)):
        if registrira:
            return _okno_registracije(predloge, request, sporocilo=SPOROCILO_CSRF, koda=403)
        return _stran_prijave(
            predloge, request, cilj=prijava.PRIVZETI_CILJ, sporocilo=SPOROCILO_CSRF, koda=403
        )

    stanje = google.novo_stanje(
        google.Namen.REGISTRACIJA if registrira else google.Namen.PRIJAVA
    )
    odgovor = RedirectResponse(
        google.naslov_privolitve(
            client_id=nastavitve.google_client_id,
            domena=nastavitve.domena,
            stanje=stanje,
        ),
        status_code=303,
    )
    google.postavi_stanje(odgovor, stanje)
    # Nov začetek toka zavrže istovetnost prejšnjega (`ADR-062` G): „Drug
    # račun" je prav ta gumb.
    registracija.pobrisi_istovetnost(odgovor)
    return odgovor


@router.get(google.POT_POVRATNA, tags=["google"])
async def google_povratek(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    koda: Annotated[str | None, Query(alias="code")] = None,
    stanje_googla: Annotated[str | None, Query(alias="state")] = None,
    napaka_googla: Annotated[str | None, Query(alias="error")] = None,
) -> Response:
    """Povratek od Googla — za oba tokova (`ADR-046` C).

    Vrstni red korakov ni poljuben in je varnostno jedro te zahteve:

    1. **Vezivo stanja**, preden se karkoli drugega naredi. Povratni klic je
       navaden `GET` iz tujega konteksta; brez veziva bi napadalec pripravil
       svoj Googlov tok in žrtvin brskalnik pripeljal, da ga dokonča — pri
       povezovanju bi se njegov Google račun prilepil na žrtvin.
    2. **Piškotek se pobriše ob vsakem izidu** (`_koncaj`). Enkratna raba je
       del veziva, ne pospravljanje.
    3. Šele nato menjava kode pri Googlu: klic v omrežje se ne zgodi za
       zahtevo, ki ji ne verjamemo.
    4. Pri povezovanju še **ujemanje z dejavno sejo**: tok, začet pod eno sejo
       in vrnjen pod drugo, bi Google račun pripisal napačnemu staršu.

    Seja se tu razreši **ročno**, ker je pot zunaj `/admin` in je nobena plast
    ne poda. To je edina taka pot — prav zato je povezovanje ostalo pod
    `/admin`, kjer ga plast pokrije sama (`ADR-046` B).
    """
    if not nastavitve.google_je_nastavljen:
        return ni_najdeno(predloge, request, google.SPOROCILO_NI_STRANI)

    stanje = google.Stanje.iz_zapisa(request.cookies.get(google.PISKOTEK_STANJA))

    if stanje is None or not google.stanje_se_ujema(stanje, stanje_googla):
        # Dokler ne vemo, čigav je tok, ne moremo vedeti, kam naj napaka pove.
        # Prijavna stran je edini kraj, ki ga ima tudi nekdo brez seje.
        return _koncaj(_na_prijavo(google.OZNAKA_STANJE))

    povezovanje = stanje.namen is google.Namen.POVEZAVA
    registrira = stanje.namen is google.Namen.REGISTRACIJA
    # Sejo razrešimo takoj za vezivom in pred vsem ostalim: od nje je odvisno
    # ne le, ali povezovanje sme skozi, ampak tudi **kam** povemo napako.
    seja_zdaj = _seja_zahteve(request, repo)

    if napaka_googla or not koda:
        return _koncaj(
            _povej(
                seja_zdaj, povezovanje, google.OZNAKA_ZAVRNJENO, predloge, request, registrira
            )
        )

    if not google.povezava_pripada_seji(stanje, seja_zdaj.user_id if seja_zdaj else None):
        return _koncaj(
            _povej(seja_zdaj, povezovanje, google.OZNAKA_STANJE, predloge, request, registrira)
        )

    odjemalec: google.OdjemalecGoogla | None = request.app.state.odjemalec_googla
    if odjemalec is None:  # pragma: no cover - pokrije `google_je_nastavljen`
        return ni_najdeno(predloge, request, google.SPOROCILO_NI_STRANI)

    try:
        # V nit in ne v zanko dogodkov: odjemalec je sinhron in gre v omrežje.
        # Na zanki bi počasen Google ustavil vse ostale zahteve strežnika —
        # isti razlog kot pri argon2 v geselni prijavi.
        racun_googla = await run_in_threadpool(odjemalec.racun, koda)
    except google.NapakaGoogla:
        return _koncaj(
            _povej(
                seja_zdaj, povezovanje, google.OZNAKA_NEDOSEGLJIV, predloge, request, registrira
            )
        )

    if povezovanje:
        # Pogoj je postavila `povezava_pripada_seji` zgoraj; brez seje se sem
        # ne pride.
        assert seja_zdaj is not None
        return _koncaj(_povezi(repo, seja_zdaj, racun_googla, predloge, request))
    return _koncaj(
        _prijavi_z_googlom(
            repo, racun_googla, request, registrira=registrira, ze_prijavljen=seja_zdaj is not None
        )
    )


def _koncaj(odgovor: Response) -> Response:
    """Vsak izid povratnega klica pobriše piškotek stanja (`ADR-046` D)."""
    google.pobrisi_stanje(odgovor)
    return odgovor


def _seja_zahteve(request: Request, repo: PrijavaRepository) -> SejaUporabnika | None:
    """Seja iz piškotka — ročno, ker je ta pot zunaj obeh plasti.

    Vloga se preveri enako kot v `SejaMiddleware`: otrokov žeton, prilepljen v
    piškotek `seja`, tu ne sme veljati nič bolj kot pod `/admin`
    (`prijava.vloga_sodi`).
    """
    seja = prijava.seja_za_zeton(
        repo, request.cookies.get(prijava.PISKOTEK_SEJE), datetime.now(UTC)
    )
    if seja is None or not prijava.vloga_sodi(seja.role, Vrata.ADMIN):
        return None
    return seja


def _povej(
    seja: SejaUporabnika | None,
    povezovanje: bool,
    oznaka: str,
    predloge: Jinja2Templates,
    request: Request,
    registrira: bool = False,
) -> Response:
    """Napaka pove tam, kjer jo bo bralec videl, in tako, kot se ga tiče.

    Dve vprašanji in dva odgovora, ki se ne ujemata:

    - **Kam** odloči seja. Kdor je prijavljen, dobi stran s pojasnilom;
      preusmeritev na prijavo bi mu povedala, da je bil odjavljen, česar ni
      bil. Kdor seje nima — ker se šele prijavlja ali ker mu je med Googlovim
      zaslonom potekla — je nima kje prebrati drugje kot na prijavni strani.
    - **Kaj** odloči tok. Staršu sredi povezovanja nasvet „prijavi se z
      geslom" ne pove ničesar, ker prijavljen je; napaka se tiče povezovanja
      in ne prijave (`google.SPOROCILA_POVEZAVE`).

    Prijavna stran pozna samo prijavni slovar, in to je prav: kdor je tam,
    seje nima, zato je „prijavi se z geslom" zanj spet pravi nasvet.
    """
    if seja is None:
        # Kdor je tok začel v oknu registracije, napako prebere tam (V6-R02).
        return _na_registracijo(oznaka) if registrira else _na_prijavo(oznaka)
    slovar = google.SPOROCILA_POVEZAVE if povezovanje else google.SPOROCILA_PRIJAVE
    return _ni_povezano(predloge, request, slovar[oznaka])


def _ni_povezano(predloge: Jinja2Templates, request: Request, sporocilo: str) -> Response:
    """409 s pojasnilom: povezave nismo naredili in povemo, zakaj.

    Ni preusmeritev z oznako v naslovu, kot uspeh: razlogov, zakaj povezave ni,
    je več in vsak bi rabil svojo oznako — tabela oznak bi bila prepis
    sporočil, ki v `app/google.py` že so.
    """
    return ni_dovoljeno(predloge, request, sporocilo)


def _povezi(
    repo: PrijavaRepository,
    seja: SejaUporabnika,
    racun_googla: google.RacunGoogla,
    predloge: Jinja2Templates,
    request: Request,
) -> Response:
    """Poveže Google račun s **prijavljenim** starševim računom.

    Uporabnika ne ustvari in družine ne ustvari (kriterij 3): `user_id` pride
    iz seje, ki je bila razrešena pred tem klicem, in nobena druga pot do
    `povezi_google` ne obstaja.
    """
    zavrnitev = google.zakaj_ne_sme_povezati(
        racun_googla, ze_povezan=repo.nacini_prijave(seja.user_id).google_povezan
    )
    if zavrnitev is not None:
        return _ni_povezano(predloge, request, zavrnitev)

    try:
        repo.povezi_google(
            user_id=seja.user_id,
            sub=racun_googla.sub,
            email=racun_googla.email,
            ko=datetime.now(UTC),
        )
    except IdentifikatorZaseden:
        # Ta `sub` je že pri nekom — pri tem staršu samem, če je gumb kliknil
        # dvakrat, ali pri kom drugem. Sporočilo je eno in primerov ne loči:
        # razlika bi povedala, ali tuj račun s tem Googlom obstaja.
        return _ni_povezano(predloge, request, google.SPOROCILO_ZASEDEN)

    return RedirectResponse(
        f"{google.POT_RACUNA}?izid={google.IZID_POVEZANO}", status_code=303
    )


def _prijavi_z_googlom(
    repo: PrijavaRepository,
    racun_googla: google.RacunGoogla,
    request: Request,
    *,
    registrira: bool = False,
    ze_prijavljen: bool = False,
) -> Response:
    """Prijavi starša, čigar račun je s tem Googlom **že povezan**; neznan
    Google račun pelje na obrazec registracije.

    **Uporabnika ne ustvari nikoli** — tudi od `V6-R02` ne. Za neznan `sub`
    postavi podpisan piškotek z istovetnostjo in pelje na obrazec; družino,
    starša in poverilnico ustvari šele oddan obrazec (`ADR-057` A,
    `registriraj`). Izid odloči `sub` in ne to, kateri gumb je tok začel
    (`ADR-062` H): znan `sub` se prijavi tudi iz okna registracije.

    Deaktiviran račun in ugasnjena družina dasta isto oznako; razlika med
    njima ni podatek za tistega, ki se prijavlja.

    Vrata se preverijo tudi tu. Poverilnica `kind='google'` na otrokovem
    računu po nobeni poti ne more nastati (povezovanje teče pod `/admin`), a
    pravilo sodi tja, **kjer seja nastane**, in ne samo tja, kjer bi jo bilo
    mogoče ustvariti danes — isto sklepanje kot `ADR-036` D.

    Omejevanja ugibanja tu ni in ga ni treba: gesla, ki bi ga kdo ugibal, v
    tem toku ni, `sub` pa ni skrivnost, ampak izid prijave, ki jo je preveril
    Google (`ADR-046`).
    """
    poverilnica = repo.poverilnica_google(racun_googla.sub)

    if poverilnica is None:
        if ze_prijavljen:
            # Kdor je že prijavljen, se ne registrira: obrazec bi mu ustvaril
            # drugo družino in zamenjal sejo. Izid je tak kot pred `V6-R02`.
            return _na_prijavo(google.OZNAKA_NEPOVEZAN)
        return _zacni_registracijo(repo, racun_googla, request)

    if (
        not poverilnica.is_active
        or not poverilnica.family_is_active
        or not prijava.vloga_sodi(poverilnica.role, Vrata.ADMIN)
    ):
        oznaka = google.OZNAKA_NEPOVEZAN
        return _na_registracijo(oznaka) if registrira else _na_prijavo(oznaka)

    zdaj = datetime.now(UTC)
    repo.osvezi_oznako_google(poverilnica.credential_id, racun_googla.email, zdaj)
    zeton = prijava.ustvari_sejo(
        repo,
        poverilnica,
        ko=zdaj,
        oznaka_naprave=request.headers.get("user-agent", "")[:200] or None,
    )
    odgovor = RedirectResponse(prijava.PRIVZETI_CILJ, status_code=303)
    _postavi_piskotek(odgovor, prijava.PISKOTEK_SEJE, zeton, PISKOTEK_SEKUND)
    odgovor.delete_cookie(prijava.PISKOTEK_CSRF_PRIJAVE, path="/")
    return odgovor


# --- Registracija (V6-R02) --------------------------------------------------
#
# Okno registracije je pod `/admin` in izvzeto iz seje kot prijavna stran
# (`docs/odlocitve/ADR-062` I): `SejaMiddleware` zanj ne preverja ne seje ne
# CSRF, zato `POST` žeton preveri sam, z istim dvojno oddanim piškotkom.
#
# Trije koraki in kdo kaj ustvari (`ADR-057` A):
#
# 1. gumb „Nadaljuj z Googlom" → `POST /auth/google/login` z `namen`;
# 2. povratni klic za neznan `sub` → podpisan piškotek in obrazec — **v bazi
#    še ni ničesar**;
# 3. oddan obrazec → družina `pending`, starš, poverilnica `google` in seja.


def _na_registracijo(oznaka: str) -> Response:
    """Neuspel tok pelje v okno registracije, ki pojasni z **oznako**."""
    return RedirectResponse(
        f"{registracija.POT}?{urlencode({'napaka': oznaka})}", status_code=303
    )


def _zacni_registracijo(
    repo: PrijavaRepository, racun_googla: google.RacunGoogla, request: Request
) -> Response:
    """Neznan Google račun: preveri, ali se sme registrirati, in ga pelje na obrazec.

    **Ne zapiše ničesar.** Istovetnost gre v piškotek, podpisan s ključem tega
    zagona strežnika (`ADR-062` G); brez podpisa bi si kdorkoli registriral
    tuj `sub`.
    """
    email = racun_googla.email
    zavrnitev = registracija.zakaj_ne_sme_zaceti(
        email=email,
        email_verified=racun_googla.email_verified,
        enaslov_ima_geslo=bool(email)
        and repo.enaslov_ima_geslo(prijava.normaliziraj_identifikator(email or "")),
    )
    if zavrnitev is not None or not email:
        return _na_registracijo(zavrnitev or registracija.OZNAKA_NEPOTRJEN)

    odgovor = RedirectResponse(registracija.POT, status_code=303)
    registracija.postavi_istovetnost(
        odgovor,
        registracija.zapisi_istovetnost(
            registracija.Istovetnost(sub=racun_googla.sub, email=email, name=racun_googla.name),
            request.app.state.kljuc_registracije,
            datetime.now(UTC),
        ),
    )
    return odgovor


def _istovetnost(request: Request) -> registracija.Istovetnost | None:
    """Istovetnost iz podpisanega piškotka te zahteve, ali `None`."""
    return registracija.preberi_istovetnost(
        request.cookies.get(registracija.PISKOTEK),
        request.app.state.kljuc_registracije,
        datetime.now(UTC),
    )


def _je_prek_meje(repo: PrijavaRepository, zdaj: datetime) -> bool:
    """Ali je javni obrazec ta trenutek zaprt (`ADR-062` F)."""
    return registracija.je_prek_meje(
        cakajocih=repo.stevilo_cakajocih(),
        v_oknu=repo.neuspelih_poskusov(
            registracija.OZNAKA_POSKUSOV, zdaj - registracija.OKNO_REGISTRACIJ
        ),
    )


def _okno_registracije(
    predloge: Jinja2Templates,
    request: Request,
    *,
    istovetnost: registracija.Istovetnost | None = None,
    sporocilo: str | None = None,
    opozorilo: str | None = None,
    vnos: dict[str, str] | None = None,
    koda: int = 200,
) -> Response:
    """Izriše okno registracije: začetek ali, z istovetnostjo, obrazec.

    CSRF piškotek je isti kot pri prijavni strani in se postavi ob vsakem
    izrisu (`ADR-035` D).
    """
    zeton = prijava.nov_zeton()
    odgovor = predloge.TemplateResponse(
        request,
        "registracija.html",
        {
            "csrf": zeton,
            "istovetnost": istovetnost,
            "sporocilo": sporocilo,
            "opozorilo": opozorilo,
            "vnos": vnos
            or {
                "ime_druzine": "",
                "ime": istovetnost.name if istovetnost is not None else "",
            },
            "besedilo_zasebnost": sistem.BESEDILO_ZASEBNOST_JAVNO,
            "namen_registracija": google.Namen.REGISTRACIJA.value,
            "pot_prijave": prijava.POT_PRIJAVE,
            "pot_googla": google.POT_PRIJAVE,
            "pot_registracije": registracija.POT,
        },
        status_code=koda,
    )
    _postavi_piskotek(odgovor, prijava.PISKOTEK_CSRF_PRIJAVE, zeton, PISKOTEK_SEKUND)
    return odgovor


@router.get(registracija.POT, tags=["registracija"])
def stran_registracije(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    napaka: Annotated[str | None, Query()] = None,
) -> Response:
    """Okno registracije: začetek (posnetek 02) ali obrazec (04, 06).

    Kdor je že prijavljen, tu nima kaj početi in gre na `/admin` — od tam ga
    zapora, če je treba, pelje na „Moj račun".

    Registracija je samo z Googlom (`ADR-057` A); namestitev brez Googla te
    strani nima (`ADR-046` F).
    """
    if not nastavitve.google_je_nastavljen:
        return ni_najdeno(predloge, request, google.SPOROCILO_NI_STRANI)
    if _seja_zahteve(request, repo) is not None:
        return RedirectResponse(prijava.PRIVZETI_CILJ, status_code=303)

    # Oznaka in nikoli besedilo; neznana ne pokaže ničesar (`app/google.py`).
    sporocilo = registracija.SPOROCILA.get(napaka or "") or google.SPOROCILA_PRIJAVE.get(
        napaka or ""
    )
    istovetnost = None if sporocilo else _istovetnost(request)
    opozorilo = None
    if istovetnost is not None and _je_prek_meje(repo, datetime.now(UTC)):
        opozorilo = registracija.SPOROCILO_PREVEC
    return _okno_registracije(
        predloge, request, istovetnost=istovetnost, sporocilo=sporocilo, opozorilo=opozorilo
    )


@router.post(registracija.POT, tags=["registracija"])
def registriraj(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    csrf: Annotated[str, Form()] = "",
    ime_druzine: Annotated[str, Form()] = "",
    ime: Annotated[str, Form()] = "",
    soglasje: Annotated[str, Form()] = "",
) -> Response:
    """Oddan obrazec: **edino mesto, kjer registracija kaj ustvari**.

    Vrstni red: CSRF, istovetnost iz podpisanega piškotka, vnos, meji, šele
    nato zapis. `sub` in e-naslov prideta **izključno iz piškotka** — obrazec
    ju ne nosi, zato ju ni mogoče zamenjati v telesu zahteve.

    E-naslov se proti geselnim poverilnicam preveri še enkrat: med povratnim
    klicem in oddajo je lahko nastal račun z geslom na istem naslovu.
    """
    if not nastavitve.google_je_nastavljen:
        return ni_najdeno(predloge, request, google.SPOROCILO_NI_STRANI)

    if not prijava.zetona_se_ujemata(csrf, request.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE)):
        return _okno_registracije(predloge, request, sporocilo=SPOROCILO_CSRF, koda=403)

    if _seja_zahteve(request, repo) is not None:
        # Prijavljen starš se ne registrira še enkrat — isto kot `GET`.
        return _brez_istovetnosti(RedirectResponse(prijava.PRIVZETI_CILJ, status_code=303))

    istovetnost = _istovetnost(request)
    if istovetnost is None:
        return _brez_istovetnosti(_na_registracijo(registracija.OZNAKA_POTEKLO))

    vnos = {"ime_druzine": ime_druzine, "ime": ime}
    zdaj = datetime.now(UTC)

    if repo.enaslov_ima_geslo(prijava.normaliziraj_identifikator(istovetnost.email)):
        return _brez_istovetnosti(_na_registracijo(registracija.OZNAKA_GESLO))

    napaka = registracija.preveri_obrazec(
        ime_druzine=ime_druzine, ime=ime, soglasje=bool(soglasje)
    )
    if napaka is not None:
        return _okno_registracije(
            predloge, request, istovetnost=istovetnost, sporocilo=napaka, vnos=vnos, koda=400
        )

    if _je_prek_meje(repo, zdaj):
        return _okno_registracije(
            predloge,
            request,
            istovetnost=istovetnost,
            opozorilo=registracija.SPOROCILO_PREVEC,
            vnos=vnos,
            koda=429,
        )

    try:
        poverilnica = repo.registriraj(
            ime_druzine=ime_druzine.strip(),
            prikazno_ime=ime.strip(),
            sub=istovetnost.sub,
            email=istovetnost.email,
            oznaka_poskusa=registracija.OZNAKA_POSKUSOV,
            ip_address=request.client.host if request.client else None,
            ko=zdaj,
        )
    except IdentifikatorZaseden:
        # Ta `sub` je medtem že registriran — dvojna oddaja ali drugo okno.
        # Druga družina ne nastane; starš se prijavi z istim Googlom.
        return _brez_istovetnosti(_na_registracijo(registracija.OZNAKA_ZE_REGISTRIRAN))

    zeton = prijava.ustvari_sejo(
        repo,
        poverilnica,
        ko=zdaj,
        oznaka_naprave=request.headers.get("user-agent", "")[:200] or None,
    )
    odgovor = _brez_istovetnosti(RedirectResponse(registracija.POT_RACUNA, status_code=303))
    _postavi_piskotek(odgovor, prijava.PISKOTEK_SEJE, zeton, PISKOTEK_SEKUND)
    odgovor.delete_cookie(prijava.PISKOTEK_CSRF_PRIJAVE, path="/")
    return odgovor


def _brez_istovetnosti(odgovor: Response) -> Response:
    """Odgovor, ki piškotek z istovetnostjo pobriše — enkratna raba (`ADR-062` G)."""
    registracija.pobrisi_istovetnost(odgovor)
    return odgovor


@router.post(prijava.POT_ODJAVE)
def odjavi(
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Izbriše sejo te naprave. Seje na drugih napravah ostanejo."""
    repo.izbrisi_sejo(seja.session_id)
    odgovor = RedirectResponse(prijava.POT_PRIJAVE, status_code=303)
    odgovor.delete_cookie(prijava.PISKOTEK_SEJE, path="/")
    return odgovor


# --- Telefon (V3-R04, V6-R01) ----------------------------------------------


@router.post(
    prijava.POT_POVEZAVE_TELEFONA,
    response_model=ZetonPrijave,
    responses={401: {"description": "Koda ne velja"}},
    tags=["telefon"],
)
async def povezi_telefon(
    request: Request,
    telo: PovezavaTelefona,
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
) -> Response:
    """Unovči povezovalni žeton iz QR kode in vrne žeton seje (V6-R01).

    Odgovor ima isto obliko, kot jo je imela prijava z geslom: aplikacija iz
    njega dobi žeton, lastnika lokalnih zapisov in ime (`ADR-036` B).

    Zamik je **pred** preverbo, kot pri prijavi, in šteje neuspehe vse
    namestitve (`ADR-061` E). Zavrnitev je vedno `401` z enim besedilom, ne
    glede na to, zakaj žeton ne velja (`ADR-061` F).

    Unovčenje teče v niti: baza je sinhrona in zahteva ne sme ustaviti zanke
    dogodkov — isti razlog kot pri argon2 v geselni prijavi.
    """
    zamik = prijava.koliko_cakati_na_povezavo(repo, datetime.now(UTC))
    if zamik:
        await asyncio.sleep(zamik)

    zdaj = datetime.now(UTC)
    izid = await run_in_threadpool(
        prijava.unovci_povezavo,
        repo,
        telo.token,
        ip=request.client.host if request.client else None,
        ko=zdaj,
        oznaka_naprave=request.headers.get("user-agent", "")[:200] or None,
    )
    if izid is None:
        return JSONResponse({"detail": prijava.SPOROCILO_KODA_NE_VELJA}, status_code=401)

    zeton, otrok = izid
    return JSONResponse(
        ZetonPrijave(
            token=zeton,
            user_id=otrok.user_id,
            display_name=otrok.display_name,
            expires_at=zdaj + prijava.TRAJANJE_SEJE,
        ).model_dump(mode="json")
    )


@router.post(
    prijava.POT_PRIJAVE_TELEFONA,
    responses={401: {"description": "Prijave z geslom ni več"}},
    tags=["telefon"],
)
def prijava_z_geslom_ni_vec() -> Response:
    """Škrbina za stari APK: vedno `401` s slovenskim sporočilom (`ADR-061` D).

    Otrok gesla nima več (`ADR-058` F). Pot ostane, ker stari APK besedilo
    zavrnitve izpiše dobesedno; brez nje bi otrok videl „Not Found".

    **Telesa ne bere in baze ne odpre**: karkoli pride, je odgovor isti, zato
    tu ni ne omejevanja ne zapisa v `login_attempts`. Odstranitev je svoja
    zahteva, ko starega APK ni več na nobenem telefonu.
    """
    return JSONResponse({"detail": prijava.SPOROCILO_GESLA_NI_VEC}, status_code=401)


@router.post(prijava.POT_ODJAVE_TELEFONA, response_model=OdjavaOpravljena, tags=["telefon"])
def odjavi_telefon(
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> OdjavaOpravljena:
    """Izbriše sejo te naprave. Lokalnih slik na telefonu se ne dotakne.

    Pot **ni** izvzeta iz `ZetonMiddleware`: brez veljavnega žetona ni seje,
    ki bi jo bilo mogoče izbrisati. Telefon zato ob `401` svoj žeton preprosto
    zavrže — odjava je najprej lokalna (`ADR-036` G).
    """
    repo.izbrisi_sejo(seja.session_id)
    return OdjavaOpravljena()
