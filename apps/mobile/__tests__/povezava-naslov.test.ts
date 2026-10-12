import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { jeZeton, PARAMETER, POT, SHEMA, zetonIzPovezave } from '@/povezava/naslov';

/**
 * Povezava za povezavo telefona (V6-R01, `docs/odlocitve/ADR-058` C,
 * `ADR-061` C).
 *
 * Prebrana koda je vhod od zunaj: otrok lahko s kamero prebere karkoli.
 * Kar ni natanko naša povezava z žetonom, ne sme do strežnika.
 */

/** Žeton, kakršnega izda strežnik (`secrets.token_urlsafe(32)`, 43 znakov). */
const ZETON = 'aB3_dE6-gH9jKlMnOpQrStUvWxYz0123456789-_AbC';

describe('žeton iz povezave', () => {
  it('prebere žeton iz povezave, ki jo sestavi strežnik', () => {
    expect(zetonIzPovezave(`school-companion://povezi?z=${ZETON}`)).toBe(ZETON);
  });

  it('povezavo sestavi iz istih delov, kot jih pozna strežnik', () => {
    // `apps/server/app/povezava.py`: SHEMA, POT in PARAMETER morajo biti isti.
    expect(zetonIzPovezave(`${SHEMA}://${POT}?${PARAMETER}=${ZETON}`)).toBe(ZETON);
    expect([SHEMA, POT, PARAMETER]).toEqual(['school-companion', 'povezi', 'z']);
  });

  it('shema je shema aplikacije iz app.json', () => {
    // Koda z drugo shemo aplikacije ne odpre — tiha napaka, ki bi se pokazala
    // šele na napravi.
    const nastavitve = JSON.parse(readFileSync(join(__dirname, '..', 'app.json'), 'utf8'));

    expect(nastavitve.expo.scheme).toBe(SHEMA);
  });

  it('prenese poševnico pred vprašajem, presledke ob robu in sidro', () => {
    expect(zetonIzPovezave(`school-companion://povezi/?z=${ZETON}`)).toBe(ZETON);
    expect(zetonIzPovezave(`  school-companion://povezi?z=${ZETON}\n`)).toBe(ZETON);
    expect(zetonIzPovezave(`school-companion://povezi?z=${ZETON}#x`)).toBe(ZETON);
  });

  it('druge parametre prezre — tudi naslov strežnika', () => {
    // `ADR-061` C: povezava, ki bi nosila naslov, bi telefon poslala k tujemu
    // strežniku. Aplikacija ga zato sploh ne bere.
    const naslov = `school-companion://povezi?streznik=https%3A%2F%2Fzlo.example&z=${ZETON}`;

    expect(zetonIzPovezave(naslov)).toBe(ZETON);
  });

  it.each([
    ['navadna spletna stran', `https://school-buddy.duckdns.org/povezi?z=${ZETON}`],
    ['druga shema', `drugaaplikacija://povezi?z=${ZETON}`],
    ['druga pot', `school-companion://kvizi?z=${ZETON}`],
    ['pot, ki se samo začne enako', `school-companion://povezitev?z=${ZETON}`],
    ['brez parametra', 'school-companion://povezi'],
    ['prazen žeton', 'school-companion://povezi?z='],
    ['drug parameter', `school-companion://povezi?zeton=${ZETON}`],
    ['prekratek žeton', 'school-companion://povezi?z=abc'],
    ['žeton s presledkom', 'school-companion://povezi?z=aaaaaaaaaaaaaaaa%20bbbbbbbbbbbbbbbb'],
    ['žeton s poševnico', 'school-companion://povezi?z=aaaaaaaaaaaaaaaa%2Fbbbbbbbbbbbbbbbb'],
    ['pokvarjeno kodiranje', 'school-companion://povezi?z=%E0%A4%A'],
    ['golo besedilo', 'Dober dan'],
    ['prazno', ''],
  ])('%s ni naša koda', (_opis, vsebina) => {
    expect(zetonIzPovezave(vsebina)).toBeNull();
  });

  it('predolg niz ni žeton', () => {
    expect(zetonIzPovezave(`school-companion://povezi?z=${'a'.repeat(513)}`)).toBeNull();
    expect(zetonIzPovezave(`school-companion://povezi?z=${'a'.repeat(512)}`)).toBe(
      'a'.repeat(512),
    );
  });
});

describe('oblika žetona', () => {
  it('sprejme znake, iz katerih strežnik sestavi žeton', () => {
    expect(jeZeton(ZETON)).toBe(true);
  });

  it.each([[''], ['kratek'], ['z presledkom v sredini niza'], [null], [undefined], [42]])(
    'zavrne %p',
    (vrednost) => {
      expect(jeZeton(vrednost)).toBe(false);
    },
  );
});
