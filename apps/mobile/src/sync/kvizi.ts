/**
 * Usklajevanje kvizov s strežnikom (V2-R02).
 *
 * En obhod: najprej **poskusi gor**, nato **seznam dol**. Vrstni red ni okus —
 * strežnik kviz označi za rešenega v isti transakciji kot zadnji poskus, zato
 * je seznam, prebran po prenosu, že brez pravkar rešenega kviza.
 *
 * Strežnik vrne **celoten delovni seznam** čakajočih kvizov, brez kazalca in
 * brez časa zadnje sinhronizacije — isti vzorec kot arhiv (`ADR-011`,
 * `ADR-016` F). Kar na seznamu ni, je rešeno ali preklicano.
 *
 * Modul je v `src/sync/`, ker se dotakne omrežja — regresijski test
 * `__tests__/no-network.test.ts` drugje tega ne dovoli.
 */

import type { ServerConfig } from '../config/server';
import {
  neprenesenePoskuse,
  oznaciPrenesene,
  pobrisiKvizeRazen,
  shraniKviz,
} from '../db/kvizi';
import type { MaterialsDatabase } from '../db/materials';
import type { KvizStreznika, Poskus } from '../types';
import { poslji, type Zahteva } from './http';

/** Koliko čakamo na en klic; isti razlog kot pri arhivu (`izbrisi.ts`). */
export const CASOVNA_OMEJITEV_MS = 30_000;

/**
 * Največ poskusov v enem paketu. Strežnik jih sprejme do 1000; pol tega je
 * dovolj, da ena zahteva ostane kratka, tudi če se jih je nabralo za teden.
 */
export const NAJVEC_V_PAKETU = 500;

/** Kar ta modul potrebuje od strežnika; v testih se podtakne. */
export type OdjemalecKvizov = {
  /** Pošlje paket poskusov. Vrže, če jih strežnik ni sprejel. */
  posljiPoskuse(poskusi: readonly Poskus[]): Promise<void>;
  /** Kvizi, ki čakajo na reševanje. Vrže, če seznama ni bilo mogoče prebrati. */
  preberiKvize(): Promise<KvizStreznika[]>;
};

/**
 * Kode, ki so 4xx, a pomenijo „poskusi kasneje", ne „ne bo šlo" — ista meja
 * kot pri prenosu slik (`ADR-004`, `upload.ts`).
 */
const ZACASNE_4XX = new Set([408, 429]);

/**
 * Strežnik je paket poskusov **trajno** zavrnil (4xx razen 408 in 429).
 *
 * Svoj razred, ker ga `uskladiKvize` obravnava drugače od nedosegljivega
 * strežnika: obhod gre naprej in seznam kvizov se vseeno prebere
 * (`docs/odlocitve/ADR-020`).
 */
export class PaketZavrnjen extends Error {
  constructor(readonly status: number) {
    super(`Strežnik je vrnil ${status}.`);
    this.name = 'PaketZavrnjen';
  }
}

/** Kar se je v enem obhodu zgodilo. */
export type IzidUsklajevanja = {
  /** Koliko poskusov je strežnik sprejel. Zavrnjeni tu niso šteti. */
  poslani: number;
  /** Koliko kvizov je na seznamu strežnika. */
  naStrezniku: number;
  /** Koliko lokalnih kvizov je šlo, ker jih strežnik ne vrača več. */
  pobrisani: number;
};

/**
 * En obhod usklajevanja.
 *
 * Neuspeh pri prenosu poskusov ima dve veji (`docs/odlocitve/ADR-020`):
 *
 * - **strežnik je nedosegljiv** (omrežje, potekel čas, 5xx, 408, 429) — obhod
 *   se konča, preden se seznam sploh prebere; branje bi spodletelo enako;
 * - **strežnik je paket trajno zavrnil** (`PaketZavrnjen`) — poskusi paketa
 *   ostanejo nepreneseni, obhod pa gre naprej: naslednji paketi se pošljejo in
 *   seznam se prebere. Sicer bi en sam neveljaven poskus za vedno odrezal
 *   telefon od novih kvizov.
 *
 * V nobeni veji se poskus **ne izgubi** (`ADR-012`).
 *
 * `odprti` je kviz, ki ga Maša ta hip rešuje; ta ne izgine, tudi če ga strežnik
 * ne vrača več (`ADR-019` C).
 */
export async function uskladiKvize(
  db: MaterialsDatabase,
  odjemalec: OdjemalecKvizov,
  odprti: string | null = null,
): Promise<IzidUsklajevanja> {
  const cakajoci = await neprenesenePoskuse(db);
  let poslani = 0;
  for (let zacetek = 0; zacetek < cakajoci.length; zacetek += NAJVEC_V_PAKETU) {
    const paket = cakajoci.slice(zacetek, zacetek + NAJVEC_V_PAKETU);
    try {
      await odjemalec.posljiPoskuse(paket);
    } catch (napaka) {
      if (napaka instanceof PaketZavrnjen) continue;
      throw napaka;
    }
    await oznaciPrenesene(
      db,
      paket.map((poskus) => poskus.id),
      new Date().toISOString(),
    );
    poslani += paket.length;
  }

  const kvizi = await odjemalec.preberiKvize();
  for (const kviz of kvizi) {
    await shraniKviz(db, kviz);
  }
  const pobrisani = await pobrisiKvizeRazen(
    db,
    kvizi.map((kviz) => kviz.id),
    odprti,
  );

  return { poslani, naStrezniku: kvizi.length, pobrisani };
}

