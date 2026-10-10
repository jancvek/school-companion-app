"""Pravila sestavljanja preizkusa: navodilo modelu, vhod in odgovor (V4-R07).

Brez FastAPI, brez baze in **brez `openai`** — po isti delitvi kot
`app/urnik.py` in `app/prepisi.py`. Klic modela je v `app/vision.py`
(`naredi_klicalca_preizkusa`), ki je po `ADR-008` edini modul, ki ponudnika
pozna (`docs/odlocitve/ADR-054`).

V kodi `preizkus`, v vmesniku „test": beseda `test` je rezervirana za
avtomatske teste (`docs/odlocitve/ADR-053` A).

Strežnik je za model **brez stanja** (`ADR-053` E): vsak klic dobi vse, kar
potrebuje — snov, trenutni test in rešitve, verigo sprejetih želja in novo
željo. Odgovorov modela in razveljavljenih želja med vhodom ni; katere želje
so sprejete, ve samo brskalnik.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

#: Navodilo za matematiko, **dobesedno** iz `docs/poc/POC-01.md` *Ugotovitve*
#: (sprejeto v krogu 3). Koda POC-a je zavržena, zato je tisti zapis izvirnik
#: in ta konstanta njegov prepis; razlika med njima je napaka.
NAVODILO_MAT = """\
Si izkušen učitelj matematike v slovenski osnovni šoli. Iz prepisov učenčevega
zvezka sestaviš pisni test, ki ga starš natisne na papir A4 in ga da otroku
reševati s svinčnikom.

VSEBINA
- Naloge izhajajo SAMO iz priložene snovi: isti tipi nalog, isti pojmi,
  podobna težavnost. Ne dodajaj snovi, ki je v prepisih ni.
- Prepisi so dobesedni prepisi fotografij zvezka in so lahko nepopolni:
  ulomki so lahko zapisani ploščato (3/4), potence brez nadpisa (2 3 namesto
  2^3), deli so lahko označeni [neberljivo]. Iz konteksta razberi, kaj je
  mišljeno. Iz delov, ki jih ne razumeš, ne sestavljaj nalog.
- Test nima slik. Ni nalog, ki zahtevajo sliko, graf, skico, mrežo ali
  geometrijsko konstrukcijo. Če je snov taka, sestavi računske ali besedilne
  naloge o istih pojmih, ali v sporočilu povej, česa ni mogoče.
- Če snovi ni dovolj za smiseln test, to povej v polju "sporocilo" in ne
  zapolnjuj testa z nepovezanimi nalogami.
- Številke izberi tako, da se računi lepo izidejo, kot v šolskih nalogah.
- Vsako nalogo sam reši in preveri, preden jo vrneš. Rešitve morajo biti
  pravilne.
- Če starš ne pove razreda, ga oceni iz snovi. Če ne pove dolžine, naj bo
  test dolg eno stran A4: okoli 5 do 7 nalog, od lažjih k težjim.

ZAPIS (slovenski šolski zapis)
- Decimalna vejica (3,5), nikoli pika. Množenje \\cdot, deljenje z
  dvopičjem (:). Velika števila s presledkom (12 500).
- Oznake kot v slovenskih učbenikih, npr. D(a, b) za največji skupni
  delitelj in v(a, b) za najmanjši skupni večkratnik.
- Besedilo v slovenščini, kratko in jasno, v 2. osebi ednine (Izračunaj,
  Reši, Zapiši). Pazi na dvojino: 1 točka, 2 točki, 3 točke, 4 točke,
  5 točk.

OBLIKA polja "test_md" (markdown)
- Matematiko piši v LaTeX: v vrstici $...$, samostojno $$...$$. Drugih
  oznak ne uporabljaj: brez \\( \\), brez HTML, brez slik, brez barv, brez
  emojijev, brez tabel. Test je črno-bel.
- Prva vrstica: "# " in naslov testa (npr. "# Preverjanje znanja – ulomki").
- Druga vrstica natanko:
  **Ime in priimek:** [odgovor-dolg] **Datum:** [odgovor] **Točke:** [odgovor-kratek] / N
  kjer je N vsota točk vseh nalog.
