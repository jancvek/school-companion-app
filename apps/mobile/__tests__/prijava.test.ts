import type { ServerConfig } from '@/config/server';
import type { Zahteva } from '@/sync/http';
import {
  glaveSeje,
  KLJUC_SEJE,
  NapakaPrijave,
  odjaviSe,
  poveziSe,
  pozabiSejo,
  preberiSejo,
  shraniSejo,
  SPOROCILO_KODA_NE_VELJA,
} from '@/sync/prijava';

import { SEJA, ustvariShrambo } from './shramba';

const NASTAVITVE: ServerConfig = { baseUrl: 'https://school-buddy.duckdns.org' };

/** Povezovalni žeton, kakršnega nosi QR koda. */
const ZETON = 'aB3_dE6-gH9jKlMnOpQrStUvWxYz0123456789-_AbC';

/** Odgovor, kakršnega vrne strežnik na uspešno povezavo. */
const ODGOVOR = {
  token: 'nov-zeton',
  user_id: 'u-masa',
  display_name: 'Maša',
  expires_at: '2026-10-18T10:00:00+00:00',
};

function odgovori(status: number, telo: unknown): jest.Mock {
  return jest.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => telo,
  }));
}

describe('povezava telefona', () => {
  // Do `V6-R01` je ta razdelek dokazoval prijavo z uporabniškim imenom in
  // geslom (`POST /auth/login`). Otrok gesla nima več (`ADR-058`): sejo dobi z
  // enkratnim žetonom iz QR kode. Kar se je dokazovalo o seji in o
  // sporočilih, se dokazuje naprej.
  it('pošlje žeton kot JSON na pot povezave', async () => {
    const zahteva = odgovori(200, ODGOVOR);

    await poveziSe(NASTAVITVE, ZETON, zahteva as unknown as Zahteva);

    const [url, moznosti] = zahteva.mock.calls[0];
    expect(url).toBe('https://school-buddy.duckdns.org/auth/link');
    expect(moznosti.method).toBe('POST');
    expect(moznosti.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(moznosti.body)).toEqual({ token: ZETON });
  });

  it('žetona ne da v naslov', async () => {
    // Naslov konča v dnevnikih strežnika in posrednikov; telo ne.
    const zahteva = odgovori(200, ODGOVOR);

    await poveziSe(NASTAVITVE, ZETON, zahteva as unknown as Zahteva);

    expect(zahteva.mock.calls[0][0]).not.toContain(ZETON);
  });

  it('vrne sejo z žetonom, lastnikom in imenom', async () => {
    const seja = await poveziSe(NASTAVITVE, ZETON, odgovori(200, ODGOVOR) as unknown as Zahteva);

    expect(seja).toEqual({ zeton: 'nov-zeton', userId: 'u-masa', ime: 'Maša' });
  });

  it('seje sama ne shrani', async () => {
    // Shranjevanje in posvojitev zapisov sta en korak višje (`use-prijava`),
    // da je na enem mestu vidno, da povezava naredi dvoje, ne eno.
    const shramba = ustvariShrambo();

    await poveziSe(NASTAVITVE, ZETON, odgovori(200, ODGOVOR) as unknown as Zahteva);

    expect(shramba.vsebina()).toBeUndefined();
  });

  it('zavrnjena koda pokaže sporočilo strežnika, ne statusne kode', async () => {
    const telo = { detail: 'Koda ne velja več. Prosi starša za novo.' };

    await expect(
      poveziSe(NASTAVITVE, ZETON, odgovori(401, telo) as unknown as Zahteva),
    ).rejects.toMatchObject({
      name: 'NapakaPrijave',
      message: telo.detail,
    });
  });

  it('zavrnitev brez razumljivega telesa dobi svoje besedilo', async () => {
    const zahteva = jest.fn(async () => ({
      ok: false,
      status: 401,
      json: async () => {
        throw new Error('ni JSON');
      },
    }));

    await expect(poveziSe(NASTAVITVE, ZETON, zahteva as unknown as Zahteva)).rejects.toThrow(
      SPOROCILO_KODA_NE_VELJA,
    );
    expect(SPOROCILO_KODA_NE_VELJA).toMatch(/prosi starša/i);
  });

  it.each([
    [404, { detail: 'Not Found' }],
    [405, { detail: 'Method Not Allowed' }],
    [422, { detail: [{ msg: 'String should have at least 1 character' }] }],
  ])('odgovor %i ne pokaže surovega besedila ogrodja', async (status, telo) => {
    // Strežnik, ki poti še nima, ali telo, ki ga ne sprejme, odgovori v
    // angleščini. Tega otrok ne sme videti kot edine vsebine (merilo
    // dokončanosti); pokaže se samo besedilo, ki ga je napisala pot povezave.
    const napaka = await poveziSe(
      NASTAVITVE,
      ZETON,
      odgovori(status, telo) as unknown as Zahteva,
    ).catch((cause: unknown) => cause);

    expect(napaka).toBeInstanceOf(NapakaPrijave);
    expect((napaka as Error).message).toMatch(/nepričakovano/i);
    expect((napaka as Error).message).not.toMatch(/Not Found|Not Allowed|String should/);
  });

  it.each([500, 502, 503, 408, 429])(
    'odgovor %i ni videti kot neveljavna koda',
    async (status) => {
      // Sicer bi otrok ob okvari strežnika prosil za novo kodo, čeprav stara
      // še velja.
      await expect(
        poveziSe(NASTAVITVE, ZETON, odgovori(status, {}) as unknown as Zahteva),
      ).rejects.toThrow(/ni dosegljiv/i);
    },
  );

  it('nedosegljiv strežnik pove, kaj naj uporabnica naredi', async () => {
    const zahteva = jest.fn(async () => {
      throw new Error('Network request failed');
    });

    const napaka = await poveziSe(NASTAVITVE, ZETON, zahteva as unknown as Zahteva).catch(
      (cause: unknown) => cause,
    );

    expect(napaka).toBeInstanceOf(NapakaPrijave);
    // Surovo besedilo sistemske napake ne sme biti edina vsebina sporočila.
    expect((napaka as Error).message).not.toMatch(/Network request failed/);
    expect((napaka as Error).message).toMatch(/posnetki/i);
    expect((napaka as Error).message).toMatch(/poskusi znova/i);
  });

  it('nerazberljiv odgovor ne postane seja brez žetona', async () => {
    await expect(
      poveziSe(NASTAVITVE, ZETON, odgovori(200, { user_id: 'u' }) as unknown as Zahteva),
    ).rejects.toThrow(/nepričakovano/i);
  });

  it('brez nastavljenega naslova pove, da povezava ni mogoča', async () => {
    const zahteva = jest.fn();

    await expect(poveziSe(null, ZETON, zahteva as unknown as Zahteva)).rejects.toThrow(
      /ni nastavljen/i,
    );
    expect(zahteva).not.toHaveBeenCalled();
  });
});

