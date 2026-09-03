import { randomUUID } from 'node:crypto';

import { createMaterialsTable, listBySubject, type MaterialsDatabase } from '@/db/materials';
import { saveCapture } from '@/materials/save';

import { createTestDatabase } from './test-database';

jest.mock('expo-crypto', () => ({
  __esModule: true,
  randomUUID: jest.fn(),
}));

jest.mock('@/photos/store', () => ({
  __esModule: true,
  savePhoto: jest.fn(),
}));

const crypto = jest.requireMock('expo-crypto') as { randomUUID: jest.Mock };
const store = jest.requireMock('@/photos/store') as { savePhoto: jest.Mock };

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

const CAS_POSNETKA = '2026-09-03T14:32:10.000Z';
const IZVIRNIK = 'file:///cache/Camera/original.jpg';

describe('shranjevanje posnetka', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    jest.clearAllMocks();
    crypto.randomUUID.mockImplementation(() => randomUUID());
    store.savePhoto.mockImplementation(async (_source: string, ime: string) =>
      `file:///documents/photos/${ime}`,
    );

    db = createTestDatabase();
    await createMaterialsTable(db);
  });

  afterEach(() => {
    db.close();
  });

  it('sestavi zapis z UUID-jem, časom posnetka in stanjem pending', async () => {
    const zapis = await saveCapture(db, {
      subject: 'MAT',
      takenAt: CAS_POSNETKA,
      sourceUri: IZVIRNIK,
    });

    expect(zapis.id).toMatch(UUID_V4);
    expect(zapis.subject).toBe('MAT');
    expect(zapis.taken_at).toBe(CAS_POSNETKA);
    expect(zapis.taken_at).toMatch(ISO_UTC);
    expect(zapis.sync_status).toBe('pending');
    expect(zapis.file_uri).toBe(`file:///documents/photos/${zapis.id}.jpg`);
  });

  it('vzame id iz generatorja naključnih UUID-jev, ne iz časa ali zaporedja', async () => {
    crypto.randomUUID.mockReturnValueOnce('11111111-1111-4111-8111-111111111111');

    const zapis = await saveCapture(db, {
      subject: 'MAT',
      takenAt: CAS_POSNETKA,
      sourceUri: IZVIRNIK,
    });

    expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(zapis.id).toBe('11111111-1111-4111-8111-111111111111');
  });

  it('zapiše natanko eno vrstico, ki jo zgodovina najde', async () => {
    const zapis = await saveCapture(db, {
      subject: 'MAT',
      takenAt: CAS_POSNETKA,
      sourceUri: IZVIRNIK,
    });

    await expect(listBySubject(db, 'MAT')).resolves.toEqual([zapis]);
  });

  it('najprej zapiše datoteko, šele nato vrstico', async () => {
    let datotekaZapisana = false;
    let vrsticaVstavljena = false;

    store.savePhoto.mockImplementation(async (_source: string, ime: string) => {
      expect(vrsticaVstavljena).toBe(false);
      datotekaZapisana = true;
      return `file:///documents/photos/${ime}`;
    });

    const spy = jest.spyOn(db, 'runAsync');
    spy.mockImplementation(async (...args) => {
      expect(datotekaZapisana).toBe(true);
      vrsticaVstavljena = true;
      return undefined;
    });

    await saveCapture(db, { subject: 'MAT', takenAt: CAS_POSNETKA, sourceUri: IZVIRNIK });

    expect(datotekaZapisana).toBe(true);
    expect(vrsticaVstavljena).toBe(true);
    spy.mockRestore();
  });

  it('ob napaki pisanja datoteke ne pusti vrstice v bazi', async () => {
    store.savePhoto.mockRejectedValue(new Error('Na napravi ni prostora'));

    await expect(
      saveCapture(db, { subject: 'MAT', takenAt: CAS_POSNETKA, sourceUri: IZVIRNIK }),
    ).rejects.toThrow('Na napravi ni prostora');

    await expect(listBySubject(db, 'MAT')).resolves.toEqual([]);
  });
});
