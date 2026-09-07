/**
 * Expo config plugin: dovoli nešifriran (`http://`) promet v zgrajeni
 * aplikaciji.
 *
 * Zakaj obstaja: Android od `targetSdk` 28 naprej nešifriran promet privzeto
 * blokira. Razvojna gradnja tega ne pokaže, ker predloga React Native doda
 * `android:usesCleartextTraffic="true"` v **debug** manifest; release ga nima.
 * Naslov domačega strežnika je `http://<tailscale>:8000`, zato je Android v
 * prvi zgrajeni APK zavrnil vsak prenos, še preden je šel na omrežje — vsaka
 * slika je ostala v stanju „Čaka na prenos".
 *
 * Zakaj plugin in ne nastavitev: `expo.android.usesCleartextTraffic` v shemi
 * Expo konfiguracije (SDK 57) ni podprt ključ. Uradna pot bi bila paket
 * `expo-build-properties`, kar bi bila nova odvisnost za eno vrstico v
 * manifestu — glej `docs/odlocitve/ADR-010`.
 *
 * Dovoljenje velja za celo aplikacijo, ne le za domači naslov. To je zavestno:
 * edini omrežni klic je v `src/sync/upload.ts` in gre na naslov iz gradnje,
 * varnostna meja sistema pa je Tailscale (`ADR-006`), ne šifriran transport.
 *
 * Datoteka je namenoma `.js`: Expo plugine naloži z navadnim `require`, brez
 * prevoda TypeScripta.
 */

const { AndroidConfig, withAndroidManifest } = require('expo/config-plugins');

/**
 * Postavi zastavico v glavno `<application>` in vrne isti manifest.
 *
 * Ločena od plugina zato, da jo test kliče kot čisto funkcijo, brez zaganjanja
 * gradnje. Glavno aplikacijo poišče uradni pomočnik: če je manifest brez nje,
 * vrže napako — tiho nespremenjen manifest bi pomenil gradnjo, ki uspe, in
 * aplikacijo, ki spet ne prenaša.
 *
 * @param {any} manifest razčlenjen `AndroidManifest.xml`
 * @returns {any} isti manifest, s postavljeno zastavico
 */
function dovoliCleartext(manifest) {
  const aplikacija = AndroidConfig.Manifest.getMainApplicationOrThrow(manifest);
  aplikacija.$['android:usesCleartextTraffic'] = 'true';
  return manifest;
}

/**
 * @param {any} config konfiguracija Expo projekta
 * @returns {any} konfiguracija z dodano spremembo manifesta
 */
const withCleartextTraffic = (config) =>
  withAndroidManifest(config, (nastavitve) => {
    nastavitve.modResults = dovoliCleartext(nastavitve.modResults);
    return nastavitve;
  });

module.exports = withCleartextTraffic;
module.exports.dovoliCleartext = dovoliCleartext;
