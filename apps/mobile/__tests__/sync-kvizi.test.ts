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
  PaketZavrnjen,
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
    // Ko je gor, na telefonu ne ostane (`ADR-019` B).
    const [{ koliko }] = await db.getAllAsync<{ koliko: number }>(
      'SELECT COUNT(*) AS koliko FROM attempts',
      [],
    );
    expect(koliko).toBe(0);
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

  describe('trajno zavrnjen paket (ADR-020)', () => {
    it('ne ustavi prenosa novih kvizov', async () => {
      // Brez ADR-020 bi en neveljaven poskus za vedno odrezal telefon od
      // novih kvizov: vsak obhod bi se končal pred branjem seznama.
      await shraniKviz(db, kvizStreznika('k1', 2));
      await zapisiPoskus(db, poskus('k1', 1));
      const streznik = odjemalec([kvizStreznika('k1', 2), kvizStreznika('nov', 1)]);
      streznik.posljiPoskuse.mockRejectedValue(new PaketZavrnjen(422));

      const izid = await uskladiKvize(db, streznik);

      expect(streznik.preberiKvize).toHaveBeenCalledTimes(1);
      expect((await cakajociKvizi(db)).map((k) => k.id)).toContain('nov');
      expect(izid.poslani).toBe(0);
    });

    it('zavrnjenih poskusov ne označi za prenesene in jih ne pobriše', async () => {
      await shraniKviz(db, kvizStreznika('k1', 2));
      await zapisiPoskus(db, poskus('k1', 1));
      const streznik = odjemalec([]);
      streznik.posljiPoskuse.mockRejectedValue(new PaketZavrnjen(422));

      await uskladiKvize(db, streznik);
      await uskladiKvize(db, streznik);

      // Kviza ni več na seznamu, poskus pa ostane in se pošilja znova.
      expect(await postavkeKviza(db, 'k1')).toEqual([]);
      expect((await neprenesenePoskuse(db)).map((p) => p.id)).toEqual(['k1-a1']);
      expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(2);
    });

    it('slab poskus ne ustavi prenosa drugih poskusov', async () => {
      // Scenarij iz tretjega pregleda: slab poskus je najstarejši, zato je
      // vedno v prvem paketu. Brez razbitja paketa ne bi šla gor nobena ocena
      // za njim in noben kviz ne bi bil več rešen (`ADR-020`, popravek).
      await shraniKviz(db, kvizStreznika('slab', 1));
      await zapisiPoskus(db, poskus('slab', 1, { answered_at: '2026-09-10T14:00:00.000Z' }));
      await shraniKviz(db, kvizStreznika('k2', 3));
      for (let i = 1; i <= 3; i += 1) await zapisiPoskus(db, poskus('k2', i));
      const streznik = odjemalec([]);
      streznik.posljiPoskuse.mockImplementation(async (paket: readonly Poskus[]) => {
        streznik.poslani.push([...paket]);
        if (paket.some((p) => p.quiz_id === 'slab')) throw new PaketZavrnjen(422);
      });

      const izid = await uskladiKvize(db, streznik);

      expect(izid.poslani).toBe(3);
      expect((await neprenesenePoskuse(db)).map((p) => p.id)).toEqual(['slab-a1']);
      // En paket s štirimi, nato vsak posebej.
      expect(streznik.poslani.map((p) => p.length)).toEqual([4, 1, 1, 1, 1]);
      expect(streznik.preberiKvize).toHaveBeenCalledTimes(1);
    });

    it('zavrnjen paket se ponovi po en poskus in ne ustavi naslednjih paketov', async () => {
      // Do tretjega pregleda je ta test trdil, da zavrnjen paket ostane cel
      // neprenesen (500 od 501). Lastnik je to vedenje preglasil (`ADR-020`,
      // popravek prve različice); test sledi novi odločitvi.
      const postavk = NAJVEC_V_PAKETU + 1;
      await shraniKviz(db, kvizStreznika('k1', postavk));
      for (let i = 1; i <= postavk; i += 1) await zapisiPoskus(db, poskus('k1', i));
      const streznik = odjemalec([kvizStreznika('k1', postavk)]);
      streznik.posljiPoskuse.mockRejectedValueOnce(new PaketZavrnjen(422));

      const izid = await uskladiKvize(db, streznik);

      // Zavrnjen paket, 500 posamičnih, drugi paket.
      expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(NAJVEC_V_PAKETU + 2);
      expect(izid.poslani).toBe(postavk);
      expect(await neprenesenePoskuse(db)).toEqual([]);
    });

    it.each([401, 403, 404, 413])(
      'zavrnitve %d ne razbije — obhod gre naprej brez ponavljanja',
      async (status) => {
        // Četrti pregled: ob napačnem ključu bi razbitje pomenilo do 501
        // zaman poslan zahtevek vsakih 5 minut (`ADR-020`, razbija se samo ob 422).
        await shraniKviz(db, kvizStreznika('k1', 3));
        for (let i = 1; i <= 3; i += 1) await zapisiPoskus(db, poskus('k1', i));
        const streznik = odjemalec([kvizStreznika('k1', 3)]);
        streznik.posljiPoskuse.mockRejectedValue(new PaketZavrnjen(status));

        const izid = await uskladiKvize(db, streznik);

        expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(1);
        expect(streznik.preberiKvize).toHaveBeenCalledTimes(1);
        expect(izid.poslani).toBe(0);
        expect(await neprenesenePoskuse(db)).toHaveLength(3);
      },
    );

    it('zavrnitev, ki ni 422, ustavi razbijanje', async () => {
      await shraniKviz(db, kvizStreznika('k1', 3));
      for (let i = 1; i <= 3; i += 1) await zapisiPoskus(db, poskus('k1', i));
      const streznik = odjemalec([]);
      streznik.posljiPoskuse
        .mockRejectedValueOnce(new PaketZavrnjen(422))
        .mockRejectedValueOnce(new PaketZavrnjen(401));

      await uskladiKvize(db, streznik);

      // Paket in prvi posamični; ostala dva se ne pošljeta.
      expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(2);
      expect(await neprenesenePoskuse(db)).toHaveLength(3);
      expect(streznik.preberiKvize).toHaveBeenCalledTimes(1);
    });

    it('paketa z enim samim poskusom ne ponavlja', async () => {
      await shraniKviz(db, kvizStreznika('k1', 1));
      await zapisiPoskus(db, poskus('k1', 1));
      const streznik = odjemalec([]);
      streznik.posljiPoskuse.mockRejectedValue(new PaketZavrnjen(422));

      await uskladiKvize(db, streznik);

      expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(1);
    });

    it('nedosegljiv strežnik med posamičnim pošiljanjem konča obhod, sprejeti ostanejo', async () => {
      await shraniKviz(db, kvizStreznika('k1', 3));
      for (let i = 1; i <= 3; i += 1) await zapisiPoskus(db, poskus('k1', i));
      const streznik = odjemalec([]);
      streznik.posljiPoskuse
        .mockRejectedValueOnce(new PaketZavrnjen(422))
        .mockResolvedValueOnce(undefined)
        .mockRejectedValueOnce(new Error('omrežje'));

      await expect(uskladiKvize(db, streznik)).rejects.toThrow('omrežje');

      expect((await neprenesenePoskuse(db)).map((p) => p.id)).toEqual(['k1-a2', 'k1-a3']);
      expect(streznik.preberiKvize).not.toHaveBeenCalled();
      expect(await postavkeKviza(db, 'k1')).toHaveLength(3);
    });

    it.each([
      [422, true],
      [401, true],
      [404, true],
      [408, false],
      [429, false],
      [500, false],
      [503, false],
    ])('odgovor %d je trajna zavrnitev: %p', async (status, trajno) => {
      const klic: Zahteva = jest.fn(async () => ({
        ok: false,
        status,
        json: async () => ({}),
      }));

      const napaka = await ustvariOdjemalcaKvizov(NASTAVITVE, klic)
        .posljiPoskuse([poskus('k1', 1)])
        .catch((e: unknown) => e);

      expect(napaka).toBeInstanceOf(Error);
      expect(napaka instanceof PaketZavrnjen).toBe(trajno);
    });

    it('s pravim odjemalcem: ob 422 se seznam prebere, ob 429 ne', async () => {
      await shraniKviz(db, kvizStreznika('k1', 1));
      await zapisiPoskus(db, poskus('k1', 1));

      for (const [status, seznamPrebran] of [
        [422, true],
        [429, false],
      ] as const) {
        const klic = jest.fn(async (url: string) =>
          url.endsWith('/quiz-attempts')
            ? { ok: false, status, json: async () => ({}) }
            : { ok: true, status: 200, json: async () => ({ quizzes: [kvizStreznika('k1', 1)] }) },
        );
        const streznik = ustvariOdjemalcaKvizov(NASTAVITVE, klic as unknown as Zahteva);

        const obhod = uskladiKvize(db, streznik);
        if (seznamPrebran) await expect(obhod).resolves.toBeDefined();
        else await expect(obhod).rejects.toThrow('429');

        const branja = klic.mock.calls.filter(([url]) => url.endsWith('/quizzes/pending'));
        expect(branja).toHaveLength(seznamPrebran ? 1 : 0);
      }
    });
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
