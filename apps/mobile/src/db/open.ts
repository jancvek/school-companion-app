import * as SQLite from 'expo-sqlite';

import type { MaterialsDatabase } from './materials';
import { migriraj } from './migrations';

export const DATABASE_NAME = 'school-companion.db';

/**
 * Prevede `SQLiteDatabase` v vmesnik, ki ga uporablja poslovna logika.
 * Če se signature razideta, se to pokaže tu in ne šele na napravi.
 */
export function asMaterialsDatabase(db: SQLite.SQLiteDatabase): MaterialsDatabase {
  return db;
}

/**
 * Priklic ob zagonu aplikacije (`SQLiteProvider onInit`).
 *
 * Tabele ne ustvarja neposredno — to je naloga migracij, ker mora baza iz
 * V1-R01 priti do nove sheme brez izgube posnetkov (ADR-004).
 */
export async function initializeDatabase(db: SQLite.SQLiteDatabase): Promise<void> {
  await migriraj(asMaterialsDatabase(db));
}
