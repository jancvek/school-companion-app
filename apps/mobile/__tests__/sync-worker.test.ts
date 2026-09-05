import { insertMaterial, listPending, type MaterialsDatabase } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import type { Izid } from '@/sync/upload';
import {
  INTERVAL_MS,
  NAJVECJI_ODMIK_MS,
  naslednjiOdmik,
  prenesiCakajoce,
  ustvariRazporejevalnik,
} from '@/sync/worker';
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

const USPEH: Izid = { vrsta: 'synced' };
const CAKA: Izid = { vrsta: 'pending', razlog: 'strežnik ni dosegljiv' };
const ZAVRNJEN: Izid = { vrsta: 'failed', razlog: 'strežnik je zavrnil ključ' };

async function stanje(db: MaterialsDatabase, id: string): Promise<Material> {
  const [zapis] = await db.getAllAsync<Material>('SELECT * FROM materials WHERE id = ?', [id]);
  return zapis;
}

describe('oddelava čakalne vrste', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => {
    db.close();
  });

  it('uspešen prenos postavi synced', async () => {
    await insertMaterial(db, material());

    const povzetek = await prenesiCakajoce(db, async () => USPEH);

    expect(povzetek).toEqual({ preneseni: 1, cakajoci: 0, neuspeli: 0 });
    expect((await stanje(db, 'id-1')).sync_status).toBe('synced');
  });

  it('zavrnjen prenos postavi failed in zapiše razlog', async () => {
    await insertMaterial(db, material());

    const povzetek = await prenesiCakajoce(db, async () => ZAVRNJEN);

    expect(povzetek).toEqual({ preneseni: 0, cakajoci: 0, neuspeli: 1 });
    const zapis = await stanje(db, 'id-1');
    expect(zapis.sync_status).toBe('failed');
    expect(zapis.sync_error).toBe('strežnik je zavrnil ključ');
  });

  it('nedosegljiv strežnik pusti zapis v vrsti in prišteje poskus', async () => {
    await insertMaterial(db, material());

    const povzetek = await prenesiCakajoce(db, async () => CAKA);

    expect(povzetek.cakajoci).toBe(1);
    const zapis = await stanje(db, 'id-1');
    expect(zapis.sync_status).toBe('pending');
    expect(zapis.sync_attempts).toBe(1);
    expect(zapis.last_attempt_at).not.toBeNull();
  });

  it('prenaša enega za drugim, ne hkrati', async () => {
    await insertMaterial(db, material({ id: 'a', taken_at: '2026-09-01T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'b', taken_at: '2026-09-02T08:00:00.000Z' }));

    let hkratnih = 0;
    let najvec = 0;
    const vrstniRed: string[] = [];

    await prenesiCakajoce(db, async (m) => {
      hkratnih += 1;
      najvec = Math.max(najvec, hkratnih);
      vrstniRed.push(m.id);
      await new Promise((r) => setTimeout(r, 1));
      hkratnih -= 1;
      return USPEH;
    });

    expect(najvec).toBe(1);
    expect(vrstniRed).toEqual(['a', 'b']);
  });

  it('ob nedosegljivem strežniku ne poskuša še preostalih', async () => {
    await insertMaterial(db, material({ id: 'a', taken_at: '2026-09-01T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'b', taken_at: '2026-09-02T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'c', taken_at: '2026-09-03T08:00:00.000Z' }));

    const poskuseni: string[] = [];
    const povzetek = await prenesiCakajoce(db, async (m) => {
      poskuseni.push(m.id);
      return CAKA;
    });

    // Če ni šlo za prvo sliko, ne bo šlo niti za tretjo, vsaka pa bi stala
    // svoj potek časovne omejitve.
    expect(poskuseni).toEqual(['a']);
    expect(povzetek.cakajoci).toBe(3);
    expect((await listPending(db)).map((v) => v.id)).toEqual(['a', 'b', 'c']);
  });

  it('zavrnjen zapis ne ustavi vrste', async () => {
    await insertMaterial(db, material({ id: 'a', taken_at: '2026-09-01T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'b', taken_at: '2026-09-02T08:00:00.000Z' }));

    const povzetek = await prenesiCakajoce(db, async (m) =>
      m.id === 'a' ? ZAVRNJEN : USPEH,
    );

    expect(povzetek).toEqual({ preneseni: 1, cakajoci: 0, neuspeli: 1 });
    expect((await stanje(db, 'b')).sync_status).toBe('synced');
  });

  it('prazna vrsta ne naredi ničesar', async () => {
    const prenesiEno = jest.fn();

    const povzetek = await prenesiCakajoce(db, prenesiEno);

    expect(prenesiEno).not.toHaveBeenCalled();
    expect(povzetek).toEqual({ preneseni: 0, cakajoci: 0, neuspeli: 0 });
  });

  it('preneseni in zavrnjeni se ne poskušajo znova', async () => {
    await insertMaterial(db, material({ id: 'a', sync_status: 'synced' }));
    await insertMaterial(db, material({ id: 'b', sync_status: 'failed' }));
    const prenesiEno = jest.fn();

    await prenesiCakajoce(db, prenesiEno);

    expect(prenesiEno).not.toHaveBeenCalled();
  });
});

describe('odmik med poskusi', () => {
  it('po uspehu je spet redni interval', () => {
    expect(naslednjiOdmik(NAJVECJI_ODMIK_MS, true)).toBe(INTERVAL_MS);
  });

  it('po neuspehu se podvoji', () => {
    expect(naslednjiOdmik(INTERVAL_MS, false)).toBe(INTERVAL_MS * 2);
  });

  it('dva zaporedna neuspeha razporedita drugi poskus kasneje kot prvega', () => {
    const prvi = naslednjiOdmik(INTERVAL_MS, false);
    const drugi = naslednjiOdmik(prvi, false);

    expect(drugi).toBeGreaterThan(prvi);
  });

  it('nikoli ne preseže zgornje meje', () => {
    let odmik = INTERVAL_MS;
    for (let i = 0; i < 20; i += 1) odmik = naslednjiOdmik(odmik, false);

    expect(odmik).toBe(NAJVECJI_ODMIK_MS);
  });
});

describe('razporejevalnik', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => {
    db.close();
  });

  /** Zbere razporejene naloge, da test ne rabi pravega časa. */
  function casovnik() {
    const naloge: { f: () => void; ms: number }[] = [];
    return {
      naloge,
      nastaviCasovnik: (f: () => void, ms: number) => {
        naloge.push({ f, ms });
        return naloge.length as unknown as ReturnType<typeof setTimeout>;
      },
      pocistiCasovnik: () => {},
    };
  }

  it('ob zagonu takoj poskusi prenesti', async () => {
    await insertMaterial(db, material());
    const c = casovnik();
    const prenesiEno = jest.fn(async () => USPEH);

    const r = ustvariRazporejevalnik({ db, prenesiEno, ...c });
    r.zazeni();
    await new Promise(process.nextTick);

    expect(prenesiEno).toHaveBeenCalledTimes(1);
    r.ustavi();
  });

  it('po uspešnem ciklu razporedi naslednjega čez redni interval', async () => {
    await insertMaterial(db, material());
    const c = casovnik();

    const r = ustvariRazporejevalnik({ db, prenesiEno: async () => USPEH, ...c });
    r.zazeni();
    await new Promise(process.nextTick);

    expect(c.naloge.at(-1)?.ms).toBe(INTERVAL_MS);
    r.ustavi();
  });

  it('po neuspešnem ciklu razporedi naslednjega kasneje', async () => {
    await insertMaterial(db, material());
    const c = casovnik();

    const r = ustvariRazporejevalnik({ db, prenesiEno: async () => CAKA, ...c });
    r.zazeni();
    await new Promise(process.nextTick);

    expect(c.naloge.at(-1)?.ms).toBeGreaterThan(INTERVAL_MS);
    r.ustavi();
  });

  it('po ustavitvi ne razporeja več', async () => {
    await insertMaterial(db, material());
    const c = casovnik();

    const r = ustvariRazporejevalnik({ db, prenesiEno: async () => USPEH, ...c });
    r.zazeni();
    await new Promise(process.nextTick);
    const koliko = c.naloge.length;

    r.ustavi();
    r.sprozi();
    await new Promise(process.nextTick);

    expect(c.naloge.length).toBe(koliko);
  });

  it('dve sprožitvi hkrati ne pogosta dveh zank', async () => {
    await insertMaterial(db, material({ id: 'a' }));
    const c = casovnik();

    let hkratnih = 0;
    let najvec = 0;
    const r = ustvariRazporejevalnik({
      db,
      prenesiEno: async () => {
        hkratnih += 1;
        najvec = Math.max(najvec, hkratnih);
        await new Promise((res) => setTimeout(res, 1));
        hkratnih -= 1;
        return USPEH;
      },
      ...c,
    });

    r.zazeni();
    r.sprozi();
    r.sprozi();
    await new Promise((res) => setTimeout(res, 20));

    // Strežnik je sicer idempotenten, a to je njegova varovalka, ne izgovor
    // za pošiljanje istega zapisa dvakrat.
    expect(najvec).toBe(1);
    r.ustavi();
  });

  it('napaka baze ne ustavi workerja in ne pobegne kot nezavrnjena obljuba', async () => {
    const pokvarjena: MaterialsDatabase = {
      execAsync: async () => {},
      runAsync: async () => ({}),
      getAllAsync: async () => {
        throw new Error('baza je odpovedala');
      },
    };
    const c = casovnik();

    const r = ustvariRazporejevalnik({
      db: pokvarjena,
      prenesiEno: async () => USPEH,
      ...c,
    });

    r.zazeni();
    await new Promise(process.nextTick);

    // Naslednji poskus je vseeno razporejen — worker ne sme obtičati.
    expect(c.naloge.length).toBeGreaterThan(0);
    r.ustavi();
  });

  it('po vsakem ciklu javi povzetek, da se vmesnik osveži', async () => {
    await insertMaterial(db, material());
    const c = casovnik();
    const poCiklu = jest.fn();

    const r = ustvariRazporejevalnik({ db, prenesiEno: async () => USPEH, poCiklu, ...c });
    r.zazeni();
    await new Promise(process.nextTick);

    expect(poCiklu).toHaveBeenCalledWith({ preneseni: 1, cakajoci: 0, neuspeli: 0 });
    r.ustavi();
  });
});
