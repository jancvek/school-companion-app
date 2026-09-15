"""Testi postavitve pred strežnikom (V3-R02).

Pokrivajo tabelo „Test casi — Strežnik" iz `docs/plan/V3-R02.md`.

Caddy, omrežje in objavljena vrata so nastavitev, ne koda: noben test nad
aplikacijo jih ne vidi, napaka v njih pa domači stroj odpre internetu. Testi
zato berejo `docker-compose.yml` in `Caddyfile` neposredno.

Datoteki se bereta kot besedilo in ne kot YAML: PyYAML je v okolju samo
posredno in brez tipov (plan, odločitev 10). Vsak pomočnik zato pade glasno,
kadar vzorca ne najde — tih prazen izid bi test naredil zelen iz napačnega
razloga.
"""

import ipaddress
import re
from pathlib import Path

MAPA_STREZNIKA = Path(__file__).resolve().parent.parent
COMPOSE = MAPA_STREZNIKA / "docker-compose.yml"
CADDYFILE = MAPA_STREZNIKA / "Caddyfile"
OKOLJE_PRIMER = MAPA_STREZNIKA / "okolje.primer"

#: Prava bcrypt zgostitev, ne zgled `'$2a$14$...'` iz `okolje.primer`.
BCRYPT = re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}")


# --- Branje `docker-compose.yml` -------------------------------------------


def _vrstice_compose() -> list[str]:
    """Vrstice brez komentarjev in brez praznih repov."""
    return [
        vrstica.split("#", 1)[0].rstrip()
        for vrstica in COMPOSE.read_text(encoding="utf-8").splitlines()
    ]


def _zamik(vrstica: str) -> int:
    return len(vrstica) - len(vrstica.lstrip())


def _odsek(vrstice: list[str], kljuc: str, zamik: int) -> list[str]:
    """Vrstice pod `kljuc:` na ravni `zamik`, do naslednjega ključa na isti ravni."""
    glava = " " * zamik + kljuc + ":"
    for i, vrstica in enumerate(vrstice):
        if vrstica == glava:
            telo: list[str] = []
            for naslednja in vrstice[i + 1 :]:
                if naslednja.strip() and _zamik(naslednja) <= zamik:
                    break
                telo.append(naslednja)
            return telo
    raise AssertionError(f"V {COMPOSE.name} ni ključa {kljuc!r} z zamikom {zamik}.")


def _servis(ime: str) -> list[str]:
    return _odsek(_odsek(_vrstice_compose(), "services", 0), ime, 2)


def _ima_kljuc(telo: list[str], kljuc: str, zamik: int) -> bool:
    return any(vrstica == " " * zamik + kljuc + ":" for vrstica in telo)


def _seznam(telo: list[str]) -> list[str]:
    """Elementi `- …` seznama, brez narekovajev."""
    return [
        vrstica.strip()[2:].strip().strip('"')
        for vrstica in telo
        if vrstica.strip().startswith("- ")
    ]


def _vrednost(telo: list[str], kljuc: str) -> str:
    for vrstica in telo:
        if vrstica.strip().startswith(kljuc + ":"):
            return vrstica.split(":", 1)[1].strip()
    raise AssertionError(f"Ni vrednosti za {kljuc!r}.")


def _vse_objave() -> list[str]:
    """Vsaka objava vrat v celotni datoteki, pri kateremkoli servisu."""
    vrstice = _vrstice_compose()
    objave: list[str] = []
    for i, vrstica in enumerate(vrstice):
        if vrstica.strip() == "ports:":
            telo = []
            for naslednja in vrstice[i + 1 :]:
                if naslednja.strip() and _zamik(naslednja) <= _zamik(vrstica):
                    break
                telo.append(naslednja)
            objave.extend(_seznam(telo))
    return objave


# --- Branje `Caddyfile` ----------------------------------------------------


def _caddyfile() -> str:
    """Caddyfile brez komentarjev."""
    return "\n".join(
        vrstica.split("#", 1)[0].rstrip()
        for vrstica in CADDYFILE.read_text(encoding="utf-8").splitlines()
    )


def _blok(besedilo: str, glava: str) -> str:
    """Vsebina bloka `glava { … }`; prazna glava je globalni blok na začetku."""
    najdba = re.search(rf"^[ \t]*{re.escape(glava)}[ \t]*\{{[ \t]*$", besedilo, re.MULTILINE)
    if najdba is None:
        raise AssertionError(f"V {CADDYFILE.name} ni bloka {glava!r}.")
    odprt = najdba.start() + najdba.group(0).rindex("{")
    globina = 0
    for i in range(odprt, len(besedilo)):
        if besedilo[i] == "{":
            globina += 1
        elif besedilo[i] == "}":
            globina -= 1
            if globina == 0:
                return besedilo[odprt + 1 : i]
    raise AssertionError(f"Blok {glava!r} ni zaprt.")


def _ukazi(blok: str) -> list[str]:
    return [vrstica.strip() for vrstica in blok.splitlines() if vrstica.strip()]


# --- Compose ---------------------------------------------------------------


