/**
 * Brisanje snovi, ki je na strežniku arhivirana (V1-R07).
 *
 * Strežnik vrne **delovni seznam**: kar je arhivirano in česar naprava še ni
 * potrdila. Telefon si zato ne zapomni ničesar — ne kazalca ne časa zadnje
 * sinhronizacije. Časovni žig bi padel na razliki ur in na transakciji, ki se
 * potrdi šele potem, ko je telefon kazalec že premaknil čezenj
 * (`docs/odlocitve/ADR-011`).
 *
 * Modul je v `src/sync/`, ker se dotakne omrežja — regresijski test
 * `__tests__/no-network.test.ts` drugje tega ne dovoli.
 *
 * V vmesniku se ob tem ne zgodi nič: slika iz Zgodovine samo izgine.
 */

import { deleteById, findById, type MaterialsDatabase } from '../db/materials';
import { removePhoto } from '../photos/store';
import type { ServerConfig } from '../config/server';
import type { Material } from '../types';

/** Kako pogosto preverjamo, ali je kaj za pobrisati. */
export const INTERVAL_MS = 5 * 60_000;

/**
 * Koliko čakamo na en klic.
 *
 * Isti razlog kot pri prenosu: cikel, ki se ne konča, pusti zaporo postavljeno
 * in ponavljanje je do ponovnega zagona aplikacije mrtvo.
 */
export const CASOVNA_OMEJITEV_MS = 30_000;

/** Kar ta modul potrebuje od strežnika; v testih se podtakne. */
export type Odjemalec = {
  /** `id` snovi, ki jih je treba pobrisati. */
  preberiSeznam(): Promise<string[]>;
  /** Sporoči, da danih snovi na tej napravi ni več. */
  potrdi(ids: string[]): Promise<void>;
};

/** Kar se je v enem obhodu zgodilo. */
export type PovzetekBrisanja = {
  /**
   * Koliko zapisov je šlo **do konca** — vrstica in datoteka.
   *
   * Zapis, ki mu je šla vrstica, datoteka pa ne, tu ni štet; tega pokrije
   * `neuspeli`. Baza se je takrat vseeno spremenila.
   */
  pobrisani: number;
  /** Koliko `id` je bilo strežniku potrjenih (tudi tistih, ki jih ni bilo). */
  potrjeni: number;
  /**
   * Koliko jih ni šlo do konca in ostajajo nepotrjeni.
   *
   * Ločeno od `pobrisani`, ker se lahko zgodi oboje hkrati: vrstica je šla,
   * datoteka pa ne. Klicatelj po tem ve, da mora osvežiti števce, čeprav
   * `pobrisani` ostaja `0`.
   */
  neuspeli: number;
};

/**
 * Pobriše en zapis: **najprej vrstico, nato datoteko.**
 *
 * Vrstni red je obraten od shranjevanja in namenoma: vrstica brez datoteke je
 * vidna okvara v Zgodovini, osirotela datoteka pa je nevidna in stane samo
 * prostor. Napaka pri datoteki se ne požre — klicatelj se po njej odloči, ali
 * sme brisanje potrditi.
 */
export async function pobrisiLokalno(
  db: MaterialsDatabase,
  material: Material,
  pobrisiDatoteko: (fileUri: string) => void = removePhoto,
): Promise<void> {
  await deleteById(db, material.id);
  pobrisiDatoteko(material.file_uri);
}

/**
 * En obhod: preberi seznam, pobriši, potrdi.
 *
 * Potrditev gre **šele po** dejanskem brisanju. Obratni vrstni red bi pomenil
 * zapis, ki ga strežnik šteje za pospravljenega, na telefonu pa ostane.
 *
 * Zapis, ki ga na tej napravi ni (sveža namestitev), se potrdi takoj:
 * potrditev pomeni „tega tu ni več", ne „pravkar sem ga izbrisal". Brez tega
 * seznam po ponovni namestitvi nikoli ne bi padel na nič.
 *
 * Če brisanje enega zapisa spodleti, ta `id` ostane nepotrjen in obhod se
 * nadaljuje z ostalimi. Ponovljena potrditev je neškodljiva, ker je prenos
 * *at-least-once* in strežnik drugo potrditev prezre.
 */
