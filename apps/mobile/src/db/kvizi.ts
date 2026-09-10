/**
 * Lokalne tabele za kvize (V2-R02): `quizzes`, `quiz_items` in `attempts`.
 *
 * Lokalna baza je **delovni prostor, ne arhiv** (`docs/odlocitve/ADR-019` B):
 * kviz živi na telefonu, dokler ga strežnik vrača, poskus pa, dokler ni
 * prenesen. Stanje kviza se nikjer ne shranjuje — izpelje se iz postavk in
 * poskusov, zato ni stolpca, ki bi se lahko razšel z resnico.
 *
 * Omrežja se ta modul ne dotakne; to je naloga `src/sync/kvizi.ts`.
 */

import type { KvizNaSeznamu, KvizStreznika, Poskus, PostavkaKviza } from '../types';
import type { MaterialsDatabase } from './materials';

/**
 * Shema, kakršno ustvari migracija 2 — **ne dopolnjuj je**, iz istega razloga
 * kot `CREATE_MATERIALS_TABLE_SQL`: telefon, ki je migracijo že prestal, je
 * nikoli več ne požene. Kar pride pozneje, doda nova migracija (ADR-004).
 *
 * `attempts` namenoma **nima tujega ključa** na `quizzes`: kviz se lahko
 * pobriše (preklic na strežniku, `ADR-019` C), preden so njegovi poskusi
 * preneseni, poskus pa ne sme iti z njim.
 *
 * `UNIQUE (quiz_item_id)` je `ADR-019` E tudi lokalno: postavka ima en poskus.
 */
export const CREATE_KVIZI_TABLES_SQL = `
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
`;

/**
 * Shrani kviz s strežnika. Ponovljen klic ne podvoji ničesar.
 *
 * Vsebina je **zamrznjena** (`ADR-016` E), zato se obstoječi kviz ne
 * prepisuje. Posodobi se samo `answered_on_server`, in to samo v smeri 0 → 1:
 * postavka, ki je na strežniku enkrat odgovorjena, to ostane.
 */
