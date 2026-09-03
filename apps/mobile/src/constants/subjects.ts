export type Subject = {
  /** Koda predmeta. Ta vrednost gre v stolpec `materials.subject`. */
  value: string;
  /** Celotno besedilo za vmesnik. */
  label: string;
};

/**
 * Predmeti so trdo zapisani in v tem vrstnem redu — tak je Mašin urnik.
 * Vrstni red ni abecedni in se ne preurejaj.
 */
export const SUBJECTS: readonly Subject[] = [
  { value: 'NAR', label: 'NAR — Naravoslovje' },
  { value: 'MAT', label: 'MAT — Matematika' },
  { value: 'TJA', label: 'TJA — Angleščina' },
  { value: 'GEO', label: 'GEO — Geografija' },
  { value: 'SLJ', label: 'SLJ — Slovenščina' },
  { value: 'LUM', label: 'LUM — Likovna umetnost' },
  { value: 'ZGO', label: 'ZGO — Zgodovina' },
  { value: 'TIT', label: 'TIT — Tehnika in tehnologija' },
  { value: 'DKE', label: 'DKE — Domovinska in državljanska kultura ter etika' },
  { value: 'GUM', label: 'GUM — Glasbena umetnost' },
];

/** Vrne predmet z dano kodo ali `undefined`, če koda ni znana. */
export function findSubject(value: string | undefined): Subject | undefined {
  return SUBJECTS.find((subject) => subject.value === value);
}
