/**
 * Katera gradnja aplikacije teče na tem telefonu.
 *
 * Brez tega izpisa dveh APK z isto verzijo ni bilo mogoče ločiti: `versionCode`
 * je bil pri obeh 1, v Nastavitvah je pri obeh pisalo `1.0.0`, edini
 * razpoložljivi test pa je bil posreden („ali prenos deluje"). Povod je
 * popravek V1-R02. `versionCode` odtlej šteje EAS sam (`eas.json`,
 * `autoIncrement`); ta vrstica ostaja tisto, kar je vidno brez brskanja po
 * Nastavitvah.
 *
 * Oznaka gradnje pride iz EAS ob gradnji (`EAS_BUILD_ID` → `extra.buildId` v
 * `app.config.ts`). Razvojna gradnja je nima in to tudi pove — prazna vrstica
 * ali `null` na zaslonu bi bila slabša od poštenega „razvojna gradnja".
 */

import Constants from 'expo-constants';

/** Toliko znakov identifikatorja gradnje pokažemo. */
export const DOLZINA_OZNAKE = 8;

const NEZNANA_VERZIJA = 'neznana različica';
const RAZVOJNA = 'razvojna gradnja';

/** Neprazen niz ali `null`; presledki se ne štejejo za vrednost. */
function niz(vrednost: unknown): string | null {
  if (typeof vrednost !== 'string') return null;
  const obrezan = vrednost.trim();
  return obrezan.length > 0 ? obrezan : null;
}

/**
 * Kar potrebujemo od `expoConfig`. Lasten tip zato, da testi podajo predmet
 * neposredno in jim ni treba posnemati celotnega `expo-constants`.
 */
export type VerzijskiVir = {
  version?: string | null;
  extra?: Record<string, unknown> | null;
} | null;

/**
 * Besedilo za izpis, npr. `1.0.0 · gradnja 317bdcd1`.
 *
 * **Vedno vrne neprazen niz.** Zaslon ga izriše brez pogojev, zato tu ni
 * primera, v katerem bi uporabnica videla `null` ali prazno vrstico.
 */
export function opisVerzije(vir: VerzijskiVir = Constants.expoConfig): string {
  const verzija = niz(vir?.version) ?? NEZNANA_VERZIJA;
  const gradnja = niz(vir?.extra?.buildId);

  if (gradnja === null) return `${verzija} · ${RAZVOJNA}`;

  return `${verzija} · gradnja ${gradnja.slice(0, DOLZINA_OZNAKE)}`;
}
