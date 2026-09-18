import { KLJUC_SEJE, type Seja, type VarnaShramba } from '@/sync/prijava';

/**
 * Varna shramba v pomnilniku (V3-R04).
 *
 * Svoja datoteka in ne izvoz iz testne, po istem pravilu kot `kvizi-podatki.ts`:
 * uvoz iz `*.test.ts` bi v uvozniku pognal še vse teste iz te datoteke.
 *
 * `expo-secure-store` se v testih ne uporablja — nativnega modula tam ni. Ta
 * dvojnik pokriva vse, kar aplikacija od shrambe potrebuje, in dodatno zna
 * **odpovedati**, ker je odpoved shrambe stanje, ki ga mora aplikacija
 * prenesti (`docs/odlocitve/ADR-036` A).
 */
export type TestnaShramba = VarnaShramba & {
  /** Kar je ta hip zapisano; `undefined`, kadar ni ničesar. */
  vsebina(): string | undefined;
  /** Od zdaj naprej vsak dostop vrže. */
  pokvari(): void;
};

/** Seja, s katero se v testih izkaže telefon. */
export const SEJA: Seja = { zeton: 'zeton-za-teste', userId: 'u-masa', ime: 'Maša' };

export function ustvariShrambo(zacetna: Seja | null = null): TestnaShramba {
  const zapisi = new Map<string, string>();
  if (zacetna !== null) zapisi.set(KLJUC_SEJE, JSON.stringify(zacetna));
  let pokvarjena = false;

  function preveri(): void {
    if (pokvarjena) throw new Error('Varna shramba ni dosegljiva.');
  }

  return {
    vsebina: () => zapisi.get(KLJUC_SEJE),
    pokvari: () => {
      pokvarjena = true;
    },
    getItemAsync: async (kljuc) => {
      preveri();
      return zapisi.get(kljuc) ?? null;
    },
    setItemAsync: async (kljuc, vrednost) => {
      preveri();
      zapisi.set(kljuc, vrednost);
    },
    deleteItemAsync: async (kljuc) => {
      preveri();
      zapisi.delete(kljuc);
    },
  };
}
