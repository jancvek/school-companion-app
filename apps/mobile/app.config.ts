import type { ConfigContext, ExpoConfig } from 'expo/config';

/**
 * Naslov strežnika in API ključ prideta v aplikacijo **ob gradnji**, iz
 * spremenljivk okolja (Expo naloži `.env` sam). V aplikaciji ni zaslona z
 * nastavitvami — odločitev 10 v `docs/plan/V1-R02.md`.
 *
 * Ključ s tem konča vgrajen v APK. To je zavestno: gre za en družinski ključ,
 * ki od V3-R02 potuje samo prek HTTPS in ga V3-R04 zamenja z žetonom. Cena je,
 * da zamenjava ključa zahteva novo gradnjo.
 *
 * `SERVER_BASE_URL` mora biti `https://`; drugačen naslov aplikacija šteje za
 * nenastavljen prenos (`src/config/server.ts`, `docs/odlocitve/ADR-034` E).
 *
 * Manjkajoča vrednost ni napaka ob gradnji — aplikacija mora delovati tudi
 * brez nastavljenega prenosa (odločitev 11), samo prenašati ne zna.
 *
 * `buildId` je oznaka gradnje EAS (V1-R06). Domača stran jo izpiše, da je s
 * telefona vidno, katera gradnja je nameščena; v razvoju je spremenljivke ni
 * in aplikacija to pove z „razvojna gradnja".
 */
export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: config.name ?? 'Šolski pomočnik',
  slug: config.slug ?? 'school-companion',
  extra: {
    ...config.extra,
    serverBaseUrl: process.env.SERVER_BASE_URL ?? null,
    apiKey: process.env.SERVER_API_KEY ?? null,
    buildId: process.env.EAS_BUILD_ID ?? null,
  },
});
