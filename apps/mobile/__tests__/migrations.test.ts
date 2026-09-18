import { migriraj, preberiVerzijo, SHEMA_VERZIJA } from '@/db/migrations';

import {
  createTestDatabase,
  SHEMA_V1_R01,
  SHEMA_VERZIJE_1,
  SHEMA_VERZIJE_2,
} from './test-database';

/** Tabele, ki jih prinese migracija 2 (V2-R02). */
const TABELE_KVIZOV = ['quizzes', 'quiz_items', 'attempts'];

async function imenaTabel(db: ReturnType<typeof createTestDatabase>): Promise<string[]> {
  const vrstice = await db.getAllAsync<{ name: string }>(
    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
    [],
  );
  return vrstice.map((vrstica) => vrstica.name);
}

async function stolpciTabele(
  db: ReturnType<typeof createTestDatabase>,
  tabela: string,
): Promise<string[]> {
  const vrstice = await db.getAllAsync<{ name: string }>(`PRAGMA table_info(${tabela})`, []);
  return vrstice.map((vrstica) => vrstica.name);
}

/**
 * Migracija je edina stvar v tej zahtevi, ki jo je mogoče pokvariti tako, da
 * so testi zeleni, naprava pa ne dela. Zato ti testi ne gredo samo nad svežo
 * bazo — glavni gre nad bazo, **zgrajeno po shemi V1-R01**, z vrsticami
 * notri. To je stanje na telefonu (ADR-004).
 */

type StolpecVrstica = { name: string };

async function imenaStolpcev(
  db: ReturnType<typeof createTestDatabase>,
): Promise<string[]> {
  const vrstice = await db.getAllAsync<StolpecVrstica>('PRAGMA table_info(materials)', []);
  return vrstice.map((vrstica) => vrstica.name);
}

/** Stavki, ki jih `migriraj` izvede nad to bazo. */
async function opazujIzvedene(
  db: ReturnType<typeof createTestDatabase>,
): Promise<string[]> {
  const izvedeni: string[] = [];
  await migriraj({
    ...db,
    execAsync: async (sql: string) => {
      izvedeni.push(sql);
      await db.execAsync(sql);
    },
  });
  return izvedeni;
}

