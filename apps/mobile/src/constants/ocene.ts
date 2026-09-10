import type { Ocena } from '../types';

/**
 * Gumbi samoocene, v vrstnem redu od najtežje navzdol (`ADR-014`).
 *
 * Ženska oblika, ker je uporabnica ena. Oblika `{ value, label }` po vzoru
 * seznama predmetov: koda gre v bazo in na strežnik, oznaka na zaslon.
 */
export const OCENE: readonly { value: Ocena; label: string }[] = [
  { value: 'nisem_vedela', label: 'Nisem vedela' },
  { value: 'tezko', label: 'Težko' },
  { value: 'srednje', label: 'Srednje' },
  { value: 'lahko', label: 'Lahko' },
];
