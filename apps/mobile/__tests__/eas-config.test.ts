/**
 * `eas.json` — kako EAS določi verzijo gradnje (V1-R06, peti kriterij).
 *
 * Te nastavitve bere izključno EAS CLI ob gradnji; v aplikaciji se nikoli ne
 * izvedejo, zato jih noben drug test ne bi opazil. Isti razred napake kot pri
 * `ADR-010`: gradnja uspe, na telefonu pa je narobe — takrat je bil to
 * nešifriran promet, tu bi bili trije APK z istim `versionCode`, ki jih
 * Android obravnava kot isto gradnjo.
 *
 * Kar ta test ne more videti, je, ali je EAS nastavitev tudi upošteval. To
 * pokaže šele številka gradnje v EAS in `versionCode` v zgrajeni APK
 * (faza 9b).
 */

import easJson from '../eas.json';

describe('eas.json — vir verzije', () => {
  it('verzijo hrani EAS, ne repozitorij', () => {
    // Pri `local` bi bila številka v `app.json`, ki je nihče ne poveča —
    // natanko stanje, ki je povzročilo V1-R06: dve gradnji, oba `versionCode` 1.
    expect(easJson.cli.appVersionSource).toBe('remote');
  });

  it('profil preview sam poveča versionCode', () => {
    expect(easJson.build.preview.autoIncrement).toBe(true);
  });
});

describe('eas.json — profil preview (regresija ADR-010)', () => {
  it('ostane interna APK gradnja v okolju preview', () => {
    // Popravek V1-R06 se je dotaknil istega profila. Če bi pri tem odpadlo
    // `environment`, bi gradnja ostala brez naslova strežnika in ključa, in
    // aplikacija spet ne bi prenašala — brez ene same rdeče vrstice drugje.
    expect(easJson.build.preview).toMatchObject({
      distribution: 'internal',
      environment: 'preview',
      android: { buildType: 'apk' },
    });
  });

  it('profil se imenuje preview, kot ga kliče gradnja', () => {
    expect(Object.keys(easJson.build)).toContain('preview');
  });
});
