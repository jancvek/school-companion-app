import type { Material, SyncPovzetek, SyncStatus } from '../types';

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

/**
 * Shema, kakršno je ustvarila V1-R01.
 *
 * **Ne dopolnjuj je.** Stolpci, ki so prišli pozneje, se dodajajo z
 * migracijami v `src/db/migrations.ts`, sicer bi sveža namestitev dobila
 * drugačno shemo kot nadgrajena — in samo ena od njiju bi bila testirana
 * (ADR-004).
 */
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

const MATERIAL_COLUMNS =
  'id, subject, taken_at, file_uri, sync_status, sync_attempts, last_attempt_at, sync_error';

export async function insertMaterial(
  db: MaterialsDatabase,
  material: Material,
): Promise<void> {
  await db.runAsync(
    `INSERT INTO materials (${MATERIAL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      material.id,
      material.subject,
      material.taken_at,
      material.file_uri,
      material.sync_status,
      material.sync_attempts,
      material.last_attempt_at,
      material.sync_error,
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

/**
 * Zapisi, ki čakajo na prenos — najstarejši prvi.
 *
 * Vrstni red je obraten kot v zgodovini in to je namenoma: zgodovino bereš od
 * najnovejšega, čakalno vrsto pa oddelaš od najstarejšega, sicer bi ob dolgi
 * vrsti najstarejši posnetek čakal najdlje.
 */
export async function listPending(db: MaterialsDatabase): Promise<Material[]> {
  return db.getAllAsync<Material>(
    `SELECT ${MATERIAL_COLUMNS} FROM materials WHERE sync_status = 'pending' ORDER BY taken_at ASC`,
    [],
  );
}

type StevecVrstica = { sync_status: SyncStatus; koliko: number };

/** Koliko zapisov je v katerem stanju prenosa. */
export async function countByStatus(db: MaterialsDatabase): Promise<SyncPovzetek> {
  const vrstice = await db.getAllAsync<StevecVrstica>(
    'SELECT sync_status, COUNT(*) AS koliko FROM materials GROUP BY sync_status',
    [],
  );

  const povzetek: SyncPovzetek = { pending: 0, synced: 0, failed: 0 };
  for (const vrstica of vrstice) {
    if (vrstica.sync_status in povzetek) {
      povzetek[vrstica.sync_status] = vrstica.koliko;
    }
  }
  return povzetek;
}

/** Prenos je uspel: zapis je na strežniku, sled o napaki ni več relevantna. */
export async function markSynced(db: MaterialsDatabase, id: string): Promise<void> {
  await db.runAsync(
    `UPDATE materials
        SET sync_status = 'synced', sync_error = NULL, last_attempt_at = ?
      WHERE id = ?`,
    [new Date().toISOString(), id],
  );
}

/**
 * Poskus ni uspel, a se splača poskusiti znova (omrežje, 5xx, 408, 429).
 * Zapis ostane `pending`.
 */
export async function recordAttempt(
  db: MaterialsDatabase,
  id: string,
  napaka: string,
): Promise<void> {
  await db.runAsync(
    `UPDATE materials
        SET sync_attempts = sync_attempts + 1, last_attempt_at = ?, sync_error = ?
      WHERE id = ?`,
    [new Date().toISOString(), napaka, id],
  );
}

/**
 * Strežnik je zahtevo zavrnil po vsebini (4xx razen 408 in 429). Ponavljanje
 * tega ne bo spremenilo, zato se ustavi in počaka na uporabnico.
 */
export async function markFailed(
  db: MaterialsDatabase,
  id: string,
  napaka: string,
): Promise<void> {
  await db.runAsync(
    `UPDATE materials
        SET sync_status = 'failed',
            sync_attempts = sync_attempts + 1,
            last_attempt_at = ?,
            sync_error = ?
      WHERE id = ?`,
    [new Date().toISOString(), napaka, id],
  );
}

/**
 * Vrne neuspele zapise v vrsto. Kliče se samo na izrecno zahtevo uporabnice —
 * če bi se dogajalo samo od sebe, bi bila razlika med `pending` in `failed`
 * brez pomena (ADR-004).
 */
export async function retryFailed(db: MaterialsDatabase): Promise<void> {
  await db.runAsync(
    `UPDATE materials
        SET sync_status = 'pending', sync_error = NULL, sync_attempts = 0
      WHERE sync_status = 'failed'`,
    [],
  );
}
