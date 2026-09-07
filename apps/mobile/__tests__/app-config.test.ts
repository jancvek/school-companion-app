/**
 * `app.config.ts` — kar pride v aplikacijo ob gradnji.
 *
 * Ta datoteka je edino mesto, kjer se `extra` sestavi, in edino mesto, kjer se
 * lahko polja pobijejo med sabo. Prvi poskus regresijskega testa (V1-R06) je
 * to trdil, a je preverjal le, da `preberiNastavitve` ignorira neznan ključ —
 * `app.config.ts` ni bil naložen v nobenem testu in je imel 0 % pokritosti.
 * Ugotovitev pregledovalca; ta test kliče pravi privzeti izvoz.
 */

import type { ConfigContext } from 'expo/config';

import appConfig from '../app.config';

/** Minimalen kontekst, kakršnega poda Expo. */
function kontekst(extra: Record<string, unknown> = {}): ConfigContext {
  return {
    config: { name: 'Šolski pomočnik', slug: 'school-companion', extra },
  } as unknown as ConfigContext;
}

const OKOLJE = { ...process.env };

afterEach(() => {
  process.env = { ...OKOLJE };
});

describe('app.config.ts', () => {
  it('vsa tri polja pridejo v extra in podedovano preživi', () => {
    // `extra.eas.projectId` pride iz `app.json` in veže projekt na EAS. Če bi
    // se izgubil, gradnja ne ve, kateri projekt gradi — in nič v aplikaciji
    // tega ne bi pokazalo.
    process.env.SERVER_BASE_URL = 'http://sto.ts.net:8000';
    process.env.SERVER_API_KEY = 'skrivnost';
    process.env.EAS_BUILD_ID = '317bdcd1-c7db-4c2c-8a6b-1cb1ce15ea29';

    const izid = appConfig(kontekst({ eas: { projectId: 'projekt-1' } }));

    expect(izid.extra).toEqual({
      eas: { projectId: 'projekt-1' },
      serverBaseUrl: 'http://sto.ts.net:8000',
      apiKey: 'skrivnost',
      buildId: '317bdcd1-c7db-4c2c-8a6b-1cb1ce15ea29',
    });
  });

  it('brez spremenljivk okolja so polja null, podedovano ostane', () => {
    delete process.env.SERVER_BASE_URL;
    delete process.env.SERVER_API_KEY;
    delete process.env.EAS_BUILD_ID;

    const izid = appConfig(kontekst({ eas: { projectId: 'projekt-1' } }));

    expect(izid.extra).toEqual({
      eas: { projectId: 'projekt-1' },
      serverBaseUrl: null,
      apiKey: null,
      buildId: null,
    });
  });

  it('ime in oznaka projekta ostaneta, kot ju poda app.json', () => {
    const izid = appConfig(kontekst());

    expect(izid.name).toBe('Šolski pomočnik');
    expect(izid.slug).toBe('school-companion');
  });
});