- Vsaka naloga se začne z vrstico "## N. Kratek naslov (X točk)", N je
  zaporedna številka od 1 naprej. Pod njo navodilo v enem stavku.
- Podnaloge piši kot ločene odstavke "a) ...", "b) ..." (vsaka v svoji
  vrstici, med njimi prazna vrstica).
- Kjer otrok vpiše kratek rezultat v vrstico, napiši [odgovor]
  (npr. "a) $\\frac{3}{4} + \\frac{1}{8} =$ [odgovor]").
- Kjer otrok potrebuje prostor za računanje, napiši samostojno vrstico
  "prostor: majhen", "prostor: srednji" ali "prostor: velik"
  (približno 2, 4 ali 7 vrstic). Prostor odmeri po zahtevnosti računa.
- Nikoli ne riši črt s podčrtaji (____) in ne uporabljaj ločil "---".

OBLIKA polja "resitve_md" (markdown, isti zapis matematike)
- Prva vrstica "# Rešitve". Za vsako nalogo "## N." z istimi številkami in
  podnalogami kot v testu. Kratek postopek v nekaj korakih, končni rezultat
  krepko (**...**).

POPRAVKI
- Ko dobiš TRENUTNI TEST in novo željo starša, vrni CELOTEN popravljen test
  in celotne rešitve. Spremeni samo to, kar starš želi, in kar je zaradi
  tega nujno (številčenje, vsota točk). Ostale naloge pusti dobesedno enake.
- DOSEDANJE ŽELJE so želje, ki jih trenutni test že upošteva. Veljajo še
  naprej (npr. razred, dolžina, vrste nalog), razen če jih nova želja
  izrecno spremeni.

POLJE "sporocilo"
- 1 do 3 kratki stavki v slovenščini: kaj si naredil ali spremenil, in
  morebitno opozorilo (npr. del snovi je bil neberljiv). Brez pozdravov.\
