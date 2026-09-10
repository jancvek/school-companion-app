import { DatabaseSync } from 'node:sqlite';

import type { MaterialsDatabase, SqlValue } from '@/db/materials';
import { migriraj } from '@/db/migrations';

/**
 * Prava SQLite baza v pomnilniku, priklopljena na isti vmesnik kot
 * `expo-sqlite`. Tako testi preverjajo dejanski SQL (vključno z
 * `ORDER BY taken_at DESC`), ne pa posnemanja SQL-a v JavaScriptu.
 *
 * `node:sqlite` je del Node.js in ni nova odvisnost projekta.
 */
export function createTestDatabase(): MaterialsDatabase & { close(): void } {
  const db = new DatabaseSync(':memory:');

  return {
    async execAsync(source: string) {
      db.exec(source);
    },
    async runAsync(source: string, params: SqlValue[]) {
      return db.prepare(source).run(...params);
    },
    async getAllAsync<T>(source: string, params: SqlValue[]) {
      return db.prepare(source).all(...params) as T[];
    },
    close() {
      db.close();
    },
  };
}

/** Baza, migrirana na trenutno shemo — izhodišče za večino testov. */
export async function createMigratedDatabase(): Promise<
  MaterialsDatabase & { close(): void }
> {
  const db = createTestDatabase();
  await migriraj(db);
  return db;
}

/**
 * Shema, kakršno je na telefonu pustila V1-R01 — **dobesedna kopija, ki se ne
 * posodablja.**
 *
 * Namenoma se ne uvozi iz `src/`: tam se sme spremeniti, tu pa mora ostati
 * to, kar je na napravah dejansko zapisano. Če bi jo test bral iz kode, bi se
 * migracija preverjala nad shemo, ki jo ta ista migracija ustvari — in bi bila
 * zelena, tudi če na pravem telefonu ne bi delovala.
 */
export const SHEMA_V1_R01 = `
CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY NOT NULL,
  subject TEXT NOT NULL,
  taken_at TEXT NOT NULL,
  file_uri TEXT NOT NULL,
  sync_status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS materials_subject_taken_at
  ON materials (subject, taken_at DESC);
`;

/**
 * Baza, kakršna je na telefonu po migraciji 1 (V1-R02 do V2-R01) — **dobesedna
 * kopija, ki se ne posodablja**, iz istega razloga kot `SHEMA_V1_R01`.
 *
 * To je stanje, v katerem je Mašin telefon danes: migracija 2 (V2-R02) mora
 * iti čezenj brez izgube posnetkov.
 */
export const SHEMA_VERZIJE_1 = `${SHEMA_V1_R01}
ALTER TABLE materials ADD COLUMN sync_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE materials ADD COLUMN last_attempt_at TEXT;
ALTER TABLE materials ADD COLUMN sync_error TEXT;
PRAGMA user_version = 1;
`;
