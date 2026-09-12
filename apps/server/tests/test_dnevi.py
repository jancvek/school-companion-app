"""Testi pregleda slik po obdobju in predmetih (`/admin/days`, V2-R07).

Pokrivajo tabelo „Test casi" iz `docs/plan/V2-R07.md`.

Zapisi nastanejo neposredno v bazi in ne prek `POST /materials`: ta stran bere
stanje, ne poti, po kateri je stanje nastalo — isti razlog kot v
`tests/test_admin.py`.

**Dva razreda testov, ki jih je treba brati različno.** Tisti, ki preizkušajo
pravila o lokalnem dnevu, uporabljajo **zapisane** trenutke in zapisane
pričakovane dneve (`2026-07-01T22:30Z` je lokalno že 2. julij) — ti veljajo ne
glede na to, kdaj zbirka teče. Tisti, ki preizkušajo gumbe *Danes*, *Včeraj* in
*Ta teden*, morajo vedeti, kateri dan je danes, in ga dobijo iz `danes()`; da
`danes()` ni `date.today()` po uri stroja, dokazuje
`test_privzeti_dan_zajame_cel_lokalni_dan` — postavi posnetka ob 00:30 in 23:30
po domačem času, ki v UTC pripadata dvema različnima dnevoma.
"""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.casi import danes, dnevi_od_do, pas
from app.models import STATUS_NOV, Material
from app.routers.dnevi import DNI_V_TEDNU, Obdobje, preberi_obdobje

POT = "/admin/days"

#: Prejem, ki ga privzeto dobi vsak zapis: 4. 9. 2026 ob 08:00 UTC, kar je po
#: domačem času (poletni čas) 10:00.
PREJETO = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
PREJETO_OPIS = "4. 9. 2026 ob 10:00"


def oznaka_dneva(dan: date) -> str:
    """Dan, kot ga stran izpiše v naslovu skupine.

    Oblika je tu zapisana na roko in ne vzeta iz `app.casi`: test, ki bi
    pričakovanje izračunal z isto funkcijo kot izvedba, bi bil zelen tudi ob
    napačni obliki.
    """
    return f"{dan.day}. {dan.month}. {dan.year}"


def sidro(material_id: str) -> str:
    """Povezava na podrobnosti, kot jo izpiše stran.

    Testi vrstnega reda in prisotnosti se sidrajo na **to** in ne na gol
    identifikator: niz „prej" se ujame tudi z besedo „prejel" v glavi strani,
    in tak test je zelen tudi ob napačnem vrstnem redu. Ta past je bila v prvi
    različici teh testov in jo je odkril mutacijski preizkus.
    """
    return f'href="/admin/materials/{material_id}"'


def lokalno(dan: date, ura: int = 10, minuta: int = 0) -> datetime:
    """Trenutek tega **lokalnega** dneva, pretvorjen v UTC.

    Za teste, ki jih zanima dan in ne ura. Kjer je pomembna prav meja med
    dnevoma, testi trenutek zapišejo v UTC in se na to funkcijo ne zanašajo.
    """
    return datetime.combine(dan, time(ura, minuta), tzinfo=pas()).astimezone(UTC)


def zapisi(
    motor: Engine,
    slike: Path,
    material_id: str,
    *,
    subject: str = "MAT",
    taken_at: datetime,
    received_at: datetime = PREJETO,
    vsebina: bytes | None = b"slika",
    arhivirano: datetime | None = None,
) -> None:
    """Ustvari zapis in (privzeto) njegovo datoteko."""
    pot = slike / f"{material_id}.jpg"
    if vsebina is not None:
        pot.write_bytes(vsebina)

    with Session(motor) as seja:
        seja.add(
            Material(
                id=material_id,
                subject=subject,
                taken_at=taken_at,
                image_path=str(pot),
                status=STATUS_NOV,
                received_at=received_at,
                archived_at=arhivirano,
            )
        )
        seja.commit()


