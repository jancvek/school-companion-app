import {
  createMaterialsTable,
  insertMaterial,
  listBySubject,
  type MaterialsDatabase,
} from '@/db/materials';
import type { Material } from '@/types';

import { createTestDatabase } from './test-database';

function material(overrides: Partial<Material> = {}): Material {
  return {
    id: 'id-1',
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: 'file:///documents/photos/id-1.jpg',
    sync_status: 'pending',
    ...overrides,
  };
}

describe('tabela materials', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await createMaterialsTable(db);
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

  it('ustvarjanje tabele je ponovljivo', async () => {
    await insertMaterial(db, material());
    await createMaterialsTable(db);

    expect(await listBySubject(db, 'MAT')).toHaveLength(1);
  });
});
