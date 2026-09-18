import type { ServerConfig } from '@/config/server';
import type { Zahteva } from '@/sync/http';
import {
  glaveSeje,
  KLJUC_SEJE,
  NapakaPrijave,
  odjaviSe,
  pozabiSejo,
  preberiSejo,
  prijaviSe,
  shraniSejo,
} from '@/sync/prijava';

import { SEJA, ustvariShrambo } from './shramba';

const NASTAVITVE: ServerConfig = { baseUrl: 'https://school-buddy.duckdns.org' };

/** Odgovor, kakršnega vrne strežnik na uspešno prijavo. */
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

describe('prijava na telefonu', () => {
  it('pošlje uporabniško ime in geslo kot JSON', async () => {
    const zahteva = odgovori(200, ODGOVOR);

    await prijaviSe(NASTAVITVE, 'masa', 'geslo-otroka', zahteva as unknown as Zahteva);

    const [url, moznosti] = zahteva.mock.calls[0];
    expect(url).toBe('https://school-buddy.duckdns.org/auth/login');
    expect(moznosti.method).toBe('POST');
    expect(moznosti.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(moznosti.body)).toEqual({
      identifier: 'masa',
      password: 'geslo-otroka',
    });
  });

  it('vrne sejo z žetonom, lastnikom in imenom', async () => {
    const seja = await prijaviSe(
      NASTAVITVE,
      'masa',
      'geslo-otroka',
      odgovori(200, ODGOVOR) as unknown as Zahteva,
    );

    expect(seja).toEqual({ zeton: 'nov-zeton', userId: 'u-masa', ime: 'Maša' });
  });

  it('seje sama ne shrani', async () => {
    // Shranjevanje in posvojitev zapisov sta en korak višje (`use-prijava`),
    // da je na enem mestu vidno, da prijava naredi dvoje, ne eno.
    const shramba = ustvariShrambo();

    await prijaviSe(NASTAVITVE, 'masa', 'g', odgovori(200, ODGOVOR) as unknown as Zahteva);

    expect(shramba.vsebina()).toBeUndefined();
  });

  it('zavrnitev pokaže sporočilo strežnika, ne statusne kode', async () => {
    const telo = { detail: 'Ta račun je starševski in se prijavi na spletni strani.' };

    await expect(
      prijaviSe(NASTAVITVE, 'stars@primer.test', 'g', odgovori(401, telo) as unknown as Zahteva),
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

    await expect(
      prijaviSe(NASTAVITVE, 'masa', 'g', zahteva as unknown as Zahteva),
    ).rejects.toThrow(/ime ali geslo/i);
  });

  it('napaka strežnika ni videti kot napačno geslo', async () => {
    // Sicer bi Maša ob okvari strežnika mislila, da je pozabila geslo.
    await expect(
      prijaviSe(NASTAVITVE, 'masa', 'g', odgovori(500, {}) as unknown as Zahteva),
    ).rejects.toThrow(/ni dosegljiv/i);
  });

  it('nedosegljiv strežnik pove, kaj naj uporabnica naredi', async () => {
    const zahteva = jest.fn(async () => {
      throw new Error('Network request failed');
    });

    const napaka = await prijaviSe(
      NASTAVITVE,
      'masa',
      'g',
      zahteva as unknown as Zahteva,
    ).catch((cause: unknown) => cause);

    expect(napaka).toBeInstanceOf(NapakaPrijave);
    // Surovo besedilo sistemske napake ne sme biti edina vsebina sporočila.
    expect((napaka as Error).message).not.toMatch(/Network request failed/);
    expect((napaka as Error).message).toMatch(/posnetki/i);
  });

  it('nerazberljiv odgovor ne postane seja brez žetona', async () => {
    await expect(
      prijaviSe(NASTAVITVE, 'masa', 'g', odgovori(200, { user_id: 'u' }) as unknown as Zahteva),
    ).rejects.toThrow(/nepričakovano/i);
  });

  it('brez nastavljenega naslova pove, da prijava ni mogoča', async () => {
    const zahteva = jest.fn();

    await expect(prijaviSe(null, 'masa', 'g', zahteva as unknown as Zahteva)).rejects.toThrow(
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

  it('odjava pobriše zapis', async () => {
    const shramba = ustvariShrambo(SEJA);

    await pozabiSejo(shramba);

    expect(shramba.vsebina()).toBeUndefined();
  });

  it('odjava ne vrže, tudi če je shramba nedosegljiva', async () => {
    const shramba = ustvariShrambo(SEJA);
    shramba.pokvari();

    await expect(pozabiSejo(shramba)).resolves.toBeUndefined();
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
