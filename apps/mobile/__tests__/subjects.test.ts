import { SUBJECTS, findSubject } from '@/constants/subjects';

const PRICAKOVAN_VRSTNI_RED = [
  'NAR',
  'MAT',
  'TJA',
  'GEO',
  'SLJ',
  'LUM',
  'ZGO',
  'TIT',
  'DKE',
  'GUM',
];

describe('konstanta predmetov', () => {
  it('ima natanko deset predmetov v dogovorjenem vrstnem redu', () => {
    expect(SUBJECTS.map((subject) => subject.value)).toEqual(PRICAKOVAN_VRSTNI_RED);
  });

  it('nima podvojenih kod', () => {
    const kode = SUBJECTS.map((subject) => subject.value);
    expect(new Set(kode).size).toBe(kode.length);
  });

  it('ima za vsak predmet oznako, ki se začne s kodo', () => {
    for (const subject of SUBJECTS) {
      expect(subject.label.startsWith(`${subject.value} — `)).toBe(true);
    }
  });

  it('najde predmet po kodi in vrne undefined za neznano kodo', () => {
    expect(findSubject('MAT')?.label).toBe('MAT — Matematika');
    expect(findSubject('XXX')).toBeUndefined();
    expect(findSubject(undefined)).toBeUndefined();
  });
});
