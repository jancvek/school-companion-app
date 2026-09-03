import type { Material } from '../types';

export type SqlValue = string | number | null;

/**
 * Tanek vmesnik nad bazo. Poslovna logika govori s tem tipom, ne z
 * `expo-sqlite` — tako je testljiva brez naprave, `expo-sqlite` pa se poveže
 * samo na robu aplikacije (`src/db/open.ts`).
 */
export type MaterialsDatabase = {
  execAsync(source: string): Promise<void>;
  runAsync(source: string, params: SqlValue[]): Promise<unknown>;
  getAllAsync<T>(source: string, params: SqlValue[]): Promise<T[]>;
};

export const CREATE_MATERIALS_TABLE_SQL = `
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

const MATERIAL_COLUMNS = 'id, subject, taken_at, file_uri, sync_status';

export async function createMaterialsTable(db: MaterialsDatabase): Promise<void> {
  await db.execAsync(CREATE_MATERIALS_TABLE_SQL);
}

export async function insertMaterial(
  db: MaterialsDatabase,
  material: Material,
): Promise<void> {
  await db.runAsync(
    `INSERT INTO materials (${MATERIAL_COLUMNS}) VALUES (?, ?, ?, ?, ?)`,
    [
      material.id,
      material.subject,
      material.taken_at,
      material.file_uri,
      material.sync_status,
    ],
  );
}

/** Posnetki enega predmeta, od najnovejšega navzdol. */
export async function listBySubject(
  db: MaterialsDatabase,
  subject: string,
): Promise<Material[]> {
  return db.getAllAsync<Material>(
    `SELECT ${MATERIAL_COLUMNS} FROM materials WHERE subject = ? ORDER BY taken_at DESC`,
    [subject],
  );
}
