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
 *
 * Od V3-R04 tu ni več ključa: kdo je prijavljen, pove žeton v varni shrambi,
 * ne vrednost iz gradnje (`docs/odlocitve/ADR-027`, `ADR-036`).
 */
describe('nastavitve prenosa', () => {
  it('prebere naslov', () => {
    expect(preberiNastavitve({ serverBaseUrl: NASLOV })).toEqual({ baseUrl: NASLOV });
  });

  it('ključ v gradnji ne pomeni ničesar več', () => {
    // Star APK je imel `apiKey` v `extra`. Nadgrajena aplikacija ga prezre in
    // ga zlasti **ne** vrne naprej: nič se ne sme izkazati z njim.
    expect(preberiNastavitve({ serverBaseUrl: NASLOV, apiKey: 'star-kljuc' })).toEqual({
      baseUrl: NASLOV,
    });
  });

  it('odreže poševnico na koncu naslova', () => {
    // Sicer bi sestavljen naslov imel dvojno poševnico.
    expect(preberiNastavitve({ serverBaseUrl: `${NASLOV}/` })?.baseUrl).toBe(NASLOV);
  });

  it('shema sme biti zapisana z velikimi črkami', () => {
    // Shema v naslovu ne loči velikih in malih črk; zavrnitev bi bila napaka.
    expect(
      preberiNastavitve({ serverBaseUrl: 'HTTPS://school-buddy.duckdns.org' }),
    ).not.toBeNull();
  });

  it.each([
    ['brez naslova', {}],
    ['prazen naslov', { serverBaseUrl: '' }],
    ['sami presledki', { serverBaseUrl: '   ' }],
    ['napačen tip', { serverBaseUrl: 42 }],
    ['sam ključ brez naslova', { apiKey: 'star-kljuc' }],
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
    expect(preberiNastavitve({ serverBaseUrl })).toBeNull();
  });

  it('manjkajoč extra vrne null', () => {
    expect(preberiNastavitve(undefined)).toBeNull();
    expect(preberiNastavitve(null)).toBeNull();
  });
});