class TestBranjeObdobja:
    """Pravila obdobja brez HTTP: čiste funkcije, zapisani dnevi."""

    def test_brez_parametrov_je_danes(self) -> None:
        obdobje = preberi_obdobje(None, None, date(2026, 9, 12))

        assert obdobje == Obdobje(prvi=date(2026, 9, 12), zadnji=date(2026, 9, 12), je_teden=False)

    def test_teden_je_danes_in_sest_dni_pred_njim(self) -> None:
        obdobje = preberi_obdobje(None, "teden", date(2026, 9, 12))

        # Sedem dni, ne osem: kriterij pravi „obseg je navzgor omejen na en
        # teden" (`docs/odlocitve/ADR-023`).
        assert obdobje.prvi == date(2026, 9, 6)
        assert obdobje.zadnji == date(2026, 9, 12)
        assert len(obdobje.dnevi) == DNI_V_TEDNU

    def test_dnevi_obdobja_so_padajoce_in_vsi(self) -> None:
        obdobje = preberi_obdobje(None, "teden", date(2026, 9, 12))

        assert obdobje.dnevi == [date(2026, 9, 12 - zamik) for zamik in range(DNI_V_TEDNU)]

    def test_teden_ne_sledi_izbranemu_dnevu(self) -> None:
        # Sidro je današnji dan; poljuben dan skupaj s tednom ni prezrt, ampak
        # zavrnjen — glej `TestNeveljavenVhod`.
        obdobje = preberi_obdobje(None, "teden", date(2026, 1, 2))

        assert obdobje.zadnji == date(2026, 1, 2)
        assert obdobje.prvi == date(2025, 12, 27)

    def test_izbrani_dan_velja(self) -> None:
        obdobje = preberi_obdobje("2026-03-08", None, date(2026, 9, 12))

        assert obdobje.prvi == obdobje.zadnji == date(2026, 3, 8)
        assert obdobje.je_teden is False


class TestMejeObdobja:
    """Meje so lokalne in polodprte (`ADR-016` B)."""

    def test_poleti_se_dan_zacne_ob_22_utc_prejsnjega_dne(self) -> None:
        od, do = dnevi_od_do(date(2026, 7, 1), date(2026, 7, 1))

        assert od == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)
        assert do == datetime(2026, 7, 1, 22, 0, tzinfo=UTC)

    def test_pozimi_se_dan_zacne_ob_23_utc_prejsnjega_dne(self) -> None:
        od, do = dnevi_od_do(date(2026, 1, 5), date(2026, 1, 5))

        assert od == datetime(2026, 1, 4, 23, 0, tzinfo=UTC)
        assert do == datetime(2026, 1, 5, 23, 0, tzinfo=UTC)

    def test_vec_dni_gre_od_prve_do_zadnje_lokalne_polnoci(self) -> None:
        od, do = dnevi_od_do(date(2026, 7, 1), date(2026, 7, 7))

        assert od == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)
        # Polodprto: zadnji dan je vključen, zato meja pade na polnoč **za**
        # njim. Zaprt interval bi posnetek točno ob polnoči štel dvakrat.
        assert do == datetime(2026, 7, 7, 22, 0, tzinfo=UTC)