function jeNiz(vrednost: unknown): vrednost is string {
  return typeof vrednost === 'string';
}

/** Ena postavka ali `null`, če ni po pogodbi. */
function postavka(surova: unknown): KvizStreznika['items'][number] | null {
  if (typeof surova !== 'object' || surova === null) return null;
  const p = surova as Record<string, unknown>;
  if (
    !jeNiz(p.id) ||
    typeof p.position !== 'number' ||
    !jeNiz(p.question) ||
    !jeNiz(p.answer) ||
    typeof p.answered !== 'boolean'
  ) {
    return null;
  }
  return {
    id: p.id,
    position: p.position,
    question: p.question,
    answer: p.answer,
    answered: p.answered,
  };
}

/** En kviz ali `null`, če on ali katera od njegovih postavk ni po pogodbi. */
function kviz(surov: unknown): KvizStreznika | null {
  if (typeof surov !== 'object' || surov === null) return null;
  const k = surov as Record<string, unknown>;
  if (!jeNiz(k.id) || !jeNiz(k.name) || !jeNiz(k.created_at) || !Array.isArray(k.items)) {
    return null;
  }
  const postavke = k.items.map(postavka);
  if (postavke.length === 0 || postavke.some((p) => p === null)) return null;
  return {
    id: k.id,
    name: k.name,
    created_at: k.created_at,
    items: postavke as KvizStreznika['items'],
  };
}

/**
 * Seznam kvizov iz odgovora; strežniku ne verjamemo na besedo.
 *
 * Nerazberljiv odgovor kot celota **vrže** in ne vrne praznega seznama:
 * prazen seznam bi usklajevanje razumelo kot „nič več ne čaka" in bi
 * pobrisalo vse lokalne kvize, tudi napol rešene. Posamezen pokvarjen kviz se
 * izpusti — tak itak ni rešljiv.
 */
export function kviziIzOdgovora(telo: unknown): KvizStreznika[] {
  if (typeof telo !== 'object' || telo === null) {
    throw new Error('Strežnik je vrnil nerazberljiv seznam kvizov.');
  }
  const kvizi = (telo as { quizzes?: unknown }).quizzes;
  if (!Array.isArray(kvizi)) {
    throw new Error('Strežnik je vrnil nerazberljiv seznam kvizov.');
  }
  return kvizi.map(kviz).filter((k): k is KvizStreznika => k !== null);
}

/**
 * Odjemalec, ki govori s pravim strežnikom.
 *
 * Neuspešen odgovor vrže, iz istega razloga kot pri arhivu: tiho vračanje
 * praznega bi napako skrilo — tu bi celo pobrisalo lokalne kvize.
 */
export function ustvariOdjemalcaKvizov(
  nastavitve: ServerConfig,
  zahteva: Zahteva = fetch as unknown as Zahteva,
  casovnaOmejitevMs: number = CASOVNA_OMEJITEV_MS,
): OdjemalecKvizov {
  const glave = { 'X-API-Key': nastavitve.apiKey, 'Content-Type': 'application/json' };

  return {
    async posljiPoskuse(poskusi) {
      const odgovor = await poslji(
        zahteva,
        `${nastavitve.baseUrl}/quiz-attempts`,
        {
          method: 'POST',
          headers: glave,
          // Samo polja iz pogodbe. `quiz_id` in `uploaded_at` sta lokalna.
          body: JSON.stringify({
            attempts: poskusi.map((p) => ({
              id: p.id,
              quiz_item_id: p.quiz_item_id,
              mode: p.mode,
              rating: p.rating,
              shown_at: p.shown_at,
              revealed_at: p.revealed_at,
              answered_at: p.answered_at,
            })),
          }),
        },
        casovnaOmejitevMs,
      );
      if (!odgovor.ok) {
        const trajno =
          odgovor.status >= 400 && odgovor.status < 500 && !ZACASNE_4XX.has(odgovor.status);
        if (trajno) throw new PaketZavrnjen(odgovor.status);
        throw new Error(`Strežnik je vrnil ${odgovor.status}.`);
      }
    },

    async preberiKvize() {
      const odgovor = await poslji(
        zahteva,
        `${nastavitve.baseUrl}/quizzes/pending`,
        { method: 'GET', headers: glave },
        casovnaOmejitevMs,
      );
      if (!odgovor.ok) {
        throw new Error(`Strežnik je vrnil ${odgovor.status}.`);
      }
      return kviziIzOdgovora(await odgovor.json());
    },
  };
}
