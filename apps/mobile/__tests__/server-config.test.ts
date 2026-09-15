import { preberiNastavitve } from '@/config/server';

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: {} } },
}));

const NASLOV = 'https://school-buddy.duckdns.org';

/**
 * Manjkajoča nastavitev ni napaka: aplikacija mora delovati kot v V1-R01, samo
 * prenašati ne zna (odločitev 11 v `docs/plan/V1-R02.md`).
 *
 * Od V3-R02 aplikacija govori samo `https`; naslov z drugo shemo šteje kot
 * nenastavljen prenos (`docs/odlocitve/ADR-034` E).
 */
describe('nastavitve prenosa', () => {
  it('prebere naslov in ključ', () => {
    expect(preberiNastavitve({ serverBaseUrl: NASLOV, apiKey: 'skrivnost' })).toEqual({
      baseUrl: NASLOV,
      apiKey: 'skrivnost',
    });
  });

  it('odreže poševnico na koncu naslova', () => {
    // Sicer bi sestavljen naslov imel dvojno poševnico.
    expect(preberiNastavitve({ serverBaseUrl: `${NASLOV}/`, apiKey: 'k' })?.baseUrl).toBe(NASLOV);
  });

  it('shema sme biti zapisana z velikimi črkami', () => {
    // Shema v naslovu ne loči velikih in malih črk; zavrnitev bi bila napaka.
    expect(
      preberiNastavitve({ serverBaseUrl: 'HTTPS://school-buddy.duckdns.org', apiKey: 'k' }),
    ).not.toBeNull();
  });

  it.each([
    ['brez naslova', { apiKey: 'skrivnost' }],
    ['brez ključa', { serverBaseUrl: NASLOV }],
    ['prazen naslov', { serverBaseUrl: '', apiKey: 'skrivnost' }],
    ['sami presledki', { serverBaseUrl: '   ', apiKey: 'skrivnost' }],
    ['prazen ključ', { serverBaseUrl: NASLOV, apiKey: '' }],
    ['napačen tip', { serverBaseUrl: 42, apiKey: 'skrivnost' }],
    ['prazen extra', {}],
  ])('%s vrne null in ne vrže', (_opis, extra) => {
    expect(preberiNastavitve(extra)).toBeNull();
  });

  it.each([
    ['http', 'http://sto.ts.net:8000'],
    ['http z velikimi črkami', 'HTTP://school-buddy.duckdns.org'],
    ['brez sheme', 'school-buddy.duckdns.org'],
    ['z drugo shemo', 'ftp://school-buddy.duckdns.org'],
    ['s https samo sredi niza', 'http://sto.ts.net/?https://school-buddy.duckdns.org'],
    ['s https brez poševnic', 'https:school-buddy.duckdns.org'],
  ])('naslov %s vrne null — aplikacija govori samo https', (_opis, serverBaseUrl) => {
    expect(preberiNastavitve({ serverBaseUrl, apiKey: 'skrivnost' })).toBeNull();
  });

  it('manjkajoč extra vrne null', () => {
    expect(preberiNastavitve(undefined)).toBeNull();
    expect(preberiNastavitve(null)).toBeNull();
  });
});
