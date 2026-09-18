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
import { glaveSeje, type Seja } from './prijava';

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
 * Odgovor na neveljavno **vsebino** paketa: slab poskus (neveljavna ocena,
 * postavka, ki je ni) ali neusklajena pogodba med APK in strežnikom — v drugem
 * primeru je zavrnjen vsak poskus. Samo takrat ima razbitje paketa smisel
 * (`docs/odlocitve/ADR-020`); ob 401, 403 ali 404 ne gre za vsebino in bi
 * strežnik zavrnil vsak poskus enako.
 */
const VSEBINSKA_ZAVRNITEV = 422;

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
 * - **strežnik je paket trajno zavrnil** (`PaketZavrnjen`) — ob `422` se paket
 *   pošlje znova po en poskus (`posljiPosamicno`), obhod pa gre v vsakem
 *   primeru naprej: naslednji paketi se pošljejo in seznam se prebere. Sicer bi en sam neveljaven
 *   poskus za vedno odrezal telefon od novih kvizov, strežnik pa od vseh ocen,
 *   ki so prišle za njim — paket je na strežniku vse ali nič.
 *
 * V nobeni veji se poskus **ne izgubi** (`ADR-012`).
 *
 * `odprti` je kviz, ki ga Maša ta hip rešuje; ta ne izgine, tudi če ga strežnik
 * ne vrača več (`ADR-019` C).
 *
 * `zavrnjeni` so poskusi, ki jih je strežnik posamič zavrnil s `422`. Obhod jih
 * ne pošilja, dokler množica živi — klicatelj jo hrani za čas zagona
 * aplikacije (`ADR-020`). Brez tega bi vsak obhod z N obtičalimi poskusi
 * poslal 1 + N zahtevkov, za vedno. Ob novem zagonu se poskusijo znova: ko je
 * vzrok na strežniku odpravljen, gredo gor sami. Po isti logiki živi v
 * pomnilniku odmik pri prenosu slik (odločitev 14 v `docs/plan/V1-R02.md`).
 */
export async function uskladiKvize(
  db: MaterialsDatabase,
  odjemalec: OdjemalecKvizov,
  lastnik: string | null,
  odprti: string | null = null,
  zavrnjeni: Set<string> = new Set(),
): Promise<IzidUsklajevanja> {
  const cakajoci = (await neprenesenePoskuse(db, lastnik)).filter(
    (poskus) => !zavrnjeni.has(poskus.id),
  );
  let poslani = 0;
  for (let zacetek = 0; zacetek < cakajoci.length; zacetek += NAJVEC_V_PAKETU) {
    const paket = cakajoci.slice(zacetek, zacetek + NAJVEC_V_PAKETU);
    try {
      await odjemalec.posljiPoskuse(paket);
    } catch (napaka) {
      if (!(napaka instanceof PaketZavrnjen)) throw napaka;
      if (napaka.status === VSEBINSKA_ZAVRNITEV) {
        poslani += await posljiPosamicno(db, odjemalec, paket, zavrnjeni);
      }
      continue;
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
    lastnik,
  );

  return { poslani, naStrezniku: kvizi.length, pobrisani };
}

/**
 * Zavrnjen paket pošlje znova, po en poskus; vrne, koliko jih je strežnik
 * sprejel (`docs/odlocitve/ADR-020`).
 *
 * Tako gre gor vse razen poskusa, ki ga strežnik zavrača — ta ostane
 * neprenesen in gre v `zavrnjeni`, da ga obhodi do naslednjega zagona ne
 * pošiljajo več. Paket z enim samim poskusom se ne ponavlja: njegova
 * zavrnitev je že sodba o tem poskusu, zato gre ta poskus v `zavrnjeni` takoj.
 *
 * Nedosegljiv strežnik sredi pošiljanja vrže naprej in konča obhod; kar je bilo
 * do takrat sprejeto, je že označeno.
 */
async function posljiPosamicno(
  db: MaterialsDatabase,
  odjemalec: OdjemalecKvizov,
  paket: readonly Poskus[],
  zavrnjeni: Set<string>,
): Promise<number> {
  if (paket.length <= 1) {
    for (const poskus of paket) zavrnjeni.add(poskus.id);
    return 0;
  }

  let sprejeti = 0;
  for (const poskus of paket) {
    try {
      await odjemalec.posljiPoskuse([poskus]);
    } catch (napaka) {
      if (!(napaka instanceof PaketZavrnjen)) throw napaka;
      // Zavrnitev, ki ni o vsebini (npr. 401 sredi razbijanja), bi zadela
      // vsak naslednji poskus enako — razbijanje se ustavi, poskusi ostanejo
      // in se ne zapomnijo: krivda ni v njih.
      if (napaka.status !== VSEBINSKA_ZAVRNITEV) break;
      zavrnjeni.add(poskus.id);
      continue;
    }
    await oznaciPrenesene(db, [poskus.id], new Date().toISOString());
    sprejeti += 1;
  }
  return sprejeti;
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
  seja: Seja,
  zahteva: Zahteva = fetch as unknown as Zahteva,
  casovnaOmejitevMs: number = CASOVNA_OMEJITEV_MS,
): OdjemalecKvizov {
  const glave = { ...glaveSeje(seja), 'Content-Type': 'application/json' };

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