export async function preveriIzbrisane(
  db: MaterialsDatabase,
  odjemalec: Odjemalec,
  pobrisiDatoteko: (fileUri: string) => void = removePhoto,
): Promise<PovzetekBrisanja> {
  const ids = await odjemalec.preberiSeznam();
  const povzetek: PovzetekBrisanja = { pobrisani: 0, potrjeni: 0, neuspeli: 0 };
  if (ids.length === 0) return povzetek;

  const potrjeni: string[] = [];

  for (const id of ids) {
    try {
      const material = await findById(db, id);
      if (material !== null) {
        // Vrstni red živi v `pobrisiLokalno` in nikjer drugje. Razpisati
        // koraka tudi tu bi pomenilo isto pravilo na dveh mestih — in
        // drugo mesto bi ostalo brez testa.
        await pobrisiLokalno(db, material, pobrisiDatoteko);
        povzetek.pobrisani += 1;
      }
      potrjeni.push(id);
    } catch {
      // Ta zapis ostane nepotrjen in pride na seznam še enkrat. Obhod se
      // nadaljuje: ena neuspela datoteka ne sme ustaviti ostalih.
      povzetek.neuspeli += 1;
    }
  }

  if (potrjeni.length > 0) {
    await odjemalec.potrdi(potrjeni);
    povzetek.potrjeni = potrjeni.length;
  }

  return povzetek;
}

/** Kar potrebujemo od `fetch`; v testih se podtakne. */
export type Zahteva = (
  url: string,
  moznosti: {
    method: string;
    headers: Record<string, string>;
    body?: string;
    signal: AbortSignal;
  },
) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

/**
 * Klic s časovno omejitvijo, ki se **vedno** konča.
 *
 * Omejitev je izpeljana dvojno, enako kot pri prenosu (`upload.ts`):
 * `signal` prekine sam klic, `Promise.race` pa poskrbi, da se ta funkcija
 * konča tudi, če bi `fetch` signal prezrl. Brez druge polovice bi viseč klic
 * pustil zaporo v `ustvariPonavljalnik` postavljeno in preverjanje arhiva bi
 * bilo do ponovnega zagona aplikacije mrtvo.
 */
async function poslji(
  zahteva: Zahteva,
  url: string,
  moznosti: { method: string; headers: Record<string, string>; body?: string },
  casovnaOmejitevMs: number,
): Promise<{ ok: boolean; status: number; json(): Promise<unknown> }> {
  const nadzor = new AbortController();
  let ura: ReturnType<typeof setTimeout> | undefined;

  const potek = new Promise<never>((_resolve, reject) => {
    ura = setTimeout(() => {
      nadzor.abort();
      reject(new Error('Strežnik se ni odzval pravočasno.'));
    }, casovnaOmejitevMs);
  });

  try {
    return await Promise.race([
      zahteva(url, { ...moznosti, signal: nadzor.signal }),
      potek,
    ]);
  } finally {
    if (ura !== undefined) clearTimeout(ura);
  }
}

/** Ali je odgovor seznam nizov; strežniku ne verjamemo na besedo. */
function seznamNizov(telo: unknown): string[] {
  if (typeof telo !== 'object' || telo === null) return [];
  const ids = (telo as { ids?: unknown }).ids;
  if (!Array.isArray(ids)) return [];
  return ids.filter((id): id is string => typeof id === 'string');
}

/**
 * Odjemalec, ki govori s pravim strežnikom.
 *
 * Neuspešen odgovor vrže — obhod se takrat konča brez brisanja in se ponovi
 * kasneje. Tiho vračanje praznega seznama bi bilo videti kot „ni nič za
 * pobrisati" in bi napako skrilo za vedno.
 */
