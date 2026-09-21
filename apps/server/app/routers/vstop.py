"""Prijava in odjava — v brskalniku (V3-R03) in na telefonu (V3-R04).

Oboje je tu in ne v dveh usmerjevalnikih, ker je pod obojim ista preverba
(`prijava.preveri_prijavo`), ista tabela `sessions` in isto omejevanje
ugibanja. Razlikuje se prenosnik in oblika odgovora:

| | brskalnik | telefon |
|---|---|---|
| poti | `/admin/login`, `/admin/logout` | `/auth/login`, `/auth/logout` |
| žeton potuje v | piškotku `seja` | glavi `Authorization: Bearer` |
| vsebina | obrazec in HTML | JSON |
| CSRF | da (dvojno oddan piškotek) | **ne** — brez piškotka ga ni treba |
| vloga, ki sme skozi | starš | otrok |

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

from app import google, prijava
from app.db import IdentifikatorZaseden, PrijavaRepository, SejaUporabnika
from app.dependencies import daj_nastavitve, daj_prijavo, daj_repozitorij_prijave
from app.prijava import Izid, Vrata
from app.schemas import OdjavaOpravljena, PrijavaTelefona, ZetonPrijave
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
        vrata=Vrata.ADMIN,
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
) -> Response:
    """Začne prijavo z Googlom. Seje še ni, zato CSRF žeton preveri pot sama.

    Isti dvojno oddani piškotek kot prijavni obrazec (`ADR-035` D): gumb je
    zato obrazec in ne povezava — povezava bi pomenila, da lahko tuja stran
    tok sproži z `GET` in brskalnik odnese h Googlu brez vednosti uporabnice.
    """
    if not nastavitve.google_je_nastavljen:
        return ni_najdeno(predloge, request, google.SPOROCILO_NI_STRANI)

    if not prijava.zetona_se_ujemata(csrf, request.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE)):
        return _stran_prijave(
            predloge, request, cilj=prijava.PRIVZETI_CILJ, sporocilo=SPOROCILO_CSRF, koda=403
        )

    stanje = google.novo_stanje(google.Namen.PRIJAVA)
    odgovor = RedirectResponse(
        google.naslov_privolitve(
            client_id=nastavitve.google_client_id,
            domena=nastavitve.domena,
            stanje=stanje,
        ),
        status_code=303,
    )
    google.postavi_stanje(odgovor, stanje)
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
    # Sejo razrešimo takoj za vezivom in pred vsem ostalim: od nje je odvisno
    # ne le, ali povezovanje sme skozi, ampak tudi **kam** povemo napako.
    seja_zdaj = _seja_zahteve(request, repo)

    if napaka_googla or not koda:
        return _koncaj(
            _povej(seja_zdaj, povezovanje, google.OZNAKA_ZAVRNJENO, predloge, request)
        )

    if not google.povezava_pripada_seji(stanje, seja_zdaj.user_id if seja_zdaj else None):
        return _koncaj(
            _povej(seja_zdaj, povezovanje, google.OZNAKA_STANJE, predloge, request)
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
            _povej(seja_zdaj, povezovanje, google.OZNAKA_NEDOSEGLJIV, predloge, request)
        )

    if povezovanje:
        # Pogoj je postavila `povezava_pripada_seji` zgoraj; brez seje se sem
        # ne pride.
        assert seja_zdaj is not None
        return _koncaj(_povezi(repo, seja_zdaj, racun_googla, predloge, request))
    return _koncaj(_prijavi_z_googlom(repo, racun_googla, request))


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
        return _na_prijavo(oznaka)
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
    repo: PrijavaRepository, racun_googla: google.RacunGoogla, request: Request
) -> Response:
    """Prijavi starša, čigar račun je s tem Googlom **že povezan**.

    **Uporabnika ne ustvari nikoli** (kriterij 3, `ADR-025`): neznan `sub`
    dobi isto sporočilo kot deaktiviran račun in kot ugasnjena družina, ker je
    razlika med njimi podatek o tem, kdo v tej namestitvi obstaja.

    Vrata se preverijo tudi tu. Poverilnica `kind='google'` na otrokovem
    računu po nobeni poti ne more nastati (povezovanje teče pod `/admin`), a
    pravilo sodi tja, **kjer seja nastane**, in ne samo tja, kjer bi jo bilo
    mogoče ustvariti danes — isto sklepanje kot `ADR-036` D.

    Omejevanja ugibanja tu ni in ga ni treba: gesla, ki bi ga kdo ugibal, v
    tem toku ni, `sub` pa ni skrivnost, ampak izid prijave, ki jo je preveril
    Google (`ADR-046`).
    """
    poverilnica = repo.poverilnica_google(racun_googla.sub)

    if (
        poverilnica is None
        or not poverilnica.is_active
        or not poverilnica.family_is_active
        or not prijava.vloga_sodi(poverilnica.role, Vrata.ADMIN)
    ):
        return _na_prijavo(google.OZNAKA_NEPOVEZAN)

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


# --- Telefon (V3-R04) ------------------------------------------------------


@router.post(
    prijava.POT_PRIJAVE_TELEFONA,
    response_model=ZetonPrijave,
    responses={401: {"description": "Poverilnica ni prava"}},
    tags=["telefon"],
)
async def prijavi_telefon(
    request: Request,
    telo: PrijavaTelefona,
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
) -> Response:
    """Preveri poverilnico otroka in vrne žeton za glavo `Authorization`.

    Isto zaporedje kot v brskalniku, brez koraka s CSRF: zamik pred preverbo
    gesla, ne po njej, in zgoščevanje v niti, ker je argon2 sinhronih ~60 ms
    in bi na zanki dogodkov ustavil vse ostale zahteve — tudi prenos slike.

    Zavrnitev je vedno `401`, tudi za starša (`ADR-036` D). Koda ne loči
    primerov; loči jih sporočilo, in to samo tam, kjer je bilo to zavestno
    dovoljeno.
    """
    zamik = prijava.koliko_cakati(repo, telo.identifier, datetime.now(UTC))
    if zamik:
        await asyncio.sleep(zamik)

    izid = await run_in_threadpool(
        prijava.preveri_prijavo,
        repo,
        telo.identifier,
        telo.password,
        vrata=Vrata.TELEFON,
        ip=request.client.host if request.client else None,
        ko=datetime.now(UTC),
    )

    if izid.izid is not Izid.USPEH or izid.poverilnica is None:
        return JSONResponse({"detail": izid.sporocilo}, status_code=401)

    zdaj = datetime.now(UTC)
    zeton = prijava.ustvari_sejo(
        repo,
        izid.poverilnica,
        ko=zdaj,
        oznaka_naprave=request.headers.get("user-agent", "")[:200] or None,
    )
    return JSONResponse(
        ZetonPrijave(
            token=zeton,
            user_id=izid.poverilnica.user_id,
            display_name=izid.poverilnica.display_name,
            expires_at=zdaj + prijava.TRAJANJE_SEJE,
        ).model_dump(mode="json")
    )


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