class TestObjavljenaVrata:
    def test_caddy_objavi_samo_tcp_443(self) -> None:
        assert _seznam(_odsek(_servis("caddy"), "ports", 4)) == ["443:443"]

    def test_nobena_objava_ni_80_ali_udp(self) -> None:
        # Vrata 80 so Arasova (IIS) in se ne smejo pojaviti nikjer; HTTP/3 je
        # izklopljen, zato tudi UDP ne.
        objave = _vse_objave()
        assert objave, "V datoteki ni nobene objave vrat — vzorec ne drži več."
        for objava in objave:
            assert "/udp" not in objava, objava
            gostitelj, vsebnik = objava.rsplit(":", 2)[-2:]
            assert gostitelj != "80", objava
            assert vsebnik != "80", objava


class TestCaddy:
    def test_slika_je_pripeta_na_razlicico(self) -> None:
        assert re.fullmatch(r"caddy:\d+\.\d+\.\d+-alpine", _vrednost(_servis("caddy"), "image"))

    def test_podatki_caddyja_so_obstojni(self) -> None:
        # Brez obstojnega `/data` vsak zagon prosi za nov certifikat.
        assert "caddy-podatki:/data" in _seznam(_odsek(_servis("caddy"), "volumes", 4))
        assert _ima_kljuc(_odsek(_vrstice_compose(), "volumes", 0), "caddy-podatki", 2)

    def test_caddyfile_je_priklopljen_samo_za_branje(self) -> None:
        assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in _seznam(
            _odsek(_servis("caddy"), "volumes", 4)
        )

    def test_domena_in_geslo_sta_obvezna(self) -> None:
        # `:?` ustavi zagon; `:-` bi Caddyja zagnal brez domene ali z praznim
        # geslom pred `/admin`.
        okolje = _odsek(_servis("caddy"), "environment", 4)
        for ime in ("DOMENA", "ADMIN_UPORABNIK", "ADMIN_ZGOSTITEV"):
            assert _vrednost(okolje, ime).startswith("${" + ime + ":?"), ime


class TestOmrezje:
    def test_caddy_ima_stalen_naslov_v_podomrezju(self) -> None:
        naslov = ipaddress.ip_address(
            _vrednost(_odsek(_odsek(_servis("caddy"), "networks", 4), "spredaj", 6), "ipv4_address")
        )
        spredaj = _odsek(_odsek(_vrstice_compose(), "networks", 0), "spredaj", 2)
        podomrezje = ipaddress.ip_network(_seznam(spredaj)[0].removeprefix("subnet: "))
        assert naslov in podomrezje
        # Prvi naslov je prehod omrežja; tega `api` ne sme zamenjati za Caddyja.
        assert naslov != next(podomrezje.hosts())

    def test_caddy_do_baze_nima_poti(self) -> None:
        caddy = _odsek(_servis("caddy"), "networks", 4)
        assert [v.strip().rstrip(":") for v in caddy if _zamik(v) == 6] == ["spredaj"]
        assert _seznam(_odsek(_servis("api"), "networks", 4)) == ["default", "spredaj"]
        # Brez ključa `networks` je `db` samo v `default`.
        assert not _ima_kljuc(_servis("db"), "networks", 4)

    def test_datoteka_ostane_v_mapi_server(self) -> None:
        # Ime mape je ime projekta Compose in predpona volumnov z bazo in
        # slikami (`server_podatki-baze`, `server_slike`).
        assert COMPOSE.parent.name == "server"


# --- Caddyfile -------------------------------------------------------------


class TestCaddyfile:
    def test_certifikat_samo_prek_tls_alpn(self) -> None:
        besedilo = _caddyfile()
        spletisce = _blok(besedilo, "{$DOMENA}")
        assert _ukazi(_blok(_blok(spletisce, "tls"), "issuer acme")) == ["disable_http_challenge"]
        assert "disable_tlsalpn_challenge" not in besedilo

    def test_brez_http3(self) -> None:
        globalni = _blok(_caddyfile(), "")
        assert _ukazi(_blok(globalni, "servers")) == ["protocols h1 h2"]

    def test_brez_preusmeritve_na_vrata_80(self) -> None:
        assert "auto_https disable_redirects" in _ukazi(_blok(_caddyfile(), ""))

    def test_basic_auth_samo_pod_admin(self) -> None:
        # `/admin*` bi ujel tudi `/administration`; ujemalnik mora biti natanko
        # `/admin` in `/admin/...`.
        besedilo = _caddyfile()
        ukazi = _ukazi(_blok(besedilo, "{$DOMENA}"))
        assert "@admin path /admin /admin/*" in ukazi
        assert besedilo.count("basic_auth") == 1
        assert _blok(besedilo, "basic_auth @admin")

    def test_zgostitev_ni_v_repozitoriju(self) -> None:
        besedilo = _caddyfile()
        assert _ukazi(_blok(besedilo, "basic_auth @admin")) == [
            "{$ADMIN_UPORABNIK} {$ADMIN_ZGOSTITEV}"
        ]
        for datoteka in (CADDYFILE, COMPOSE, OKOLJE_PRIMER):
            assert not BCRYPT.search(datoteka.read_text(encoding="utf-8")), datoteka.name

    def test_cep_je_oznacen_kot_zacasen(self) -> None:
        vrstice = CADDYFILE.read_text(encoding="utf-8").splitlines()
        mesto = next(i for i, v in enumerate(vrstice) if v.strip().startswith("basic_auth"))
        assert any("V3-R03" in v for v in vrstice[max(0, mesto - 6) : mesto])

    def test_promet_gre_na_api(self) -> None:
        assert "reverse_proxy api:8000" in _ukazi(_blok(_caddyfile(), "{$DOMENA}"))