export function ustvariOdjemalca(
  nastavitve: ServerConfig,
  zahteva: Zahteva = fetch as unknown as Zahteva,
  casovnaOmejitevMs: number = CASOVNA_OMEJITEV_MS,
): Odjemalec {
  const glave = { 'X-API-Key': nastavitve.apiKey, 'Content-Type': 'application/json' };

  return {
    async preberiSeznam() {
      const odgovor = await poslji(
        zahteva,
        `${nastavitve.baseUrl}/materials/pending-deletion`,
        { method: 'GET', headers: glave },
        casovnaOmejitevMs,
      );
      if (!odgovor.ok) {
        throw new Error(`Strežnik je vrnil ${odgovor.status}.`);
      }
      return seznamNizov(await odgovor.json());
    },

    async potrdi(ids) {
      const odgovor = await poslji(
        zahteva,
        `${nastavitve.baseUrl}/materials/deleted-on-device`,
        { method: 'POST', headers: glave, body: JSON.stringify({ ids }) },
        casovnaOmejitevMs,
      );
      if (!odgovor.ok) {
        throw new Error(`Strežnik je vrnil ${odgovor.status}.`);
      }
    },
  };
}

export type Ponavljalnik = {
  zazeni(): void;
  ustavi(): void;
};

export type PonavljalnikOdvisnosti = {
  naloga(): Promise<unknown>;
  intervalMs?: number;
  nastaviCasovnik?: (f: () => void, ms: number) => ReturnType<typeof setTimeout>;
  pocistiCasovnik?: (id: ReturnType<typeof setTimeout>) => void;
};

/**
 * Preprost ponavljalnik s stalnim razmikom.
 *
 * Namenoma **ni** razporejevalnik iz `worker.ts`: tam razmik raste po
 * neuspehih, ker se prenaša čakalna vrsta, in tam obstaja `sprozi()` za takoj
 * po shranjevanju. Tu ni ne vrste ne povoda — brisanje je počasno opravilo, ki
 * se zgodi, ko se zgodi. Dve različni pravili v eni funkciji bi bili dražji od
 * teh nekaj vrstic.
 *
 * Zapora `tece` je bistvena iz istega razloga kot pri prenosu: dva hkratna
 * obhoda bi isti zapis brisala dvakrat.
 */
export function ustvariPonavljalnik(o: PonavljalnikOdvisnosti): Ponavljalnik {
  const intervalMs = o.intervalMs ?? INTERVAL_MS;
  const nastaviCasovnik = o.nastaviCasovnik ?? ((f, ms) => setTimeout(f, ms));
  const pocistiCasovnik = o.pocistiCasovnik ?? ((id) => clearTimeout(id));

  let casovnik: ReturnType<typeof setTimeout> | null = null;
  let tece = false;
  let ustavljen = true;

  async function obhod(): Promise<void> {
    // Tudi `ustavljen`, ne le `tece`: časovnik, ki je že sprožil svojo
    // povratno funkcijo, se s `pocistiCasovnik` ne da več preklicati, in
    // brez te vrstice bi en obhod stekel še potem, ko je aplikacija šla v
    // ozadje.
    if (tece || ustavljen) return;
    tece = true;
    try {
      await o.naloga();
    } catch {
      // Nedosegljiv strežnik ni napaka aplikacije. Poskusimo spet čez razmik.
    } finally {
      tece = false;
    }
    if (!ustavljen) razporedi();
  }

  function razporedi(): void {
    if (casovnik !== null) pocistiCasovnik(casovnik);
    casovnik = nastaviCasovnik(() => {
      void obhod();
    }, intervalMs);
  }

  return {
    zazeni() {
      ustavljen = false;
      void obhod();
    },
    ustavi() {
      ustavljen = true;
      if (casovnik !== null) {
        pocistiCasovnik(casovnik);
        casovnik = null;
      }
    },
  };
}
