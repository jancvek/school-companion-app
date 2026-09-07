/**
 * Config plugin, ki dovoli nešifriran promet (`docs/odlocitve/ADR-010`).
 *
 * Plugin teče ob gradnji in ne v aplikaciji, zato ga tu preverjamo tam, kjer
 * je preverljiv: nad razčlenjenim manifestom kot čisto funkcijo. Kar test ne
 * more videti, je, ali je plugin sploh registriran — zato zadnji primer bere
 * `app.json`, in zato je pred izdajo obvezna še preverba manifesta v zgrajeni
 * APK.
 */

import appJson from '../app.json';
import withCleartextTraffic, { dovoliCleartext } from '../plugins/with-cleartext-traffic';

type Aplikacija = { $: Record<string, string> };
type Manifest = { manifest: { application: Aplikacija[] } };

function manifestZ(atributi: Record<string, string>): Manifest {
  return {
    manifest: {
      application: [{ $: { 'android:name': '.MainApplication', ...atributi } }],
    },
  };
}

function glavnaAplikacija(manifest: Manifest): Record<string, string> {
  return manifest.manifest.application[0].$;
}

describe('dovoliCleartext', () => {
  it('postavi zastavico, kadar je manifest nima', () => {
    const manifest = manifestZ({});

    dovoliCleartext(manifest);

    expect(glavnaAplikacija(manifest)['android:usesCleartextTraffic']).toBe('true');
  });

  it('prepiše izrecni "false"', () => {
    // Brez prepisa bi bila napaka natanko tam, kjer je bila prvič: gradnja
    // uspe, aplikacija pa ne prenaša.
    const manifest = manifestZ({ 'android:usesCleartextTraffic': 'false' });

    dovoliCleartext(manifest);

    expect(glavnaAplikacija(manifest)['android:usesCleartextTraffic']).toBe('true');
  });

  it('pusti ostale atribute pri miru', () => {
    const manifest = manifestZ({ 'android:label': '@string/app_name' });

    dovoliCleartext(manifest);

    expect(glavnaAplikacija(manifest)['android:label']).toBe('@string/app_name');
    expect(glavnaAplikacija(manifest)['android:name']).toBe('.MainApplication');
  });

  it('vrže napako, kadar glavne aplikacije v manifestu ni', () => {
    // Tiho vrnjen nespremenjen manifest bi pomenil zeleno gradnjo in
    // aplikacijo, ki spet obtiči v „Čaka na prenos".
    const brezGlavne = {
      manifest: { application: [{ $: { 'android:name': '.DrugaAplikacija' } }] },
    };

    expect(() => dovoliCleartext(brezGlavne)).toThrow();
  });
});

describe('registracija plugina', () => {
  it('je v app.json med plugini', () => {
    expect(appJson.expo.plugins).toContain('./plugins/with-cleartext-traffic');
  });

  it('izvožena je funkcija, kot jo Expo pričakuje', () => {
    expect(typeof withCleartextTraffic).toBe('function');
  });
});
