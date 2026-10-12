/**
 * Povezava, s katero starš poveže otrokov telefon (V6-R01).
 *
 * Isto povezavo nosita QR koda na strani `/admin/family` in gumb „Odpri na
 * tem telefonu" (`docs/odlocitve/ADR-058` C). Tu je samo razčlenjevanje:
 * modul se omrežja ne dotakne in zato ne živi v `src/sync/`.
 *
 * **Povezava nosi samo žeton** (`docs/odlocitve/ADR-061` C). Naslov strežnika
 * ima aplikacija iz gradnje; povezava, ki bi ga nosila, bi bila način, kako
 * telefon poslati k tujemu strežniku — zato se vse razen žetona prezre.
 */

/** Shema aplikacije iz `app.json`; ujemanje varuje test. */
export const SHEMA = 'school-companion';

/** Pot, ki jo `expo-router` razreši v zaslon `app/povezi.tsx`. */
export const POT = 'povezi';

/** Ime parametra z žetonom. */
export const PARAMETER = 'z';

/**
 * Znaki, iz katerih strežnik sestavi žeton (`secrets.token_urlsafe`), in
 * razumna zgornja meja. Kar temu ne ustreza, ni naš žeton in ne gre na
 * strežnik — prebrana koda je vhod od zunaj.
 */
const OBLIKA_ZETONA = /^[A-Za-z0-9_-]{16,512}$/;

const ZACETEK = `${SHEMA}://${POT}`;

/** Ali je niz po obliki žeton, kakršnega izda strežnik. */
export function jeZeton(vrednost: unknown): vrednost is string {
  return typeof vrednost === 'string' && OBLIKA_ZETONA.test(vrednost);
}

/**
 * Žeton iz prebrane kode ali odprte povezave, ali `null`.
 *
 * `null` pomeni „to ni koda Šolskega pomočnika": druga shema, druga pot,
 * brez parametra ali z vrednostjo, ki po obliki ni žeton. Razčlenjuje ročno
 * in ne z `URL`: ta se pri shemah, ki niso `http`, med okolji obnaša
 * različno, in razlika bi se pokazala šele na napravi.
 */
export function zetonIzPovezave(besedilo: string): string | null {
  const naslov = besedilo.trim();
  if (!naslov.startsWith(ZACETEK)) return null;

  let ostanek = naslov.slice(ZACETEK.length);
  if (ostanek.startsWith('/')) ostanek = ostanek.slice(1);
  if (!ostanek.startsWith('?')) return null;

  // Sidro ni del poizvedbe; pari so ločeni z `&`.
  const poizvedba = ostanek.slice(1).split('#')[0];
  for (const par of poizvedba.split('&')) {
    const enacaj = par.indexOf('=');
    if (enacaj === -1 || par.slice(0, enacaj) !== PARAMETER) continue;
    let vrednost: string;
    try {
      vrednost = decodeURIComponent(par.slice(enacaj + 1));
    } catch {
      return null;
    }
    return jeZeton(vrednost) ? vrednost : null;
  }
  return null;
}
