"""Sestavljanje besedila s prepisi izbranih slik (V3-R11).

Testi enot nad `app/prepisi.py`: brez baze, brez odjemalca in brez izrisa.
Prav to je razlog, da modul obstaja — `docs/odlocitve/ADR-048` F zahteva, da
je sestavljanje ločeno od predloge in ima svoje teste, ker ga bo morda
uporabil tudi generator delovnih listov (`V4-R04`).

Stran, ki to besedilo pokaže, je preizkušena v `test_admin.py`; tesnjenje
med družinami v `test_tesnjenje.py`.
"""

from datetime import UTC, datetime

from app.casi import cas_z_mesecem
from app.prepisi import Prepisi, SnovZaPrepis, izbrane, sestavi


def snov(
    material_id: str = "a1",
    koda: str = "MAT",
    *,
    taken_at: str = "2026-09-12T08:32:00+00:00",
    otrok: str | None = None,
    prepis: str | None = "Delci snovi se gibljejo.",
) -> SnovZaPrepis:
    """Ena snov za sestavljanje. Privzeti čas je 10:32 po domačem pasu."""
    return SnovZaPrepis(
        id=material_id,
        koda=koda,
        taken_at=datetime.fromisoformat(taken_at),
        otrok=otrok,
        prepis=prepis,
    )


class TestCasZMesecem:
    """Oblika časa v glavi (`docs/odlocitve/ADR-048` D).

    Svoj razred, ker je od te oblike odvisno besedilo, ki ga lastnik lepi
    drugam: `12. 9. 2026` je zunaj admina dvoumen, `12. september 2026` ni.
    """

    def test_ime_meseca_in_ura_v_domacem_pasu(self) -> None:
        # Vhod je UTC; poleti je domači pas dve uri naprej.
        trenutek = datetime(2026, 9, 12, 8, 32, tzinfo=UTC)

        assert cas_z_mesecem(trenutek) == "12. september 2026, 10:32"

    def test_dan_in_ura_brez_vodilne_nicle_oziroma_z_njo(self) -> None:
        # Dan brez vodilne ničle (`5.`, ne `05.`), ura z njo (`08:05`) — tako
        # se v slovenščini pišeta datum in ura.
        trenutek = datetime(2026, 1, 5, 7, 5, tzinfo=UTC)

        assert cas_z_mesecem(trenutek) == "5. januar 2026, 08:05"

    def test_zimski_cas_ni_poletni(self) -> None:
        # Pas je imenski in ne odmik: januarja je +1, septembra +2. Zamrznjen
        # odmik bi ta test podrl.
        assert cas_z_mesecem(datetime(2026, 1, 5, 7, 5, tzinfo=UTC)).endswith("08:05")
        assert cas_z_mesecem(datetime(2026, 7, 5, 7, 5, tzinfo=UTC)).endswith("09:05")


class TestGlava:
    """Glava ene snovi."""

    def test_koda_datum_in_ura(self) -> None:
        izid = sestavi([snov()])

        assert izid.besedilo.startswith("## MAT — 12. september 2026, 10:32")

    def test_ime_otroka_je_v_glavi_kadar_ga_snov_ima(self) -> None:
        izid = sestavi([snov(otrok="Ana")])

        assert izid.besedilo.startswith("## MAT — 12. september 2026, 10:32 · Ana")

    def test_druzina_z_enim_otrokom_imena_nima(self) -> None:
        # `imena_otrok` je pri enem otroku prazna (`ADR-039` F), zato je
        # `otrok=None` in ločila „ ·" v glavi ne sme biti.
        izid = sestavi([snov(otrok=None)])

        assert "·" not in izid.besedilo

    def test_prepis_stoji_pod_glavo(self) -> None:
        izid = sestavi([snov(prepis="Delci snovi se gibljejo.")])

        assert izid.besedilo == (
            "## MAT — 12. september 2026, 10:32\n\nDelci snovi se gibljejo.\n"
        )


class TestSnovBrezPrepisa:
    """Slika brez prepisa prispeva samo glavo (`ADR-048` E).

    Zavestno drugače kot pri izbirniku kvizov, kjer neizbirna snov ostane brez
    kljukice: tu je glava sled, da je bila snov tisti dan, in ta se ne sme
    izgubiti.
    """

    def test_prepisa_ni(self) -> None:
        izid = sestavi([snov(prepis=None)])

        assert izid.besedilo == "## MAT — 12. september 2026, 10:32\n"

    def test_prepis_je_prazen_niz(self) -> None:
        assert sestavi([snov(prepis="")]).besedilo == (
            "## MAT — 12. september 2026, 10:32\n"
        )

    def test_prepis_je_iz_samih_presledkov(self) -> None:
        # V polju bi bil videti kot izgubljeno besedilo, ne kot prazen prepis.
        assert sestavi([snov(prepis="   \n\t \n")]).besedilo == (
            "## MAT — 12. september 2026, 10:32\n"
        )

    def test_steje_v_stevec_slik(self) -> None:
        # Kriterij: slika brez prepisa ni posebej označena. Tudi v števcu ne.
        assert sestavi([snov(prepis=None), snov("a2", prepis="Nekaj.")]).slik == 2

    def test_med_glavo_brez_prepisa_in_naslednjo_je_prazna_vrstica(self) -> None:
        izid = sestavi([snov("a1", prepis=None), snov("a2", prepis="Nekaj.")])

        assert izid.besedilo == (
            "## MAT — 12. september 2026, 10:32\n"
            "\n"
            "## MAT — 12. september 2026, 10:32\n"
            "\n"
            "Nekaj.\n"
        )


