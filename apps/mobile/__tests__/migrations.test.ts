import { migriraj, preberiVerzijo, SHEMA_VERZIJA } from '@/db/migrations';

import { createTestDatabase, SHEMA_V1_R01 } from './test-database';

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

  describe('nad svežo bazo', () => {
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