class TestIzbraniDan:
    """Kaj stran pokaže za en zapisan dan."""

    def test_pokaze_sliko_izbranega_dne(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "a-1", taken_at=datetime(2026, 9, 8, 6, 5, tzinfo=UTC))

        odgovor = odjemalec.get(POT, params={"dan": "2026-09-08"})

        assert odgovor.status_code == 200
        assert oznaka_dneva(date(2026, 9, 8)) in odgovor.text
        assert sidro("a-1") in odgovor.text

    def test_slike_drugih_dni_se_ne_pokazejo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "a-1", taken_at=datetime(2026, 9, 8, 6, 5, tzinfo=UTC))
        zapisi(motor, slike, "a-2", taken_at=datetime(2026, 9, 9, 6, 5, tzinfo=UTC))

        odgovor = odjemalec.get(POT, params={"dan": "2026-09-08"})

        assert sidro("a-1") in odgovor.text
        assert sidro("a-2") not in odgovor.text

    def test_ob_sliki_stoji_ura_in_klik_pelje_na_podrobnosti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # 06:05 UTC je po domačem času (poletni čas) 08:05.
        zapisi(motor, slike, "a-1", taken_at=datetime(2026, 9, 8, 6, 5, tzinfo=UTC))

        odgovor = odjemalec.get(POT, params={"dan": "2026-09-08"})

        assert sidro("a-1") in odgovor.text
        # Sličic ni; edino, kar teden drži znosen, je lena naložitev.
        assert 'src="/admin/materials/a-1/image"' in odgovor.text
        assert 'loading="lazy"' in odgovor.text

        # Kriterij pravi „**samo** ura posnetka", zato se presoja nad samo
        # ploščico in ne nad celo stranjo: polni čas („8. 9. 2026 ob 08:05")
        # vsebuje uro kot podniz in bi bil nad celo stranjo zelen.
        ploscica = odgovor.text[odgovor.text.index(sidro("a-1")) :]
        ploscica = ploscica[: ploscica.index("</a>")]
        assert "08:05" in ploscica
        assert oznaka_dneva(date(2026, 9, 8)) not in ploscica

    def test_manjkajoca_datoteka_pove_kaj_je_narobe(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(
            motor, slike, "a-1", taken_at=datetime(2026, 9, 8, 6, 5, tzinfo=UTC), vsebina=None
        )

        odgovor = odjemalec.get(POT, params={"dan": "2026-09-08"})

        # Brez tega bi brskalnik narisal ikono pokvarjene slike — kar je videti
        # kot napaka strani in ne kot podatek o manjkajoči datoteki.
        assert "slike na disku ni" in odgovor.text
        assert 'src="/admin/materials/a-1/image"' not in odgovor.text

    def test_arhivirana_slika_se_ne_pokaze(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(
            motor,
            slike,
            "a-1",
            taken_at=datetime(2026, 9, 8, 6, 5, tzinfo=UTC),
            arhivirano=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
        )
        zapisi(motor, slike, "a-2", taken_at=datetime(2026, 9, 8, 7, 0, tzinfo=UTC))

        odgovor = odjemalec.get(POT, params={"dan": "2026-09-08"})

        assert sidro("a-2") in odgovor.text
        assert sidro("a-1") not in odgovor.text

    def test_prazen_dan_je_izpisan_in_ni_napaka(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(POT, params={"dan": "2026-09-08"})

        assert odgovor.status_code == 200
        # Prav odsotnost slik je odgovor na vprašanje, ali je bila snov tisti
        # dan poslikana, zato se dan izpiše in ne izpade.
        assert oznaka_dneva(date(2026, 9, 8)) in odgovor.text
        assert "Tega dne ni nobene slike." in odgovor.text

    def test_meja_dneva_je_lokalna_polnoc(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Poleti je 22:30 UTC po domačem času že 00:30 naslednjega dne.
        # Regresija na `ADR-016` (B): meja v UTC bi sliko pripisala 1. juliju.
        zapisi(motor, slike, "a-1", taken_at=datetime(2026, 7, 1, 22, 30, tzinfo=UTC))

        drugega = odjemalec.get(POT, params={"dan": "2026-07-02"})
        prvega = odjemalec.get(POT, params={"dan": "2026-07-01"})

        assert sidro("a-1") in drugega.text
        assert sidro("a-1") not in prvega.text


class TestVrstniRed:
    """Trije vrstni redi: dnevi, predmeti, slike."""

    def test_predmeti_so_po_urniku_in_ne_po_abecedi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        kdaj = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        for stevilka, koda in enumerate(("GEO", "MAT", "NAR", "TJA")):
            zapisi(motor, slike, f"a-{stevilka}", subject=koda, taken_at=kdaj)

        besedilo = odjemalec.get(POT, params={"dan": "2026-09-08"}).text

        # Abecedno bi bilo GEO, MAT, NAR, TJA. Vrstni red je `PREDMETI`.
        assert besedilo.index("NAR") < besedilo.index("MAT")
        assert besedilo.index("MAT") < besedilo.index("TJA")
        assert besedilo.index("TJA") < besedilo.index("GEO")

    def test_neznana_koda_je_vidna_in_stoji_za_znanimi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        kdaj = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        zapisi(motor, slike, "a-1", subject="MAT", taken_at=kdaj)
        zapisi(motor, slike, "a-2", subject="XYZ", taken_at=kdaj)

        besedilo = odjemalec.get(POT, params={"dan": "2026-09-08"}).text

        # Nikoli molčeč izpust: koda, ki je ni na seznamu desetih, se pokaže
        # pod svojo kodo (odločitev 3 v `docs/plan/V1-R04.md`).
        assert "XYZ" in besedilo
        assert sidro("a-2") in besedilo
        assert besedilo.index("MAT") < besedilo.index("XYZ")
        # Koda je vidna, ni pa podvojena: `oznaka_predmeta` za neznano kodo
        # vrne kodo samo, in naslov „XYZ — XYZ" bi bil videti kot okvara.
        assert "XYZ — XYZ" not in besedilo
        assert "MAT — Matematika" in besedilo

    def test_predmet_brez_slik_tega_dne_se_ne_izpise(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(
            motor, slike, "a-1", subject="MAT", taken_at=datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        )

        besedilo = odjemalec.get(POT, params={"dan": "2026-09-08"}).text

        assert "MAT" in besedilo
        for koda in ("NAR", "TJA", "GEO", "SLJ", "LUM", "ZGO", "TIT", "DKE", "GUM"):
            assert koda not in besedilo

    def test_slike_znotraj_predmeta_so_narascajoce(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "druga-stran", taken_at=datetime(2026, 9, 8, 8, 0, tzinfo=UTC))
        zapisi(motor, slike, "prva-stran", taken_at=datetime(2026, 9, 8, 6, 0, tzinfo=UTC))

        besedilo = odjemalec.get(POT, params={"dan": "2026-09-08"}).text

        # Zaporedni posnetki so strani iste snovi (`ADR-003`), zato prva stran
        # stoji prva — obratno kot na strani predmeta.
        assert besedilo.index(sidro("prva-stran")) < besedilo.index(sidro("druga-stran"))

    def test_dnevi_so_padajoce(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        zdaj = danes()
        zapisi(motor, slike, "starejsa", taken_at=lokalno(zdaj - timedelta(days=2)))
        zapisi(motor, slike, "novejsa", taken_at=lokalno(zdaj))

        besedilo = odjemalec.get(POT, params={"obdobje": "teden"}).text

        assert besedilo.index(sidro("novejsa")) < besedilo.index(sidro("starejsa"))


class TestGumbi:
    """*Danes*, *Včeraj*, *Ta teden* — edini testi, ki vedo, kateri dan je."""

    def test_privzeti_dan_zajame_cel_lokalni_dan(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zdaj = danes()
        # 00:30 in 23:30 po **domačem** času. V UTC pripadata dvema različnima
        # koledarskima dnevoma, zato bi meja v UTC ali `date.today()` po uri
        # stroja enega od njiju izgubila.
        zapisi(motor, slike, "zjutraj", taken_at=lokalno(zdaj, 0, 30))
        zapisi(motor, slike, "zvecer", taken_at=lokalno(zdaj, 23, 30))

        besedilo = odjemalec.get(POT).text

        assert sidro("zjutraj") in besedilo
        assert sidro("zvecer") in besedilo

    def test_privzeto_ne_pokaze_vcerajsnje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zdaj = danes()
        zapisi(motor, slike, "danasnja", taken_at=lokalno(zdaj))
        zapisi(motor, slike, "vcerajsnja", taken_at=lokalno(zdaj - timedelta(days=1)))

        besedilo = odjemalec.get(POT).text

        assert sidro("danasnja") in besedilo
        assert sidro("vcerajsnja") not in besedilo

    def test_vceraj_pelje_na_vcerajsnji_dan(self, odjemalec: TestClient) -> None:
        vceraj = danes() - timedelta(days=1)

        besedilo = odjemalec.get(POT).text

        assert f'href="/admin/days?dan={vceraj.isoformat()}"' in besedilo

    def test_teden_zajame_sedem_dni_in_ne_osem(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zdaj = danes()
        zapisi(motor, slike, "znotraj", taken_at=lokalno(zdaj - timedelta(days=DNI_V_TEDNU - 1)))
        zapisi(motor, slike, "zunaj", taken_at=lokalno(zdaj - timedelta(days=DNI_V_TEDNU)))

        besedilo = odjemalec.get(POT, params={"obdobje": "teden"}).text

        assert sidro("znotraj") in besedilo
        assert sidro("zunaj") not in besedilo

    def test_teden_izpise_vse_dni_tudi_prazne(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zdaj = danes()
        zapisi(motor, slike, "a-1", taken_at=lokalno(zdaj))

        besedilo = odjemalec.get(POT, params={"obdobje": "teden"}).text

        # Vseh sedem dni ima svoj naslov, tudi tisti brez slik: manjkajoč dan
        # je prav podatek, ki ga lastnik išče (`ADR-023`).
        for zamik in range(DNI_V_TEDNU):
            assert oznaka_dneva(zdaj - timedelta(days=zamik)) in besedilo
        assert besedilo.count("Tega dne ni nobene slike.") == DNI_V_TEDNU - 1


class TestGlava:
    """Kdaj je strežnik nazadnje karkoli prejel."""

    def test_pove_kdaj_je_nazadnje_prejel(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "a-1", taken_at=datetime(2026, 9, 8, 6, 0, tzinfo=UTC))

        besedilo = odjemalec.get(POT, params={"dan": "2026-09-08"}).text

        assert f"Strežnik je nazadnje prejel sliko {PREJETO_OPIS}" in besedilo

    def test_steje_tudi_arhivirane(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "a-1", taken_at=datetime(2026, 9, 8, 6, 0, tzinfo=UTC))
        # Arhivirana slika se v seznamu ne pokaže, prejeta pa je bila — in
        # vprašanje je, ali je telefon prenašal, ne ali je slika še v pregledu.
        zapisi(
            motor,
            slike,
            "a-2",
            taken_at=datetime(2026, 9, 8, 7, 0, tzinfo=UTC),
            received_at=datetime(2026, 9, 10, 15, 30, tzinfo=UTC),
            arhivirano=datetime(2026, 9, 11, 8, 0, tzinfo=UTC),
        )

        besedilo = odjemalec.get(POT, params={"dan": "2026-09-08"}).text

        assert "Strežnik je nazadnje prejel sliko 10. 9. 2026 ob 17:30" in besedilo
        assert PREJETO_OPIS not in besedilo

    def test_prazna_baza_pove_da_se_ni_prejel_nicesar(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get(POT).text

        # Ne ničla in ne prazen niz: prazen dan ne sme biti zamenjan za
        # neopravljeno delo, kadar telefon še ni prenesel.
        assert "Strežnik še ni prejel nobene slike." in besedilo


class TestNeveljavenVhod:
    """Neveljaven naslov vrne 400 in ne tihega padca na današnji dan."""

    def _danasnja(self, motor: Engine, slike: Path) -> None:
        zapisi(motor, slike, "danasnja", taken_at=lokalno(danes()))

    def test_nerazberljiva_oblika_datuma(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        self._danasnja(motor, slike)

        odgovor = odjemalec.get(POT, params={"dan": "8.9.2026"})

        assert odgovor.status_code == 400
        assert "Pričakovana oblika je 2026-09-12" in odgovor.text
        # Ključni del kriterija: stran ne sme pokazati današnjih slik in
        # pustiti operaterja v veri, da gleda izbrani dan.
        assert sidro("danasnja") not in odgovor.text

    def test_datum_ki_ga_v_koledarju_ni(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(POT, params={"dan": "2026-13-40"})

        assert odgovor.status_code == 400
        assert "ni v koledarju" in odgovor.text

    def test_kompaktna_oblika_iso_ni_dovolj(self, odjemalec: TestClient) -> None:
        # `date.fromisoformat` bi to od Pythona 3.11 sprejel; stran naslova, ki
        # ga sama nikoli ne sestavi, raje zavrne kot tiho razume po svoje.
        odgovor = odjemalec.get(POT, params={"dan": "20260908"})

        assert odgovor.status_code == 400

    def test_leto_izven_meja(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(POT, params={"dan": "1200-01-01"})

        assert odgovor.status_code == 400
        assert "Leto mora biti med 2000 in 2100" in odgovor.text

    def test_neznano_obdobje(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        self._danasnja(motor, slike)

        odgovor = odjemalec.get(POT, params={"obdobje": "mesec"})

        assert odgovor.status_code == 400
        assert "Izbrati je mogoče dan ali teden" in odgovor.text
        assert sidro("danasnja") not in odgovor.text

    def test_teden_skupaj_z_dnevom(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(POT, params={"obdobje": "teden", "dan": "2026-09-01"})

        # Parameter, ki na obseg ne vpliva, ne sme izgledati, kot da nanj
        # vpliva (`ADR-023`).
        assert odgovor.status_code == 400
        assert "Teden se vedno konča z današnjim dnem" in odgovor.text

    def test_prazen_parameter_je_privzetek_in_ne_napaka(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(POT, params={"dan": "", "obdobje": ""})

        # Prazno polje obrazca ni ročno vtipkana napaka.
        assert odgovor.status_code == 200
        assert oznaka_dneva(danes()) in odgovor.text


class TestDosegljivostInMeje:
    """Stran je dosegljiva z `/admin` in ostaja v mejah zahteve."""

    def test_domaca_stran_pelje_na_pregled_po_dnevih(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin").text

        assert 'href="/admin/days"' in besedilo

    def test_povezava_na_domaci_strani_ne_nosi_kode_predmeta(
        self, odjemalec: TestClient
    ) -> None:
        besedilo = odjemalec.get("/admin").text

        # Sidro je povezava in ne naslov razdelka: „Pregled po dnevih" stoji
        # tudi v komentarju sloga v `osnova.html`, torej pred telesom strani.
        zacetek = besedilo.index('href="/admin/days"')
        razdelek = besedilo[zacetek : besedilo.index("</section>", zacetek)]

        # Razdelek stoji pod seznamom predmetov in brez kod: koda pred
        # seznamom bi podrla test, ki po vrstnem redu pojavitev dokazuje, da so
        # predmeti našteti po urniku in ne po abecedi.
        assert besedilo.index("NAR") < zacetek
        for koda in ("NAR", "MAT", "TJA", "GEO"):
            assert koda not in razdelek

    def test_stran_ne_uporablja_skripte(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(POT)

        # Kriterij V2-R07: brez JavaScripta. `ADR-024` ga pod `/admin`
        # dovoljuje kot nadgradnjo, ta stran pa ga ne uporablja.
        assert "<script" not in odgovor.text

    def test_predloga_ne_vsebuje_skripte(self) -> None:
        from app.routers.admin import MAPA_PREDLOG

        assert "<script" not in (MAPA_PREDLOG / "dnevi.html").read_text(encoding="utf-8")

    def test_izbirnik_dneva_je_obrazec_get(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get(POT).text

        # `GET` zato, ker stran ničesar ne spremeni in mora biti dosegljiva z
        # osvežitvijo in iz zgodovine brskalnika.
        assert 'method="get" action="/admin/days"' in besedilo
        assert 'type="date" name="dan"' in besedilo
        # Skrito polje poskrbi, da iz vmesnika nikoli ne nastane kombinacija
        # „teden in poljuben dan", ki je 400.
        assert 'name="obdobje" value="dan"' in besedilo

    def test_kljuc_pod_admin_ni_zahtevan(self, odjemalec: TestClient) -> None:
        # Meja je Tailscale (`ADR-006`); odjemalec ključa ne pošlje.
        assert odjemalec.get(POT).status_code == 200

    def test_stevila_so_v_dvojini(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        kdaj = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        zapisi(motor, slike, "a-1", taken_at=kdaj)
        zapisi(motor, slike, "a-2", taken_at=kdaj + timedelta(minutes=5))

        besedilo = odjemalec.get(POT, params={"dan": "2026-09-08"}).text

        assert "2 sliki" in besedilo
        assert "2 slik" not in besedilo.replace("2 sliki", "")