class TestStevca:
    """Števca sta del izida in ne izračun v predlogi.

    Obljuba kriterija je „število slik in znakov **tega** besedila"; dve
    ločeni poti do istega števila bi se nekoč razšli.
    """

    def test_znakov_je_dolzina_besedila(self) -> None:
        izid = sestavi([snov(), snov("a2", prepis="Drugo.")])

        assert izid.znakov == len(izid.besedilo)

    def test_slik_je_stevilo_snovi(self) -> None:
        assert sestavi([snov("a1"), snov("a2"), snov("a3")]).slik == 3

    def test_prazen_izbor_da_prazno_besedilo_in_niclo(self) -> None:
        # In ne besedila z eno samo novo vrstico: stran polja takrat ne izriše,
        # števec znakov pa mora biti 0.
        assert sestavi([]) == Prepisi(besedilo="", slik=0, znakov=0)

    def test_besedilo_se_ne_reze(self) -> None:
        # `ADR-048` A: praga ni, strežnik ne reže in ne opozarja.
        dolg = "z" * 200_000
        izid = sestavi([snov(prepis=dolg)])

        assert dolg in izid.besedilo
        assert izid.znakov > 200_000


class TestIzbrane:
    """Presejanje in vrstni red (`ADR-048` D in F)."""

    def test_vrstni_red_je_od_najstarejse(self) -> None:
        # Stran predmeta kaže najnovejše prve; besedilo se bere obratno, kot
        # je snov nastajala.
        nabor = [
            snov("novejsa", taken_at="2026-09-12T08:00:00+00:00"),
            snov("starejsa", taken_at="2026-09-04T08:00:00+00:00"),
        ]

        assert [x.id for x in izbrane(nabor, ["novejsa", "starejsa"])] == [
            "starejsa",
            "novejsa",
        ]

    def test_ob_enakem_casu_odloci_id(self) -> None:
        # Brez drugega ključa bi dva posnetka iz iste minute lahko vsakič
        # zamenjala mesti in besedilo ne bi bilo ponovljivo.
        cas = "2026-09-12T08:00:00+00:00"
        nabor = [snov("b", taken_at=cas), snov("a", taken_at=cas)]

        assert [x.id for x in izbrane(nabor, ["a", "b"])] == ["a", "b"]
        assert izbrane(nabor, ["a", "b"]) == izbrane(list(reversed(nabor)), ["b", "a"])

    def test_neizbrana_snov_v_besedilo_ne_pride(self) -> None:
        nabor = [snov("a1"), snov("a2")]

        assert [x.id for x in izbrane(nabor, ["a1"])] == ["a1"]

    def test_identifikator_izven_nabora_se_tiho_izpusti(self) -> None:
        # Tuja družina, drug predmet, arhiv in neobstoječ zapis: nabor določi
        # klicalec, ta funkcija pozna samo to, kaj je v njem.
        nabor = [snov("a1")]

        assert [x.id for x in izbrane(nabor, ["a1", "tuja", "arhivirana"])] == ["a1"]

    def test_sam_tuj_identifikator_da_prazen_izbor(self) -> None:
        assert izbrane([snov("a1")], ["tuja"]) == []

    def test_ponovljen_identifikator_prispeva_enkrat(self) -> None:
        # Obrazec ga tako ne pošlje; podvojena glava bi bila tihi nesmisel.
        assert [x.id for x in izbrane([snov("a1")], ["a1", "a1"])] == ["a1"]

    def test_prazen_nabor_prenese_kateri_koli_izbor(self) -> None:
        assert izbrane([], ["a1"]) == []


class TestSestaviVrstnegaRedaNePopravlja:
    """`sestavi` uredi ravno toliko, kolikor dobi.

    Ločnica med `izbrane` in `sestavi` je namenska: kdor si zaporedje sestavi
    sam (`V4-R04`), dobi svoje in ne našega.
    """

    def test_dano_zaporedje_ostane(self) -> None:
        novejsa = snov("novejsa", koda="SLO", taken_at="2026-09-12T08:00:00+00:00")
        starejsa = snov("starejsa", koda="MAT", taken_at="2026-09-04T08:00:00+00:00")

        izid = sestavi([novejsa, starejsa])

        assert izid.besedilo.index("## SLO") < izid.besedilo.index("## MAT")