describe('shramba seje', () => {
  it('kar shrani, tudi prebere', async () => {
    const shramba = ustvariShrambo();

    await shraniSejo(SEJA, shramba);

    expect(await preberiSejo(shramba)).toEqual(SEJA);
  });

  it('prazna shramba vrne null in ne vrže', async () => {
    expect(await preberiSejo(ustvariShrambo())).toBeNull();
  });

  it('nedosegljiva shramba pomeni neprijavljeno aplikacijo, ne okvare', async () => {
    // Naprava brez zaslonskega zaklepa ali poškodovan ključ ne smeta pomeniti,
    // da aplikacije ni mogoče uporabiti (`docs/odlocitve/ADR-036` A).
    const shramba = ustvariShrambo(SEJA);
    shramba.pokvari();

    expect(await preberiSejo(shramba)).toBeNull();
  });

  it('pokvarjen zapis v shrambi vrne null', async () => {
    const shramba = ustvariShrambo();
    await shramba.setItemAsync(KLJUC_SEJE, '{to ni json');

    expect(await preberiSejo(shramba)).toBeNull();
  });

  it('zapis brez žetona ni seja', async () => {
    // Zapis iz starejše različice aplikacije ne sme postati polovična seja.
    const shramba = ustvariShrambo();
    await shramba.setItemAsync(KLJUC_SEJE, JSON.stringify({ userId: 'u', ime: 'Maša' }));

    expect(await preberiSejo(shramba)).toBeNull();
  });

  it('odjava pobriše zapis in to potrdi', async () => {
    const shramba = ustvariShrambo(SEJA);

    await expect(pozabiSejo(shramba)).resolves.toBe(true);

    expect(shramba.vsebina()).toBeUndefined();
  });

  it('odjava ne vrže, tudi če je shramba nedosegljiva — pove pa, da ni uspela', async () => {
    // Izid potrebuje klicatelj: ob neuspehu žeton ostane na disku in ga mora
    // naslednji zagon prepoznati kot ostanek (`docs/odlocitve/ADR-037`).
    const shramba = ustvariShrambo(SEJA);
    shramba.pokvari();

    await expect(pozabiSejo(shramba)).resolves.toBe(false);
  });
});

describe('glava, s katero se telefon izkaže', () => {
  it('je Bearer z žetonom seje', () => {
    expect(glaveSeje(SEJA)).toEqual({ Authorization: `Bearer ${SEJA.zeton}` });
  });
});

describe('odjava na strežniku', () => {
  it('pošlje žeton na pot odjave', async () => {
    const zahteva = odgovori(200, { logged_out: true });

    await odjaviSe(NASTAVITVE, SEJA, zahteva as unknown as Zahteva);

    const [url, moznosti] = zahteva.mock.calls[0];
    expect(url).toBe('https://school-buddy.duckdns.org/auth/logout');
    expect(moznosti.headers['Authorization']).toBe(`Bearer ${SEJA.zeton}`);
  });

  it('nedosegljiv strežnik ne vrže', async () => {
    // Odjava je najprej lokalna: strežnik, ki ne odgovori, ne sme pustiti
    // otroka prijavljenega na napravi (`docs/odlocitve/ADR-036` G).
    const zahteva = jest.fn(async () => {
      throw new Error('Network request failed');
    });

    await expect(
      odjaviSe(NASTAVITVE, SEJA, zahteva as unknown as Zahteva),
    ).resolves.toBeUndefined();
  });

  it('zavrnjen žeton ne vrže', async () => {
    await expect(
      odjaviSe(NASTAVITVE, SEJA, odgovori(401, {}) as unknown as Zahteva),
    ).resolves.toBeUndefined();
  });
});
