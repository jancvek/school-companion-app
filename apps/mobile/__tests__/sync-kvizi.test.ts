import {
  cakajociKvizi,
  neprenesenePoskuse,
  postavkeKviza,
  shraniKviz,
  zapisiPoskus,
} from '@/db/kvizi';
import type { MaterialsDatabase } from '@/db/materials';
import type { Zahteva } from '@/sync/http';
import {
  kviziIzOdgovora,
  NAJVEC_V_PAKETU,
  uskladiKvize,
  ustvariOdjemalcaKvizov,
  type OdjemalecKvizov,
} from '@/sync/kvizi';
import type { KvizStreznika, Poskus } from '@/types';

import { kvizStreznika, poskus } from './kvizi-podatki';
import { createMigratedDatabase } from './test-database';

const NASTAVITVE = { baseUrl: 'http://sto.ts.net:8000', apiKey: 'kljuc' };

/** Odjemalec, ki vrne dani seznam in si zapomni vrstni red klicev. */
function odjemalec(kvizi: KvizStreznika[] = []): OdjemalecKvizov & {
  klici: string[];
  poslani: Poskus[][];
  posljiPoskuse: jest.Mock;
  preberiKvize: jest.Mock;
} {
  const klici: string[] = [];
  const poslani: Poskus[][] = [];
  return {
    klici,
    poslani,
    posljiPoskuse: jest.fn(async (poskusi: readonly Poskus[]) => {
      klici.push('poskusi');
      poslani.push([...poskusi]);
    }),
    preberiKvize: jest.fn(async () => {
      klici.push('seznam');
      return kvizi;
    }),
  };
}

describe('uskladiKvize', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = await createMigratedDatabase();
  });

  afterEach(() => db.close());

  it('shrani nov kviz s seznama', async () => {
    const izid = await uskladiKvize(db, odjemalec([kvizStreznika('k1', 3)]));

    expect(izid).toEqual({ poslani: 0, naStrezniku: 1, pobrisani: 0 });
    expect((await cakajociKvizi(db)).map((k) => k.id)).toEqual(['k1']);
  });

  it('ponovno usklajevanje ne podvoji', async () => {
    const streznik = odjemalec([kvizStreznika('k1', 3)]);

    await uskladiKvize(db, streznik);
    await uskladiKvize(db, streznik);

    expect(await postavkeKviza(db, 'k1')).toHaveLength(3);
  });

  it('poskuse pošlje pred branjem seznama', async () => {
    // Strežnik kviz reši v isti transakciji kot zadnji poskus; seznam,
    // prebran po prenosu, je že brez njega.
    await shraniKviz(db, kvizStreznika('k1', 1));
    await zapisiPoskus(db, poskus('k1', 1));
    const streznik = odjemalec([]);

    await uskladiKvize(db, streznik);

    expect(streznik.klici).toEqual(['poskusi', 'seznam']);
  });

  it('brez neprenesenih poskusov ne pošlje praznega paketa', async () => {
    const streznik = odjemalec([]);

    await uskladiKvize(db, streznik);

    expect(streznik.posljiPoskuse).not.toHaveBeenCalled();
  });

  it('prenesenih poskusov drugič ne pošlje', async () => {
    await shraniKviz(db, kvizStreznika('k1', 2));
    await zapisiPoskus(db, poskus('k1', 1));
    const streznik = odjemalec([kvizStreznika('k1', 2)]);

    await uskladiKvize(db, streznik);
    await uskladiKvize(db, streznik);

    expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(1);
    expect(await neprenesenePoskuse(db)).toEqual([]);
  });

  it('kviz, ki ga strežnik ne vrača več, pobriše', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1));

    const izid = await uskladiKvize(db, odjemalec([]));

    expect(izid.pobrisani).toBe(1);
    expect(await cakajociKvizi(db)).toEqual([]);
  });

  it('odprtega kviza ne pobriše', async () => {
    await shraniKviz(db, kvizStreznika('k1', 2));

    await uskladiKvize(db, odjemalec([]), 'k1');

    expect(await postavkeKviza(db, 'k1')).toHaveLength(2);
  });

  it('neprenesen poskus preživi preklic kviza in gre gor ob naslednjem obhodu', async () => {
    // Kviz na pol, prenos poskusa spodleti, strežnik kviza medtem ne vrača več.
    await shraniKviz(db, kvizStreznika('k1', 3));
    await zapisiPoskus(db, poskus('k1', 1));
    const nedosegljiv = odjemalec([]);
    nedosegljiv.posljiPoskuse.mockRejectedValueOnce(new Error('omrežje'));
    await expect(uskladiKvize(db, nedosegljiv)).rejects.toThrow('omrežje');

    // Naslednji obhod: poskus gre gor, kviz gre s telefona.
    const streznik = odjemalec([]);
    await uskladiKvize(db, streznik);

    expect(streznik.poslani).toEqual([[expect.objectContaining({ id: 'k1-a1' })]]);
    expect(await postavkeKviza(db, 'k1')).toEqual([]);
  });

  it('neuspeh prenosa pusti poskuse in seznama ne bere', async () => {
    await shraniKviz(db, kvizStreznika('k1', 2));
    await zapisiPoskus(db, poskus('k1', 1));
    const streznik = odjemalec([]);
    streznik.posljiPoskuse.mockRejectedValueOnce(new Error('Strežnik je vrnil 500.'));

    await expect(uskladiKvize(db, streznik)).rejects.toThrow('500');

    expect(streznik.preberiKvize).not.toHaveBeenCalled();
    expect((await neprenesenePoskuse(db)).map((p) => p.id)).toEqual(['k1-a1']);
    expect(await postavkeKviza(db, 'k1')).toHaveLength(2);
  });

  it('po uspešnem prenosu in neuspešnem seznamu kviz ne čaka znova', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1));
    await zapisiPoskus(db, poskus('k1', 1));
    const streznik = odjemalec([]);
    streznik.preberiKvize.mockRejectedValueOnce(new Error('omrežje'));

    await expect(uskladiKvize(db, streznik)).rejects.toThrow('omrežje');

    // Poskus je prenesen, a še na telefonu — postavka je odgovorjena.
    expect(await neprenesenePoskuse(db)).toEqual([]);
    expect(await cakajociKvizi(db)).toEqual([]);
  });

  it('veliko poskusov razdeli v pakete', async () => {
    const postavk = NAJVEC_V_PAKETU + 1;
    await shraniKviz(db, kvizStreznika('k1', postavk));
    for (let i = 1; i <= postavk; i += 1) await zapisiPoskus(db, poskus('k1', i));
    const streznik = odjemalec([]);

    await uskladiKvize(db, streznik);

    expect(streznik.poslani.map((paket) => paket.length)).toEqual([NAJVEC_V_PAKETU, 1]);
  });
});

