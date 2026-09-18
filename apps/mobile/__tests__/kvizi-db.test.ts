import {
  cakajociKvizi,
  neprenesenePoskuse,
  oznaciPrenesene,
  pobrisiKvizeRazen,
  postavkeKviza,
  shraniKviz,
  zapisiPoskus,
} from '@/db/kvizi';
import type { MaterialsDatabase } from '@/db/materials';

import { kvizStreznika, poskus } from './kvizi-podatki';
import { createMigratedDatabase } from './test-database';

/**
 * Lokalne tabele za kvize (V2-R02). Testi tečejo nad pravo SQLite bazo, ker
 * je pravilo „kdaj kviz čaka" ena poizvedba in ne JavaScript.
 */

async function stej(db: MaterialsDatabase, tabela: string): Promise<number> {
  const [{ koliko }] = await db.getAllAsync<{ koliko: number }>(
    `SELECT COUNT(*) AS koliko FROM ${tabela}`,
    [],
  );
  return koliko;
}

describe('lokalni kvizi', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = await createMigratedDatabase();
  });

  afterEach(() => db.close());

  describe('shraniKviz', () => {
    it('shrani kviz in vse postavke', async () => {
      await shraniKviz(db, kvizStreznika('k1', 3));

      expect(await stej(db, 'quizzes')).toBe(1);
      const postavke = await postavkeKviza(db, 'k1');
      expect(postavke.map((p) => p.position)).toEqual([1, 2, 3]);
      expect(postavke[1].question_text).toBe('Vprašanje 2?');
      expect(postavke[1].answer_text).toBe('Odgovor 2.');
    });

    it('ponovljen klic ne podvoji ničesar', async () => {
      await shraniKviz(db, kvizStreznika('k1', 3));
      await shraniKviz(db, kvizStreznika('k1', 3));

      expect(await stej(db, 'quizzes')).toBe(1);
      expect(await stej(db, 'quiz_items')).toBe(3);
    });

    it('vsebine obstoječega kviza ne prepiše — je zamrznjena', async () => {
      await shraniKviz(db, kvizStreznika('k1', 1));
      const spremenjen = kvizStreznika('k1', 1);
      spremenjen.items[0].question = 'Drugače?';

      await shraniKviz(db, spremenjen);

      expect((await postavkeKviza(db, 'k1'))[0].question_text).toBe('Vprašanje 1?');
    });

    it('postavka, odgovorjena na strežniku, šteje za odgovorjeno', async () => {
      const kviz = kvizStreznika('k1', 3);
      kviz.items[0].answered = true;

      await shraniKviz(db, kviz);

      expect((await postavkeKviza(db, 'k1')).map((p) => p.odgovorjena)).toEqual([
        true,
        false,
        false,
      ]);
    });

    it('odgovorjenost s strežnika se doda tudi obstoječemu kvizu', async () => {
      await shraniKviz(db, kvizStreznika('k1', 2));
      const pozneje = kvizStreznika('k1', 2);
      pozneje.items[1].answered = true;

      await shraniKviz(db, pozneje);

      expect((await postavkeKviza(db, 'k1')).map((p) => p.odgovorjena)).toEqual([false, true]);
    });
  });

  describe('cakajociKvizi', () => {
    it('našteje čakajoče, najstarejši prvi', async () => {
      await shraniKviz(db, kvizStreznika('mlajsi', 2, { created_at: '2026-09-10T08:00:00+00:00' }));
      await shraniKviz(db, kvizStreznika('starejsi', 2, { created_at: '2026-09-08T08:00:00+00:00' }));

      expect((await cakajociKvizi(db)).map((k) => k.id)).toEqual(['starejsi', 'mlajsi']);
    });

    it('lokalno rešenega ne našteje', async () => {
      await shraniKviz(db, kvizStreznika('k1', 2));
      await zapisiPoskus(db, poskus('k1', 1));
      await zapisiPoskus(db, poskus('k1', 2));

      expect(await cakajociKvizi(db)).toEqual([]);
    });

    it('napol rešenega našteje s številom odgovorjenih', async () => {
      await shraniKviz(db, kvizStreznika('k1', 3));
      await zapisiPoskus(db, poskus('k1', 1));

      expect(await cakajociKvizi(db)).toEqual([
        expect.objectContaining({ id: 'k1', vprasanj: 3, odgovorjenih: 1 }),
      ]);
    });

    it('odgovorjenost s strežnika šteje enako kot lokalni poskus', async () => {
      const kviz = kvizStreznika('k1', 2);
      kviz.items[0].answered = true;
      await shraniKviz(db, kviz);
      await zapisiPoskus(db, poskus('k1', 2));

      expect(await cakajociKvizi(db)).toEqual([]);
    });
  });

  describe('poskusi', () => {
    it('drugi poskus za isto postavko se prezre — prvi zmaga', async () => {
      await shraniKviz(db, kvizStreznika('k1', 1));
      await zapisiPoskus(db, poskus('k1', 1, { id: 'prvi', rating: 'lahko' }));
      await zapisiPoskus(db, poskus('k1', 1, { id: 'drugi', rating: 'nisem_vedela' }));

      const poskusi = await neprenesenePoskuse(db, null);
      expect(poskusi.map((p) => [p.id, p.rating])).toEqual([['prvi', 'lahko']]);
    });

    it('prenesen poskus dobi žig in ni več med neprenesenimi', async () => {
      await shraniKviz(db, kvizStreznika('k1', 2));
      await zapisiPoskus(db, poskus('k1', 1));
      await zapisiPoskus(db, poskus('k1', 2));

      await oznaciPrenesene(db, ['k1-a1'], '2026-09-10T16:00:00.000Z');

      expect((await neprenesenePoskuse(db, null)).map((p) => p.id)).toEqual(['k1-a2']);
      const [vrstica] = await db.getAllAsync<{ uploaded_at: string }>(
        "SELECT uploaded_at FROM attempts WHERE id = 'k1-a1'",
        [],
      );
      expect(vrstica.uploaded_at).toBe('2026-09-10T16:00:00.000Z');
    });

    it('prenesen poskus postavko še vedno šteje za odgovorjeno', async () => {
      // Brez tega bi kviz med uspešnim prenosom in neuspešnim branjem
      // seznama spet čakal in Maša bi ga reševala znova.
      await shraniKviz(db, kvizStreznika('k1', 1));
      await zapisiPoskus(db, poskus('k1', 1));
      await oznaciPrenesene(db, ['k1-a1'], '2026-09-10T16:00:00.000Z');

      expect(await cakajociKvizi(db)).toEqual([]);
    });
  });

  describe('pobrisiKvizeRazen', () => {
    it('pobriše kviz, ki ga strežnik ne vrača, s postavkami in prenesenimi poskusi', async () => {
      await shraniKviz(db, kvizStreznika('k1', 2));
      await zapisiPoskus(db, poskus('k1', 1));
      await oznaciPrenesene(db, ['k1-a1'], '2026-09-10T16:00:00.000Z');

      const pobrisani = await pobrisiKvizeRazen(db, []);

      expect(pobrisani).toBe(1);
      expect(await stej(db, 'quizzes')).toBe(0);
      expect(await stej(db, 'quiz_items')).toBe(0);
      expect(await stej(db, 'attempts')).toBe(0);
    });

    it('kvize s seznama ohrani', async () => {
      await shraniKviz(db, kvizStreznika('k1', 1));
      await shraniKviz(db, kvizStreznika('k2', 1));

      await pobrisiKvizeRazen(db, ['k2']);

      expect((await cakajociKvizi(db)).map((k) => k.id)).toEqual(['k2']);
    });

    it('neprenesenega poskusa ne pobriše nikoli', async () => {
      // `ADR-019` C: kviz, preklican sredi reševanja, gre, poskus ostane.
      await shraniKviz(db, kvizStreznika('k1', 3));
      await zapisiPoskus(db, poskus('k1', 1));

      await pobrisiKvizeRazen(db, []);

      expect(await stej(db, 'quizzes')).toBe(0);
      expect((await neprenesenePoskuse(db, null)).map((p) => p.id)).toEqual(['k1-a1']);
    });

    it('poskus pobrisanega kviza gre, ko je prenesen', async () => {
      // Kviz je šel pred prenosom poskusa (preklic). Poskus je ostal, da gre
      // gor; ko je gor, ga nič več ne veže na telefon (`ADR-019` B).
      await shraniKviz(db, kvizStreznika('k1', 3));
      await zapisiPoskus(db, poskus('k1', 1));
      await pobrisiKvizeRazen(db, []);
      expect(await stej(db, 'attempts')).toBe(1);

      await oznaciPrenesene(db, ['k1-a1'], '2026-09-10T16:00:00.000Z');
      await pobrisiKvizeRazen(db, []);

      expect(await stej(db, 'attempts')).toBe(0);
    });

    it('prenesenih poskusov kviza, ki je še na telefonu, ne pobriše', async () => {
      await shraniKviz(db, kvizStreznika('k1', 2));
      await zapisiPoskus(db, poskus('k1', 1));
      await oznaciPrenesene(db, ['k1-a1'], '2026-09-10T16:00:00.000Z');

      await pobrisiKvizeRazen(db, ['k1']);

      expect(await stej(db, 'attempts')).toBe(1);
      expect((await postavkeKviza(db, 'k1'))[0].odgovorjena).toBe(true);
    });

    it('odprtega kviza ne pobriše', async () => {
      await shraniKviz(db, kvizStreznika('k1', 2));

      const pobrisani = await pobrisiKvizeRazen(db, [], 'k1');

      expect(pobrisani).toBe(0);
      expect((await postavkeKviza(db, 'k1')).length).toBe(2);
    });
  });
});
