import { preberiNastavitve } from '@/config/server';

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: {} } },
}));

/**
 * Manjkajoča nastavitev ni napaka: aplikacija mora delovati kot v V1-R01, samo
 * prenašati ne zna (odločitev 11 v `docs/plan/V1-R02.md`).
 */
describe('nastavitve prenosa', () => {
  it('prebere naslov in ključ', () => {
    expect(
      preberiNastavitve({ serverBaseUrl: 'http://sto.ts.net:8000', apiKey: 'skrivnost' }),
    ).toEqual({ baseUrl: 'http://sto.ts.net:8000', apiKey: 'skrivnost' });
  });

  it('odreže poševnico na koncu naslova', () => {
    // Sicer bi sestavljen naslov imel dvojno poševnico.
    expect(preberiNastavitve({ serverBaseUrl: 'http://sto.ts.net:8000/', apiKey: 'k' })?.baseUrl)
      .toBe('http://sto.ts.net:8000');
  });

  it.each([
    ['brez naslova', { apiKey: 'skrivnost' }],
    ['brez ključa', { serverBaseUrl: 'http://sto.ts.net:8000' }],
    ['prazen naslov', { serverBaseUrl: '', apiKey: 'skrivnost' }],
    ['sami presledki', { serverBaseUrl: '   ', apiKey: 'skrivnost' }],
    ['prazen ključ', { serverBaseUrl: 'http://sto.ts.net:8000', apiKey: '' }],
    ['napačen tip', { serverBaseUrl: 42, apiKey: 'skrivnost' }],
    ['prazen extra', {}],
  ])('%s vrne null in ne vrže', (_opis, extra) => {
    expect(preberiNastavitve(extra)).toBeNull();
  });

  it('manjkajoč extra vrne null', () => {
    expect(preberiNastavitve(undefined)).toBeNull();
    expect(preberiNastavitve(null)).toBeNull();
  });
});
