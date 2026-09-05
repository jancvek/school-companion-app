import {
  countByStatus,
  insertMaterial,
  listBySubject,
  listPending,
  markFailed,
  markSynced,
  recordAttempt,
  retryFailed,
  type MaterialsDatabase,
} from '@/db/materials';
import { migriraj } from '@/db/migrations';
import type { Material } from '@/types';

import { createTestDatabase } from './test-database';

function material(overrides: Partial<Material> = {}): Material {
  return {
    id: 'id-1',
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: 'file:///documents/photos/id-1.jpg',
    sync_status: 'pending',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
    ...overrides,
  };
}

async function vrstica(db: MaterialsDatabase, id: string): Promise<Material> {
  const [zapis] = await db.getAllAsync<Material>(
    'SELECT * FROM materials WHERE id = ?',
    [id],
  );
  return zapis;
}

describe('tabela materials', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => {
    db.close();
  });

  it('vstavi natanko eno vrstico z danim id', async () => {
    await insertMaterial(db, material());

    const vrstice = await listBySubject(db, 'MAT');

    expect(vrstice).toEqual([material()]);
  });

  it('vrne posnetke od najnovejšega do najstarejšega', async () => {
    await insertMaterial(db, material({ id: 'srednji', taken_at: '2026-09-02T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'najstarejsi', taken_at: '2026-09-01T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'najnovejsi', taken_at: '2026-09-03T08:00:00.000Z' }));

    const vrstice = await listBySubject(db, 'MAT');

    expect(vrstice.map((v) => v.id)).toEqual(['najnovejsi', 'srednji', 'najstarejsi']);
  });

  it('razvršča s poizvedbo, ne z indeksom', async () => {
    // Brez indeksa SQLite bere po rowid, torej po vrstnem redu vstavljanja.
    // Če iz `listBySubject` izgine `ORDER BY taken_at DESC`, ta test pade —
    // prejšnji ne bi, ker ga reši načrt poizvedbe po indeksu.
    await db.execAsync('DROP INDEX materials_subject_taken_at');

    await insertMaterial(db, material({ id: 'srednji', taken_at: '2026-09-02T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'najstarejsi', taken_at: '2026-09-01T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'najnovejsi', taken_at: '2026-09-03T08:00:00.000Z' }));

    const vrstice = await listBySubject(db, 'MAT');

    expect(vrstice.map((v) => v.id)).toEqual(['najnovejsi', 'srednji', 'najstarejsi']);
  });

  it('vrne samo zapise izbranega predmeta', async () => {
    await insertMaterial(db, material({ id: 'mat-1', subject: 'MAT' }));
    await insertMaterial(db, material({ id: 'slj-1', subject: 'SLJ' }));

    const vrstice = await listBySubject(db, 'MAT');

    expect(vrstice.map((v) => v.id)).toEqual(['mat-1']);
    expect(vrstice.every((v) => v.subject === 'MAT')).toBe(true);
  });

  it('vrne prazen seznam za predmet brez posnetkov, brez napake', async () => {
    await expect(listBySubject(db, 'GUM')).resolves.toEqual([]);
  });

  it('ohrani sync_status pending', async () => {
    await insertMaterial(db, material());

    const [vrstica] = await listBySubject(db, 'MAT');

    expect(vrstica.sync_status).toBe('pending');
  });

  it('zavrne drugo vrstico z istim id', async () => {
    await insertMaterial(db, material());

    await expect(insertMaterial(db, material({ subject: 'SLJ' }))).rejects.toThrow();
  });

  it('postavitev sheme je ponovljiva', async () => {
    await insertMaterial(db, material());
    await migriraj(db);

    expect(await listBySubject(db, 'MAT')).toHaveLength(1);
  });
});

describe('čakalna vrsta za prenos', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => {
    db.close();
  });

  it('vrne samo čakajoče, najstarejši prvi', async () => {
    await insertMaterial(db, material({ id: 'nov', taken_at: '2026-09-03T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'star', taken_at: '2026-09-01T08:00:00.000Z' }));
    await insertMaterial(
      db,
      material({ id: 'prenesen', taken_at: '2026-09-02T08:00:00.000Z', sync_status: 'synced' }),
    );
    await insertMaterial(
      db,
      material({ id: 'neuspel', taken_at: '2026-09-02T09:00:00.000Z', sync_status: 'failed' }),
    );

    const cakajoci = await listPending(db);

    // Zgodovina se bere od najnovejšega, vrsta pa oddela od najstarejšega —
    // sicer bi najstarejši posnetek čakal najdlje.
    expect(cakajoci.map((v) => v.id)).toEqual(['star', 'nov']);
  });

  it('razvršča vrsto s poizvedbo, ne po vrstnem redu vstavljanja', async () => {
    await db.execAsync('DROP INDEX materials_subject_taken_at');
    await insertMaterial(db, material({ id: 'nov', taken_at: '2026-09-03T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'star', taken_at: '2026-09-01T08:00:00.000Z' }));

    expect((await listPending(db)).map((v) => v.id)).toEqual(['star', 'nov']);
  });

  it('prešteje zapise po stanjih', async () => {
    await insertMaterial(db, material({ id: 'a' }));
    await insertMaterial(db, material({ id: 'b' }));
    await insertMaterial(db, material({ id: 'c', sync_status: 'synced' }));
    await insertMaterial(db, material({ id: 'd', sync_status: 'failed' }));

    expect(await countByStatus(db)).toEqual({ pending: 2, synced: 1, failed: 1 });
  });

  it('prazna baza da same ničle', async () => {
    expect(await countByStatus(db)).toEqual({ pending: 0, synced: 0, failed: 0 });
  });

  it('markSynced postavi synced in počisti napako', async () => {
    await insertMaterial(db, material({ sync_error: 'prej je šlo narobe' }));

    await markSynced(db, 'id-1');

    const zapis = await vrstica(db, 'id-1');
    expect(zapis.sync_status).toBe('synced');
    expect(zapis.sync_error).toBeNull();
    expect(zapis.last_attempt_at).not.toBeNull();
  });

  it('recordAttempt pusti pending in šteje poskuse', async () => {
    await insertMaterial(db, material());

    await recordAttempt(db, 'id-1', 'strežnik ni dosegljiv');
    await recordAttempt(db, 'id-1', 'strežnik ni dosegljiv');

    const zapis = await vrstica(db, 'id-1');
    expect(zapis.sync_status).toBe('pending');
    expect(zapis.sync_attempts).toBe(2);
    expect(zapis.sync_error).toBe('strežnik ni dosegljiv');
  });

  it('markFailed postavi failed in zapiše razlog', async () => {
    await insertMaterial(db, material());

    await markFailed(db, 'id-1', 'strežnik je zavrnil ključ');

    const zapis = await vrstica(db, 'id-1');
    expect(zapis.sync_status).toBe('failed');
    expect(zapis.sync_error).toBe('strežnik je zavrnil ključ');
    expect(await listPending(db)).toEqual([]);
  });

  it('retryFailed vrne neuspele v vrsto in počisti napako', async () => {
    await insertMaterial(
      db,
      material({ id: 'neuspel', sync_status: 'failed', sync_error: 'ključ' }),
    );
    await insertMaterial(db, material({ id: 'prenesen', sync_status: 'synced' }));

    await retryFailed(db);

    expect((await listPending(db)).map((v) => v.id)).toEqual(['neuspel']);
    expect((await vrstica(db, 'neuspel')).sync_error).toBeNull();
    // Preneseni se ne smejo prenašati znova.
    expect((await vrstica(db, 'prenesen')).sync_status).toBe('synced');
  });
});
