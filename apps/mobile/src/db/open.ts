import * as SQLite from 'expo-sqlite';

import { createMaterialsTable, type MaterialsDatabase } from './materials';

export const DATABASE_NAME = 'school-companion.db';

/**
 * Prevede `SQLiteDatabase` v vmesnik, ki ga uporablja poslovna logika.
 * Če se signature razideta, se to pokaže tu in ne šele na napravi.
 */
export function asMaterialsDatabase(db: SQLite.SQLiteDatabase): MaterialsDatabase {
  return db;
}

/** Priklic ob zagonu aplikacije (`SQLiteProvider onInit`). */
export async function initializeDatabase(db: SQLite.SQLiteDatabase): Promise<void> {
  await createMaterialsTable(asMaterialsDatabase(db));
}
