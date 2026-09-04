/**
 * En prenos ene slike na strežnik.
 *
 * To je **edini** modul v aplikaciji, ki se dotakne omrežja. Regresijski test
 * `__tests__/no-network.test.ts` to tudi zahteva: povsod drugod v `app/` in
 * `src/` omrežnega klica ne sme biti.
 *
 * Prenos gre skozi `expo-file-system`, ne skozi `fetch` z `FormData`: datoteko
 * pošlje nativno, naravnost z diska, brez nalaganja v pomnilnik JS, in vrne
 * statusno kodo tudi za odgovore, ki niso 2xx.
 */

import { File, UploadType } from 'expo-file-system';

import type { ServerConfig } from '../config/server';
import type { Material } from '../types';

/**
 * Izid enega poskusa.
 *
 * `pending` in `failed` se ne ločita po tem, kolikokrat je že spodletelo,
 * ampak po tem, ali se stanje more spremeniti samo od sebe (ADR-004).
 */
export type Izid =
  | { vrsta: 'synced' }
  | { vrsta: 'pending'; razlog: string }
  | { vrsta: 'failed'; razlog: string };

/** Kar potrebuje ta modul od `expo-file-system`; v testih se podtakne. */
export type NaloziDatoteko = (
  fileUri: string,
  url: string,
  moznosti: {
    headers: Record<string, string>;
    parameters: Record<string, string>;
  },
) => Promise<{ status: number }>;

/**
 * Kode, ki so 4xx, a pomenijo „poskusi kasneje", ne „ne bo šlo".
 * 408 je potekel čas zahteve, 429 pa prošnja, naj upočasnimo.
 */
const ZACASNE_4XX = new Set([408, 429]);

/** Odloči, kaj status pomeni za zapis v bazi. */
export function razvrstiStatus(status: number): Izid {
  if (status >= 200 && status < 300) {
    // 201 je nov zapis, 200 je zapis, ki je na strežniku že bil. Oboje pomeni,
    // da je slika tam — idempotentnost je uspeh, ne napaka.
    return { vrsta: 'synced' };
  }

  if (status >= 400 && status < 500 && !ZACASNE_4XX.has(status)) {
    return { vrsta: 'failed', razlog: opisStatusa(status) };
  }

  return { vrsta: 'pending', razlog: opisStatusa(status) };
}

/** Sporočilo, ki uporabnici pove, kaj naj naredi — ne le številke. */
function opisStatusa(status: number): string {
  switch (status) {
    case 401:
    case 403:
      return 'Strežnik je zavrnil ključ. Aplikacijo je treba zgraditi znova s pravim ključem.';
    case 413:
      return 'Slika je za strežnik prevelika.';
    case 422:
      return 'Strežnik podatkov o posnetku ni sprejel.';
    case 429:
      return 'Strežnik je zaseden. Poskusim znova čez nekaj časa.';
    default:
      if (status >= 500) {
        return `Strežnik je javil napako (${status}). Poskusim znova čez nekaj časa.`;
      }
      if (status >= 400) {
        return `Strežnik je zahtevo zavrnil (${status}).`;
      }
      return `Nepričakovan odgovor strežnika (${status}).`;
  }
}

/** Napaka, ki jo vrže sam prenos (ni odgovora) — skoraj vedno omrežje. */
function opisIzjeme(napaka: unknown): string {
  const podrobnost = napaka instanceof Error ? napaka.message : String(napaka);
  return `Strežnik ni dosegljiv. Poskusim znova, ko bo telefon v domačem omrežju. (${podrobnost})`;
}

const privzetoNalozi: NaloziDatoteko = async (fileUri, url, moznosti) => {
  const datoteka = new File(fileUri);
  const odgovor = await datoteka.upload(url, {
    httpMethod: 'POST',
    uploadType: UploadType.MULTIPART,
    fieldName: 'file',
    mimeType: 'image/jpeg',
    headers: moznosti.headers,
    parameters: moznosti.parameters,
  });
  return { status: odgovor.status };
};

/**
 * Prenese en zapis. Nikoli ne vrže — vsaka pot se konča z izidom, ker je od
 * njega odvisno, kaj se zapiše v bazo.
 */
export async function prenesi(
  material: Material,
  nastavitve: ServerConfig,
  nalozi: NaloziDatoteko = privzetoNalozi,
): Promise<Izid> {
  try {
    const { status } = await nalozi(material.file_uri, `${nastavitve.baseUrl}/materials`, {
      headers: { 'X-API-Key': nastavitve.apiKey },
      parameters: {
        id: material.id,
        subject: material.subject,
        taken_at: material.taken_at,
      },
    });
    return razvrstiStatus(status);
  } catch (napaka) {
    // Ni odgovora, torej ni sodbe strežnika o vsebini. Zapis ostane v vrsti.
    return { vrsta: 'pending', razlog: opisIzjeme(napaka) };
  }
}