describe('kviziIzOdgovora', () => {
  it('vrne kvize po pogodbi', () => {
    expect(kviziIzOdgovora({ quizzes: [kvizStreznika('k1', 2)] })).toEqual([
      kvizStreznika('k1', 2),
    ]);
  });

  it.each([null, 'niz', {}, { quizzes: 'ni seznam' }])(
    'nerazberljiv odgovor %p vrže in ne vrne praznega seznama',
    (telo) => {
      // Prazen seznam bi usklajevanje razumelo kot „nič več ne čaka" in bi
      // pobrisalo tudi napol rešene kvize.
      expect(() => kviziIzOdgovora(telo)).toThrow();
    },
  );

  it('pokvarjen kviz izpusti, ostale obdrži', () => {
    const pokvarjen = { ...kvizStreznika('slab', 1), items: [{ id: 'x' }] };

    expect(
      kviziIzOdgovora({ quizzes: [pokvarjen, kvizStreznika('dober', 1)] }).map((k) => k.id),
    ).toEqual(['dober']);
  });
});

describe('ustvariOdjemalcaKvizov', () => {
  function zahteva(status: number, telo: unknown = {}): Zahteva & jest.Mock {
    return jest.fn(async () => ({ ok: status >= 200 && status < 300, status, json: async () => telo }));
  }

  it('bere seznam s ključem', async () => {
    const klic = zahteva(200, { quizzes: [kvizStreznika('k1', 1)] });

    const kvizi = await ustvariOdjemalcaKvizov(NASTAVITVE, klic).preberiKvize();

    expect(kvizi.map((k) => k.id)).toEqual(['k1']);
    const [url, moznosti] = klic.mock.calls[0];
    expect(url).toBe('http://sto.ts.net:8000/quizzes/pending');
    expect(moznosti.method).toBe('GET');
    expect(moznosti.headers['X-API-Key']).toBe('kljuc');
  });

  it('pošlje samo polja iz pogodbe', async () => {
    const klic = zahteva(200, { recorded: 1 });

    await ustvariOdjemalcaKvizov(NASTAVITVE, klic).posljiPoskuse([poskus('k1', 1)]);

    const [url, moznosti] = klic.mock.calls[0];
    expect(url).toBe('http://sto.ts.net:8000/quiz-attempts');
    expect(moznosti.method).toBe('POST');
    expect(moznosti.headers['X-API-Key']).toBe('kljuc');
    expect(JSON.parse(moznosti.body ?? '')).toEqual({
      attempts: [
        {
          id: 'k1-a1',
          quiz_item_id: 'k1-p1',
          mode: 'samoocena',
          rating: 'srednje',
          shown_at: '2026-09-10T15:00:00.000Z',
          revealed_at: '2026-09-10T15:00:07.000Z',
          answered_at: '2026-09-10T15:00:09.000Z',
        },
      ],
    });
  });

  it.each([401, 422, 500])('odgovor %d pri poskusih vrže', async (status) => {
    // Vrže, zato poskusi ostanejo nepreneseni — tudi 422 jih ne pobriše.
    await expect(
      ustvariOdjemalcaKvizov(NASTAVITVE, zahteva(status)).posljiPoskuse([poskus('k1', 1)]),
    ).rejects.toThrow(String(status));
  });

  it('neuspešen seznam vrže', async () => {
    await expect(ustvariOdjemalcaKvizov(NASTAVITVE, zahteva(503)).preberiKvize()).rejects.toThrow(
      '503',
    );
  });
});
