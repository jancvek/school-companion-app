import { DatabaseSync } from 'node:sqlite';

import type { MaterialsDatabase, SqlValue } from '@/db/materials';

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
