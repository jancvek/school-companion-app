/**
 * Izpis verzije in oznake gradnje (V1-R06).
 *
 * Funkcija vrne besedilo, ki gre naravnost na zaslon, zato testi ne preverjajo
 * samo srečne poti, ampak predvsem to, da uporabnica nikoli ne vidi `null`,
 * `undefined` ali prazne vrstice.
 */

import { preberiNastavitve } from '@/config/server';
import { DOLZINA_OZNAKE, opisVerzije } from '@/config/verzija';

describe('opisVerzije', () => {
  it('pokaže verzijo in skrajšano oznako gradnje', () => {
    const besedilo = opisVerzije({
      version: '1.0.0',
      extra: { buildId: '317bdcd1-c7db-4c2c-8a6b-1cb1ce15ea29' },
    });

    expect(besedilo).toBe('1.0.0 · gradnja 317bdcd1');
  });

  it('oznako skrajša na dogovorjeno dolžino', () => {
    const besedilo = opisVerzije({
      version: '1.0.0',
      extra: { buildId: 'abcdefghijklmnop' },
    });

    expect(besedilo).toBe(`1.0.0 · gradnja ${'abcdefghijklmnop'.slice(0, DOLZINA_OZNAKE)}`);
    expect(besedilo).not.toContain('ijklmnop');
  });

  it('razvojno gradnjo pove naravnost', () => {
    expect(opisVerzije({ version: '1.0.0', extra: { buildId: null } })).toBe(
      '1.0.0 · razvojna gradnja',
    );
  });

  it('prazna oznaka šteje kot odsotna', () => {
    // Spremenljivka okolja, nastavljena na prazen niz, je pogostejša od
    // odsotne — brez tega bi na zaslonu pisalo „gradnja " brez ničesar.
    expect(opisVerzije({ version: '1.0.0', extra: { buildId: '   ' } })).toBe(
      '1.0.0 · razvojna gradnja',
    );
  });

  it('brez konfiguracije ne vrne prazne vrstice', () => {
    const besedilo = opisVerzije(null);

    expect(besedilo).toBe('neznana različica · razvojna gradnja');
  });

  it('nikoli ne izpiše null ali undefined', () => {
    const primeri = [
      opisVerzije(null),
      opisVerzije({}),
      opisVerzije({ version: undefined, extra: undefined }),
      opisVerzije({ version: '1.0.0', extra: { buildId: 42 as unknown as string } }),
    ];

    for (const besedilo of primeri) {
      expect(besedilo.length).toBeGreaterThan(0);
      expect(besedilo).not.toContain('null');
      expect(besedilo).not.toContain('undefined');
    }
  });
});

describe('regresija V1-R02', () => {
  it('novo polje v extra ne povozi naslova in ključa', () => {
    // `app.config.ts` piše vsa tri polja v isti `extra`; če bi se pobila,
    // bi tiho odpovedal prenos — in to brez enega samega rdečega testa.
    const nastavitve = preberiNastavitve({
      serverBaseUrl: 'http://100.0.0.1:8000',
      apiKey: 'kljuc',
      buildId: '317bdcd1-c7db-4c2c-8a6b-1cb1ce15ea29',
    });

    expect(nastavitve).toEqual({ baseUrl: 'http://100.0.0.1:8000', apiKey: 'kljuc' });
  });
});