describe('migracija lokalne sheme', () => {
  describe('nad bazo iz V1-R01', () => {
    it('ohrani obstoječe vrstice in doda nove stolpce', async () => {
      const db = createTestDatabase();
      try {
        // Natanko tako, kot je bazo pustila V1-R01: stara shema, brez
        // zapisane verzije, z dvema posnetkoma.
        await db.execAsync(SHEMA_V1_R01);
        await db.runAsync(
          'INSERT INTO materials (id, subject, taken_at, file_uri, sync_status) VALUES (?, ?, ?, ?, ?)',
          ['a', 'MAT', '2026-09-01T08:00:00.000Z', 'file:///a.jpg', 'pending'],
        );
        await db.runAsync(
          'INSERT INTO materials (id, subject, taken_at, file_uri, sync_status) VALUES (?, ?, ?, ?, ?)',
          ['b', 'SLJ', '2026-09-02T08:00:00.000Z', 'file:///b.jpg', 'pending'],
        );
        expect(await preberiVerzijo(db)).toBe(0);

        await migriraj(db);

        const vrstice = await db.getAllAsync<{
          id: string;
          file_uri: string;
          sync_attempts: number;
          last_attempt_at: string | null;
          sync_error: string | null;
        }>('SELECT id, file_uri, sync_attempts, last_attempt_at, sync_error FROM materials ORDER BY id', []);

        expect(vrstice).toEqual([
          {
            id: 'a',
            file_uri: 'file:///a.jpg',
            sync_attempts: 0,
            last_attempt_at: null,
            sync_error: null,
          },
          {
            id: 'b',
            file_uri: 'file:///b.jpg',
            sync_attempts: 0,
            last_attempt_at: null,
            sync_error: null,
          },
        ]);
        expect(await preberiVerzijo(db)).toBe(SHEMA_VERZIJA);
      } finally {
        db.close();
      }
    });

    it('ne izgubi posnetkov, tudi če je vrstic več', async () => {
      const db = createTestDatabase();
      try {
        await db.execAsync(SHEMA_V1_R01);
        for (let i = 0; i < 25; i += 1) {
          await db.runAsync(
            'INSERT INTO materials (id, subject, taken_at, file_uri, sync_status) VALUES (?, ?, ?, ?, ?)',
            [`id-${i}`, 'MAT', `2026-09-01T08:00:0${i % 10}.000Z`, `file:///${i}.jpg`, 'pending'],
          );
        }

        await migriraj(db);

        const [{ koliko }] = await db.getAllAsync<{ koliko: number }>(
          'SELECT COUNT(*) AS koliko FROM materials',
          [],
        );
        expect(koliko).toBe(25);
      } finally {
        db.close();
      }
    });
  });

  describe('nad bazo verzije 1 (stanje pred V2-R02)', () => {
    it('ohrani posnetke in doda tabele za kvize', async () => {
      // To je Mašin telefon danes. Test nad svežo bazo tu ne dokazuje ničesar
      // (ADR-004): migracija 1 je tam že bila in migracija 2 teče nad
      // vrsticami, ki jih je pustila.
      const db = createTestDatabase();
      try {
        await db.execAsync(SHEMA_VERZIJE_1);
        await db.runAsync(
          `INSERT INTO materials (id, subject, taken_at, file_uri, sync_status, sync_attempts, last_attempt_at, sync_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
          ['a', 'MAT', '2026-09-01T08:00:00.000Z', 'file:///a.jpg', 'failed', 3, '2026-09-02T08:00:00.000Z', 'Strežnik je zahtevo zavrnil (413).'],
        );
        await db.runAsync(
          `INSERT INTO materials (id, subject, taken_at, file_uri, sync_status, sync_attempts, last_attempt_at, sync_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
          ['b', 'SLJ', '2026-09-03T08:00:00.000Z', 'file:///b.jpg', 'synced', 0, null, null],
        );
        expect(await preberiVerzijo(db)).toBe(1);

        await migriraj(db);

        expect(await preberiVerzijo(db)).toBe(SHEMA_VERZIJA);
        const vrstice = await db.getAllAsync<Record<string, unknown>>(
          'SELECT * FROM materials ORDER BY id',
          [],
        );
        expect(vrstice).toEqual([
          {
            id: 'a',
            subject: 'MAT',
            taken_at: '2026-09-01T08:00:00.000Z',
            file_uri: 'file:///a.jpg',
            sync_status: 'failed',
            sync_attempts: 3,
            last_attempt_at: '2026-09-02T08:00:00.000Z',
            sync_error: 'Strežnik je zahtevo zavrnil (413).',
            // Migracija 3: zapis iz časa pred prijavo nima lastnika in ga
            // dobi šele s prvo prijavo (ADR-036 B).
            user_id: null,
          },
          {
            id: 'b',
            subject: 'SLJ',
            taken_at: '2026-09-03T08:00:00.000Z',
            file_uri: 'file:///b.jpg',
            sync_status: 'synced',
            sync_attempts: 0,
            last_attempt_at: null,
            sync_error: null,
            user_id: null,
          },
        ]);
        const tabele = await imenaTabel(db);
        for (const tabela of TABELE_KVIZOV) expect(tabele).toContain(tabela);
      } finally {
        db.close();
      }
    });

    it('migracije 1 ne požene znova', async () => {
      // Stare migracije se ne ponavljajo: telefon, ki je bil na verziji 1,
      // gre samo skozi koraka 2 in 3.
      const db = createTestDatabase();
      try {
        await db.execAsync(SHEMA_VERZIJE_1);

        const izvedeni = await opazujIzvedene(db);

        // Stolpci migracije 1 se ne dodajajo znova; `user_id` iz migracije 3
        // pa se doda, in prav zato se ALTER tu ne sme iskati kar po ključni
        // besedi.
        expect(izvedeni.some((sql) => sql.includes('ADD COLUMN sync_attempts'))).toBe(false);
        expect(izvedeni.some((sql) => sql.includes('CREATE TABLE IF NOT EXISTS quizzes'))).toBe(
          true,
        );
        expect(izvedeni.some((sql) => sql.includes('ADD COLUMN user_id'))).toBe(true);
      } finally {
        db.close();
      }
    });
  });

  describe('nad bazo verzije 2 (stanje pred V3-R04)', () => {
    /** Vrstice, kakršne so na Mašinem telefonu pred nadgradnjo. */
    async function napolni(db: ReturnType<typeof createTestDatabase>): Promise<void> {
      await db.execAsync(SHEMA_VERZIJE_2);
      await db.runAsync(
        'INSERT INTO materials (id, subject, taken_at, file_uri, sync_status, sync_attempts)' +
          ' VALUES (?, ?, ?, ?, ?, ?)',
        ['a', 'MAT', '2026-09-01T08:00:00.000Z', 'file:///a.jpg', 'pending', 1],
      );
      await db.runAsync('INSERT INTO quizzes (id, name, created_at) VALUES (?, ?, ?)', [
        'k1',
        'MAT',
        '2026-09-10T08:00:00.000Z',
      ]);
      await db.runAsync(
        'INSERT INTO attempts (id, quiz_id, quiz_item_id, mode, rating, shown_at,' +
          ' revealed_at, answered_at, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
          'p1',
          'k1',
          'k1-i1',
          'samoocena',
          'tezko',
          '2026-09-10T15:00:00.000Z',
          '2026-09-10T15:00:07.000Z',
          '2026-09-10T15:00:09.000Z',
          null,
        ],
      );
    }

    it('doda lastnika obema tabelama in ne izgubi vrstic', async () => {
      // To je Mašin telefon danes. Neprenesen poskus je tu namenoma: prav ta
      // se v V3-R04 ne sme izgubiti in ne sme oditi pod tujim žetonom.
      const db = createTestDatabase();
      try {
        await napolni(db);
        expect(await preberiVerzijo(db)).toBe(2);

        await migriraj(db);

        expect(await preberiVerzijo(db)).toBe(SHEMA_VERZIJA);
        expect(await imenaStolpcev(db)).toContain('user_id');
        expect(await stolpciTabele(db, 'attempts')).toContain('user_id');

        const snov = await db.getAllAsync<Record<string, unknown>>(
          'SELECT id, sync_status, sync_attempts, user_id FROM materials',
          [],
        );
        expect(snov).toEqual([
          { id: 'a', sync_status: 'pending', sync_attempts: 1, user_id: null },
        ]);

        const poskusi = await db.getAllAsync<Record<string, unknown>>(
          'SELECT id, quiz_item_id, rating, uploaded_at, user_id FROM attempts',
          [],
        );
        expect(poskusi).toEqual([
          { id: 'p1', quiz_item_id: 'k1-i1', rating: 'tezko', uploaded_at: null, user_id: null },
        ]);
      } finally {
        db.close();
      }
    });

    it('migracij 1 in 2 ne požene znova', async () => {
      const db = createTestDatabase();
      try {
        await napolni(db);

        const izvedeni = await opazujIzvedene(db);

        expect(izvedeni.some((sql) => sql.includes('ADD COLUMN sync_attempts'))).toBe(false);
        expect(izvedeni.some((sql) => sql.includes('CREATE TABLE IF NOT EXISTS quizzes'))).toBe(
          false,
        );
        expect(izvedeni.some((sql) => sql.includes('ADD COLUMN user_id'))).toBe(true);
      } finally {
        db.close();
      }
    });

    it('drugi zagon ne doda stolpca še enkrat', async () => {
      // Korak mora biti ponovljiv: aplikacija se lahko ubije med `ALTER` in
      // zapisom `user_version`, `ADD COLUMN` na obstoječem stolpcu pa vrže.
      const db = createTestDatabase();
      try {
        await napolni(db);
        await migriraj(db);

        await expect(migriraj(db)).resolves.toBe(SHEMA_VERZIJA);
      } finally {
        db.close();
      }
    });
  });

  describe('nad svežo bazo', () => {
    it('ima tudi tabele za kvize, enake kot nadgrajena', async () => {
      const sveza = createTestDatabase();
      const nadgrajena = createTestDatabase();
      try {
        await migriraj(sveza);
        await nadgrajena.execAsync(SHEMA_VERZIJE_2);
        await migriraj(nadgrajena);

        expect(await imenaTabel(sveza)).toEqual(await imenaTabel(nadgrajena));
        for (const tabela of TABELE_KVIZOV) {
          expect(await stolpciTabele(sveza, tabela)).toEqual(
            await stolpciTabele(nadgrajena, tabela),
          );
        }
      } finally {
        sveza.close();
        nadgrajena.close();
      }
    });

    it('ustvari isto shemo kot nadgradnja', async () => {
      const sveza = createTestDatabase();
      const nadgrajena = createTestDatabase();
      try {
        await migriraj(sveza);

        await nadgrajena.execAsync(SHEMA_V1_R01);
        await migriraj(nadgrajena);

        // Dve poti do dveh različnih shem bi pomenili, da je testirana samo
        // ena od njiju (ADR-004).
        expect(await imenaStolpcev(sveza)).toEqual(await imenaStolpcev(nadgrajena));
        expect(await preberiVerzijo(sveza)).toBe(SHEMA_VERZIJA);
      } finally {
        sveza.close();
        nadgrajena.close();
      }
    });

    it('ima vse stolpce, ki jih potrebuje prenos', async () => {
      const db = createTestDatabase();
      try {
        await migriraj(db);

        expect(await imenaStolpcev(db)).toEqual([
          'id',
          'subject',
          'taken_at',
          'file_uri',
          'sync_status',
          'sync_attempts',
          'last_attempt_at',
          'sync_error',
          'user_id',
        ]);
      } finally {
        db.close();
      }
    });
  });

  it('je idempotentna — drugi zagon ne naredi nič in ne vrže napake', async () => {
    const db = createTestDatabase();
    try {
      await migriraj(db);
      await db.runAsync(
        `INSERT INTO materials (id, subject, taken_at, file_uri, sync_status, sync_attempts, last_attempt_at, sync_error)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        ['a', 'MAT', '2026-09-01T08:00:00.000Z', 'file:///a.jpg', 'synced', 2, null, null],
      );

      await expect(migriraj(db)).resolves.toBe(SHEMA_VERZIJA);

      const vrstice = await db.getAllAsync<{ id: string; sync_attempts: number }>(
        'SELECT id, sync_attempts FROM materials',
        [],
      );
      expect(vrstice).toEqual([{ id: 'a', sync_attempts: 2 }]);
    } finally {
      db.close();
    }
  });

  it('ohrani indeks iz V1-R01', async () => {
    const db = createTestDatabase();
    try {
      await migriraj(db);

      const indeksi = await db.getAllAsync<{ name: string }>(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'materials'",
        [],
      );
      expect(indeksi.map((i) => i.name)).toContain('materials_subject_taken_at');
    } finally {
      db.close();
    }
  });
});
