/**
 * Čakalna vrsta za prenos.
 *
 * Dva dela: `prenesiCakajoce` je čista logika, ki oddela vrsto in posodobi
 * bazo, `ustvariRazporejevalnik` pa skrbi za to, kdaj se to zgodi.
 *
 * Worker teče **samo, dokler je aplikacija v ospredju** — brez opravil v
 * ozadju. Zato odmik med poskusi živi v pomnilniku in ne v bazi: ponoven
 * zagon aplikacije je sam po sebi znak, da naj se poskusi znova (odločitev 14
 * v `docs/plan/V1-R02.md`).
 */

import {
  listPending,
  markFailed,
  markSynced,
  recordAttempt,
  type MaterialsDatabase,
} from '../db/materials';
import type { Material } from '../types';
import type { Izid } from './upload';

/** Koliko časa mine med rednimi poskusi, dokler gre vse gladko. */
export const INTERVAL_MS = 30_000;

/** Najdaljši odmik po zaporednih neuspehih. */
export const NAJVECJI_ODMIK_MS = 5 * 60_000;

export type Povzetek = {
  /** Koliko zapisov je bilo prenesenih. */
  preneseni: number;
  /** Koliko jih ostaja v vrsti (poskusimo znova). */
  cakajoci: number;
  /** Koliko jih je strežnik dokončno zavrnil. */
  neuspeli: number;
};

export type PrenesiEno = (material: Material) => Promise<Izid>;

/**
 * Oddela celotno vrsto, enega za drugim.
 *
 * Zaporedno in ne vzporedno namenoma: obseg je 5–25 slik na teden, hkratni
 * prenosi pa bi prinesli samo načine odpovedi (odločitev 12).
 *
 * Ob prvi zaznani nedosegljivosti strežnika se ustavi. Če ni šlo za prvo
 * sliko, ne bo šlo niti za dvajseto, vsaka pa bi stala svoj potek časa.
 */
export async function prenesiCakajoce(
  db: MaterialsDatabase,
  prenesiEno: PrenesiEno,
): Promise<Povzetek> {
  const cakajoci = await listPending(db);
  const povzetek: Povzetek = { preneseni: 0, cakajoci: 0, neuspeli: 0 };

  for (const [zaporedna, material] of cakajoci.entries()) {
    const izid = await prenesiEno(material);

    if (izid.vrsta === 'synced') {
      await markSynced(db, material.id);
      povzetek.preneseni += 1;
      continue;
    }

    if (izid.vrsta === 'failed') {
      await markFailed(db, material.id, izid.razlog);
      povzetek.neuspeli += 1;
      continue;
    }

    await recordAttempt(db, material.id, izid.razlog);
    povzetek.cakajoci = cakajoci.length - zaporedna;
    return povzetek;
  }

  return povzetek;
}

/**
 * Odmik do naslednjega poskusa.
 *
 * Po uspehu spet redni interval; po neuspehu podvojitev do zgornje meje, da
 * ob ugasnjenem strežniku ne kurimo baterije.
 */
export function naslednjiOdmik(prejsnji: number, jeUspelo: boolean): number {
  if (jeUspelo) return INTERVAL_MS;
  return Math.min(prejsnji * 2, NAJVECJI_ODMIK_MS);
}

export type Razporejevalnik = {
  /** Takojšen poskus in zagon rednega ponavljanja. */
  zazeni(): void;
  /** Ustavi ponavljanje; tekoči prenos se dokonča. */
  ustavi(): void;
  /** Takojšen poskus, brez čakanja na naslednji interval. */
  sprozi(): void;
};

/**
 * Ročica časovnika. Lasten tip zato, ker se `setTimeout` v React Native in v
 * Node.js razlikujeta (število proti predmetu) in bi se tipa razšla.
 */
export type CasovnikId = ReturnType<typeof setTimeout>;

export type RazporejevalnikOdvisnosti = {
  db: MaterialsDatabase;
  prenesiEno: PrenesiEno;
  /** Kliče se po vsakem ciklu, da vmesnik osveži števce. */
  poCiklu?: (povzetek: Povzetek) => void;
  /** Podtakljivo v testih, da jim ni treba čakati pravega časa. */
  nastaviCasovnik?: (f: () => void, ms: number) => CasovnikId;
  pocistiCasovnik?: (id: CasovnikId) => void;
};

/**
 * Razporejevalnik z eno zanko naenkrat.
 *
 * Zapora `tece` je bistvena: brez nje bi `sprozi()` po vsakem shranjevanju
 * lahko pognal drugo zanko čez prvo in isti zapis bi šel na strežnik dvakrat.
 * Strežnik je sicer idempotenten, a to je njegova varovalka, ne izgovor.
 */
export function ustvariRazporejevalnik(o: RazporejevalnikOdvisnosti): Razporejevalnik {
  const nastaviCasovnik =
    o.nastaviCasovnik ?? ((f: () => void, ms: number): CasovnikId => setTimeout(f, ms));
  const pocistiCasovnik =
    o.pocistiCasovnik ?? ((id: CasovnikId): void => clearTimeout(id));

  let casovnik: CasovnikId | null = null;
  let odmik = INTERVAL_MS;
  let tece = false;
  let ustavljen = true;
  /** Sprožitev, ki je prišla med tekočim ciklom in je ne smemo izgubiti. */
  let ponovi = false;

  function razporedi(ms: number): void {
    if (ustavljen) return;
    if (casovnik !== null) pocistiCasovnik(casovnik);
    casovnik = nastaviCasovnik(() => {
      void cikel();
    }, ms);
  }

  async function cikel(): Promise<void> {
    if (tece) {
      ponovi = true;
      return;
    }
    tece = true;

    try {
      const povzetek = await prenesiCakajoce(o.db, o.prenesiEno);
      odmik = naslednjiOdmik(odmik, povzetek.cakajoci === 0);
      o.poCiklu?.(povzetek);
    } catch {
      // Napaka pri branju ali pisanju baze ne sme ustaviti workerja in ne sme
      // pustiti nezavrnjene obljube — `sprozi()` se kliče brez čakanja in
      // klicatelj te napake nima kje ujeti.
      odmik = naslednjiOdmik(odmik, false);
    } finally {
      tece = false;
    }

    if (ponovi) {
      ponovi = false;
      razporedi(0);
      return;
    }
    razporedi(odmik);
  }

  return {
    zazeni() {
      ustavljen = false;
      odmik = INTERVAL_MS;
      void cikel();
    },
    ustavi() {
      ustavljen = true;
      if (casovnik !== null) {
        pocistiCasovnik(casovnik);
        casovnik = null;
      }
    },
    sprozi() {
      if (ustavljen) return;
      void cikel();
    },
  };
}