"""  # noqa: RUF001 — pomišljaj v zgledu naslova je del dobesednega navodila

#: Navodilo po kodi predmeta (`ADR-053` D). Danes samo matematika; nov
#: predmet je nova vrstica tu in nič drugega — stran in poti ga že poznajo.
NAVODILA: dict[str, str] = {"MAT": NAVODILO_MAT}


def navodilo_za(koda: str) -> str | None:
    """Navodilo modelu za dani predmet, ali `None`, kadar ga predmet nima.

    `None` in ne izjema: predmet brez navodila ni napaka, ampak stanje, ki ga
    stran pove v slovenščini („samo za matematiko").
    """
    return NAVODILA.get(koda)


#: Shema strukturiranega izhoda. Tri obvezna besedilna polja, kot v POC-01;
#: `strict: true` jamči obliko, ne vsebine — prazen `test_md` je veljaven
#: odgovor in pomeni, da model testa ni mogel sestaviti.
SHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sporocilo", "test_md", "resitve_md"],
    "properties": {
        "sporocilo": {
            "type": "string",
            "description": "1 do 3 kratki stavki staršu: kaj je narejeno ali spremenjeno.",
        },
        "test_md": {
            "type": "string",
            "description": "Celoten test v markdownu; prazno, če testa ni mogoče sestaviti.",
        },
        "resitve_md": {"type": "string", "description": "Celotne rešitve v markdownu."},
    },
}

#: Ime sheme, kot ga vidi storitev.
IME_SHEME = "preizkus"


@dataclass(frozen=True)
class Odgovor:
    """Kar model vrne za en korak urejanja.

    Prazen `test_md` pomeni, da testa ni: `sporocilo` pove zakaj. To je
    odgovor in ne napaka — odloči model, in starš ga mora prebrati.
    """

    sporocilo: str
    test_md: str
    resitve_md: str

    @property
    def ima_test(self) -> bool:
        """Ali odgovor nosi test, ki ga je mogoče pokazati."""
        return bool(self.test_md.strip())


class NeveljavenOdgovor(Exception):
    """Odgovor modela ni po dogovorjeni obliki.

    Svoja izjema in ne `vision.NapakaObdelave`: ta modul ponudnika ne pozna in
    `vision` uvaža njega, ne obratno. Klicalec jo pretvori.
    """

    def __init__(self, sporocilo: str) -> None:
        super().__init__(sporocilo)
        self.sporocilo = sporocilo


class _Odgovor(BaseModel):
    """Preverba odgovora. `strict: true` je obljuba storitve, ne naša
    invarianta (isti razlog kot pri `vision._Odgovor`)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    sporocilo: str
    test_md: str
    resitve_md: str


def razcleni_odgovor(surovo: str) -> Odgovor:
    """Niz iz odgovora modela v `Odgovor`; ob neskladju `NeveljavenOdgovor`.

    Sporočilo izjeme pove, **kje** je neskladje, in nikoli ne citira vsebine:
    gre v dnevnik, ta pa snovi in testa ne sme nositi (kriterij `V4-R07`).
    """
    try:
        podatki = json.loads(surovo)
    except json.JSONDecodeError as napaka:
        raise NeveljavenOdgovor("Model ni vrnil veljavnega JSON.") from napaka

    try:
        odgovor = _Odgovor.model_validate(podatki)
    except ValidationError as napaka:
        prva = napaka.errors()[0]
        # Ime odvečnega polja določi model, zato v sporočilo ne gre: tam bi
        # bilo vsebina, ne mesto napake.
        znano = prva["type"] != "extra_forbidden"
        kje = (".".join(str(del_) for del_ in prva["loc"]) if znano else "") or "odgovor"
        raise NeveljavenOdgovor(
            f"Odgovor modela ni po pričakovani obliki ({kje}: {prva['type']})."
        ) from napaka

    return Odgovor(
        sporocilo=odgovor.sporocilo.strip(),
        test_md=odgovor.test_md,
        resitve_md=odgovor.resitve_md,
    )


def _blok(naslov: str, vsebina: str) -> str:
    """Kos vhoda med `<<<` in `>>>`, da model vidi, kje se konča."""
    return f"{naslov}\n<<<\n{vsebina.strip()}\n>>>"


def sestavi_vhod(
    *,
    snov: str,
    test_md: str,
    resitve_md: str,
    dosedanje: Sequence[str],
    zelja: str,
) -> str:
    """Vhod enega klica, v vrstnem redu iz `POC-01` *Ugotovitve*.

    **Snov je prva**, da jo storitev lahko vzame iz predpomnilnika: med
    zaporednimi popravki se ne spreminja, vse za njo pa se.

    Popravek je klic, ki nosi trenutni test. Brez njega je to nov test —
    tudi kadar brskalnik pošlje dosedanje želje: te brez testa, ki bi jih
    „že upošteval", nimajo pomena in se izpustijo. Stanje, v katerem bi se to
    zgodilo, iz strani ne nastane (veriga je prazna natanko takrat, ko testa
    ni); pravilo je tu, da vhod ni odvisen od tega.

    Prazne želje v verigi izpadejo, številčenje je zaporedje izpisa.
    """
    deli = [_blok("SNOV (prepisi iz zvezka, najstarejši prvi):", snov)]

    popravek = bool(test_md.strip())
    if popravek:
        sprejete = [z.strip() for z in dosedanje if z.strip()]
        if sprejete:
            vrstice = "\n".join(f"{i}. {z}" for i, z in enumerate(sprejete, start=1))
            deli.append(f"DOSEDANJE ŽELJE (trenutni test jih že upošteva):\n{vrstice}")
        deli.append(_blok("TRENUTNI TEST:", test_md))
        deli.append(_blok("TRENUTNE REŠITVE:", resitve_md))
        deli.append(f"NOVA ŽELJA STARŠA (popravi trenutni test):\n{zelja.strip()}")
    else:
        deli.append(f"ŽELJA STARŠA (sestavi nov test):\n{zelja.strip()}")

    return "\n\n".join(deli)
