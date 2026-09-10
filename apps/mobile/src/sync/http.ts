/**
 * Klic na strežnik s časovno omejitvijo, ki se **vedno** konča.
 *
 * Skupen za oba odjemalca v tej mapi — preverjanje arhiva (V1-R07) in kvize
 * (V2-R02). Do V2-R02 je živel v `izbrisi.ts`; ko ga je potreboval še drugi
 * odjemalec, je dobil svoj modul, da kvizi ne uvažajo iz modula za brisanje.
 * Vedenje se ob premiku ni spremenilo.
 */

export type Odgovor = { ok: boolean; status: number; json(): Promise<unknown> };

/** Kar potrebujemo od `fetch`; v testih se podtakne. */
export type Zahteva = (
  url: string,
  moznosti: {
    method: string;
    headers: Record<string, string>;
    body?: string;
    signal: AbortSignal;
  },
) => Promise<Odgovor>;

/**
 * Omejitev je izpeljana dvojno, enako kot pri prenosu (`upload.ts`):
 * `signal` prekine sam klic, `Promise.race` pa poskrbi, da se ta funkcija
 * konča tudi, če bi `fetch` signal prezrl. Brez druge polovice bi viseč klic
 * pustil zaporo v `ustvariPonavljalnik` postavljeno in ponavljanje bi bilo do
 * ponovnega zagona aplikacije mrtvo.
 */
export async function poslji(
  zahteva: Zahteva,
  url: string,
  moznosti: { method: string; headers: Record<string, string>; body?: string },
  casovnaOmejitevMs: number,
): Promise<Odgovor> {
  const nadzor = new AbortController();
  let ura: ReturnType<typeof setTimeout> | undefined;

  const potek = new Promise<never>((_resolve, reject) => {
    ura = setTimeout(() => {
      nadzor.abort();
      reject(new Error('Strežnik se ni odzval pravočasno.'));
    }, casovnaOmejitevMs);
  });

  try {
    return await Promise.race([
      zahteva(url, { ...moznosti, signal: nadzor.signal }),
      potek,
    ]);
  } finally {
    if (ura !== undefined) clearTimeout(ura);
  }
}
