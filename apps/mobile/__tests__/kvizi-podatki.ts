import type { KvizStreznika, Poskus } from '@/types';

/**
 * Skupni testni podatki za kvize (V2-R02).
 *
 * Svoja datoteka in ne izvoz iz testne: uvoz iz `*.test.ts` bi v uvozniku
 * pognal še vse teste iz te datoteke.
 */

/** Kviz v obliki, kot ga vrne strežnik; postavke so `<id>-p1`, `<id>-p2` … */
export function kvizStreznika(
  id: string,
  postavk = 3,
  overrides: Partial<KvizStreznika> = {},
): KvizStreznika {
  return {
    id,
    name: `Kviz ${id}`,
    created_at: '2026-09-10T08:00:00+00:00',
    items: Array.from({ length: postavk }, (_, i) => ({
      id: `${id}-p${i + 1}`,
      position: i + 1,
      question: `Vprašanje ${i + 1}?`,
      answer: `Odgovor ${i + 1}.`,
      answered: false,
    })),
    ...overrides,
  };
}

/** Neprenesen poskus za dano postavko kviza; `id` je `<kviz>-a<postavka>`. */
export function poskus(quizId: string, postavka: number, overrides: Partial<Poskus> = {}): Poskus {
  return {
    id: `${quizId}-a${postavka}`,
    quiz_id: quizId,
    quiz_item_id: `${quizId}-p${postavka}`,
    mode: 'samoocena',
    rating: 'srednje',
    shown_at: '2026-09-10T15:00:00.000Z',
    revealed_at: '2026-09-10T15:00:07.000Z',
    answered_at: '2026-09-10T15:00:09.000Z',
    uploaded_at: null,
    user_id: null,
    ...overrides,
  };
}