export async function shraniKviz(db: MaterialsDatabase, kviz: KvizStreznika): Promise<void> {
  await db.runAsync(
    'INSERT OR IGNORE INTO quizzes (id, name, created_at) VALUES (?, ?, ?)',
    [kviz.id, kviz.name, kviz.created_at],
  );

  for (const postavka of kviz.items) {
    await db.runAsync(
      `INSERT OR IGNORE INTO quiz_items
         (id, quiz_id, position, question_text, answer_text, answered_on_server)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [
        postavka.id,
        kviz.id,
        postavka.position,
        postavka.question,
        postavka.answer,
        postavka.answered ? 1 : 0,
      ],
    );
    if (postavka.answered) {
      await db.runAsync(
        'UPDATE quiz_items SET answered_on_server = 1 WHERE id = ? AND answered_on_server = 0',
        [postavka.id],
      );
    }
  }
}

/**
 * Pobriše lokalne kvize, ki jih strežnik ne vrača več; vrne, koliko jih je šlo.
 *
 * Tak kviz je rešen ali preklican. Z njim gredo postavke in **preneseni**
 * poskusi. Dve izjemi, obe iz `ADR-019` C:
 *
 * - kviz, ki je ta hip odprt (`odprti`), ostane — sicer bi Maši izginil
 *   zaslon pod prsti;
 * - **neprenesen poskus se ne pobriše nikoli**, tudi ko njegovega kviza ni
 *   več. Na strežniku ga čaka sprejem, ne zavrnitev.
 *
 * Tak poskus, ki je medtem prenesen, pa gre ob naslednjem klicu: nobenega
 * kviza več ne dokazuje in lokalna baza je delovni prostor, ne arhiv
 * (`ADR-019` B). Brez tega bi ostal na telefonu za vedno.
 */
export async function pobrisiKvizeRazen(
  db: MaterialsDatabase,
  ohrani: readonly string[],
  odprti: string | null = null,
): Promise<number> {
  const ohranjeni = new Set(ohrani);
  if (odprti !== null) ohranjeni.add(odprti);

  const lokalni = await db.getAllAsync<{ id: string }>('SELECT id FROM quizzes', []);
  const zaBrisanje = lokalni.map((vrstica) => vrstica.id).filter((id) => !ohranjeni.has(id));

  for (const id of zaBrisanje) {
    await db.runAsync('DELETE FROM attempts WHERE quiz_id = ? AND uploaded_at IS NOT NULL', [
      id,
    ]);
    await db.runAsync('DELETE FROM quiz_items WHERE quiz_id = ?', [id]);
    await db.runAsync('DELETE FROM quizzes WHERE id = ?', [id]);
  }

  // Preneseni poskusi kvizov, ki so šli, preden so bili poskusi preneseni.
  // Poskusi kviza, ki je še na telefonu, ostanejo — ti dokazujejo, da je
  // postavka odgovorjena (glej `oznaciPrenesene`).
  await db.runAsync(
    `DELETE FROM attempts
      WHERE uploaded_at IS NOT NULL
        AND quiz_id NOT IN (SELECT id FROM quizzes)`,
    [],
  );

  return zaBrisanje.length;
}

/**
 * Kvizi, ki čakajo na reševanje, najstarejši prvi.
 *
 * Kviz čaka, dokler ima vsaj eno neodgovorjeno postavko. Postavka je
 * odgovorjena, če ima lokalni poskus **ali** je bila odgovorjena že na
 * strežniku (`ADR-019` E). To je edino mesto, kjer to pravilo živi; števec
 * na domači strani in seznam kvizov ga bereta od tu.
 */
export async function cakajociKvizi(db: MaterialsDatabase): Promise<KvizNaSeznamu[]> {
  return db.getAllAsync<KvizNaSeznamu>(
    `SELECT q.id, q.name, q.created_at,
            COUNT(i.id) AS vprasanj,
            SUM(CASE WHEN i.answered_on_server = 1 OR a.id IS NOT NULL THEN 1 ELSE 0 END)
              AS odgovorjenih
       FROM quizzes q
       JOIN quiz_items i ON i.quiz_id = q.id
       LEFT JOIN attempts a ON a.quiz_item_id = i.id
      GROUP BY q.id, q.name, q.created_at
     HAVING odgovorjenih < vprasanj
      ORDER BY q.created_at ASC, q.id ASC`,
    [],
  );
}

type PostavkaVrstica = Omit<PostavkaKviza, 'odgovorjena'> & { odgovorjena: number };

/** En lokalni kviz ali `null`, če ga na telefonu ni. */
export async function najdiKviz(
  db: MaterialsDatabase,
  id: string,
): Promise<{ id: string; name: string } | null> {
  const vrstice = await db.getAllAsync<{ id: string; name: string }>(
    'SELECT id, name FROM quizzes WHERE id = ?',
    [id],
  );
  return vrstice[0] ?? null;
}

/** Postavke kviza po zaporedju, vsaka s podatkom, ali je že odgovorjena. */
export async function postavkeKviza(
  db: MaterialsDatabase,
  quizId: string,
): Promise<PostavkaKviza[]> {
  const vrstice = await db.getAllAsync<PostavkaVrstica>(
    `SELECT i.id, i.quiz_id, i.position, i.question_text, i.answer_text,
            CASE WHEN i.answered_on_server = 1 OR a.id IS NOT NULL THEN 1 ELSE 0 END
              AS odgovorjena
       FROM quiz_items i
       LEFT JOIN attempts a ON a.quiz_item_id = i.id
      WHERE i.quiz_id = ?
      ORDER BY i.position ASC`,
    [quizId],
  );
  return vrstice.map((vrstica) => ({ ...vrstica, odgovorjena: vrstica.odgovorjena === 1 }));
}

/**
 * Zapiše poskus. Drugi poskus za isto postavko se tiho prezre.
 *
 * `INSERT OR IGNORE` na `UNIQUE (quiz_item_id)` je isto pravilo kot na
 * strežniku — prvi zmaga (`ADR-019` E). Nastane lahko ob dvojnem dotiku, ki
 * ga zaslon sicer prestreže.
 */
export async function zapisiPoskus(db: MaterialsDatabase, poskus: Poskus): Promise<void> {
  await db.runAsync(
    `INSERT OR IGNORE INTO attempts
       (id, quiz_id, quiz_item_id, mode, rating, shown_at, revealed_at, answered_at, uploaded_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      poskus.id,
      poskus.quiz_id,
      poskus.quiz_item_id,
      poskus.mode,
      poskus.rating,
      poskus.shown_at,
      poskus.revealed_at,
      poskus.answered_at,
      poskus.uploaded_at,
    ],
  );
}

/** Poskusi, ki še niso na strežniku, po času ocene. */
export async function neprenesenePoskuse(db: MaterialsDatabase): Promise<Poskus[]> {
  return db.getAllAsync<Poskus>(
    `SELECT id, quiz_id, quiz_item_id, mode, rating, shown_at, revealed_at, answered_at,
            uploaded_at
       FROM attempts
      WHERE uploaded_at IS NULL
      ORDER BY answered_at ASC, id ASC`,
    [],
  );
}

/**
 * Označi poskuse kot prenesene.
 *
 * Označi in ne pobriše: poskus je dokaz, da je postavka odgovorjena. Če bi šel
 * takoj, bi med uspešnim prenosom in neuspešnim branjem seznama kviz za hip
 * spet čakal in Maša bi ga reševala znova. Pobriše se skupaj s kvizom.
 */
export async function oznaciPrenesene(
  db: MaterialsDatabase,
  ids: readonly string[],
  kdaj: string,
): Promise<void> {
  for (const id of ids) {
    await db.runAsync('UPDATE attempts SET uploaded_at = ? WHERE id = ? AND uploaded_at IS NULL', [
      kdaj,
      id,
    ]);
  }
}
