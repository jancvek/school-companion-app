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
 */
export const SHEMA_VERZIJE_1 = `${SHEMA_V1_R01}
ALTER TABLE materials ADD COLUMN sync_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE materials ADD COLUMN last_attempt_at TEXT;
ALTER TABLE materials ADD COLUMN sync_error TEXT;
PRAGMA user_version = 1;
`;

/**
 * Baza, kakršna je na telefonu po migraciji 2 (V2-R02 do V3-R03) — spet
 * **dobesedna kopija, ki se ne posodablja**.
 *
 * To je stanje, v katerem je Mašin telefon danes: migracija 3 (V3-R04) mora
 * iti čezenj brez izgube posnetkov in brez izgube neprenesenih poskusov.
 */
export const SHEMA_VERZIJE_2 = `${SHEMA_VERZIJE_1}
CREATE TABLE IF NOT EXISTS quizzes (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_items (
  id TEXT PRIMARY KEY NOT NULL,
  quiz_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  question_text TEXT NOT NULL,
  answer_text TEXT NOT NULL,
  answered_on_server INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS quiz_items_quiz_id_position
  ON quiz_items (quiz_id, position);
CREATE TABLE IF NOT EXISTS attempts (
  id TEXT PRIMARY KEY NOT NULL,
  quiz_id TEXT NOT NULL,
  quiz_item_id TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL,
  rating TEXT NOT NULL,
  shown_at TEXT NOT NULL,
  revealed_at TEXT NOT NULL,
  answered_at TEXT NOT NULL,
  uploaded_at TEXT
);
PRAGMA user_version = 2;
`;

/**
 * Baza, kakršna je na telefonu po migraciji 3 (V3-R04, prvi del) — spet
 * **dobesedna kopija, ki se ne posodablja**.
 *
 * Migracija 4 mora čezenj brez izgube posnetkov, poskusov in lastnikov.
 */
export const SHEMA_VERZIJE_3 = `${SHEMA_VERZIJE_2}
ALTER TABLE materials ADD COLUMN user_id TEXT;
ALTER TABLE attempts ADD COLUMN user_id TEXT;
CREATE INDEX IF NOT EXISTS materials_user_id ON materials (user_id);
CREATE INDEX IF NOT EXISTS attempts_user_id ON attempts (user_id);
PRAGMA user_version = 3;
`;

/**
 * Baza, kakršna je na telefonu po migraciji 4 (V3-R04, drugi del) — spet
 * **dobesedna kopija, ki se ne posodablja** (`docs/odlocitve/ADR-004`).
 *
 * To je stanje Mašinega telefona pred `V3-R07`: kvizi so tu, lastnika pa
 * nimajo. Migracija 5 mora čezenj brez izgube kvizov, postavk in poskusov.
 */
export const SHEMA_VERZIJE_4 = `${SHEMA_VERZIJE_3}
CREATE TABLE IF NOT EXISTS naprava (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  odjava_ob TEXT
);
PRAGMA user_version = 4;
`;
