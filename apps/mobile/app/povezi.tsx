import { CameraView, useCameraPermissions } from 'expo-camera';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { jeZeton, zetonIzPovezave } from '@/povezava/naslov';
import { usePrijava } from '@/sync/use-prijava';
import { useSync } from '@/sync/use-sync';
import { theme } from '@/ui/theme';

export const SPOROCILO_NI_NASA_KODA =
  'To ni koda Šolskega pomočnika. Prosi starša, naj ti pokaže kodo za povezavo telefona.';

const SPOROCILO_NEPRICAKOVANO = 'Povezava ni uspela. Poskusi znova.';

/**
 * Povezava telefona s QR kodo (V6-R01).
 *
 * En zaslon za obe poti iz `docs/odlocitve/ADR-058` C:
 *
 * - **kamera** prebere QR kodo, ki jo starš pokaže na drugem zaslonu;
 * - **odprta povezava** `school-companion://povezi?z=…` (gumb „Odpri na tem
 *   telefonu") pripelje sem z žetonom v parametru in se unovči takoj.
 *
 * Zaslon in ne vrata, kot je bila prijava (`ADR-036` A): do njega se pride z
 * domače strani, aplikacija pa brez njega dela naprej. Kar povezava odklene,
 * je **prenos**, ne kamera.
 *
 * Omrežja se zaslon ne dotakne sam — unovčenje je v `src/sync/prijava.ts`.
 */
export default function PoveziScreen() {
  const { z } = useLocalSearchParams<{ z?: string }>();
  // Nova povezava v že odprt zaslon je nov začetek: s ključem se zaslon vpne
  // znova in začetno stanje (povezujem, napaka) se izpelje iz novega žetona.
  return <Povezi key={typeof z === 'string' ? z : ''} z={z} />;
}

function Povezi({ z }: { z?: string }) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { povezi } = usePrijava();
  const { nastavljen } = useSync();
  const [permission, requestPermission] = useCameraPermissions();

  // Začetno stanje je izpeljano iz parametra odprte povezave in ne nastavljeno
  // v učinku: veljaven žeton pomeni, da zaslon že ob prvem izrisu povezuje,
  // nekaj, kar po obliki ni žeton, pa je napaka že takrat.
  const [povezujem, setPovezujem] = useState(() => nastavljen && jeZeton(z));
  const [napaka, setNapaka] = useState<string | null>(() =>
    typeof z === 'string' && z.length > 0 && !jeZeton(z) ? SPOROCILO_NI_NASA_KODA : null,
  );

  // Ali zadnji poskus izhaja iz odprte povezave. Dokler je tako, „Poskusi
  // znova" pošlje isti žeton; ko otrok izbere kamero, velja prebrana koda.
  const [izPovezaveVelja, setIzPovezaveVelja] = useState(() => jeZeton(z));
  // Ali zadnja napaka dopušča ponovitev iste kode: samo nedosegljiv strežnik.
  // Zavrnjena koda je mrtva; vsak nov poskus z njo bi štel v mejo poskusov,
  // ki je skupna za vso namestitev (`ADR-061` E).
  const [ponovljivo, setPonovljivo] = useState(false);

  // Zaporo drži referenca: bralnik isto kodo javi večkrat na sekundo in stanje
  // bi se posodobilo šele ob naslednjem izrisu.
  const zaklep = useRef(false);
  // Zadnja vsebina, ki je že dobila odgovor. Dokler je koda pred kamero, jo
  // bralnik javlja znova in znova; brez tega bi ista neveljavna koda sprožila
  // zahtevo ob vsaki sličici — in vsaka bi štela v mejo poskusov na strežniku.
  const obdelano = useRef<string | null>(null);

  // Samo delo: klic, navigacija, sporočilo. Zaporo in napis „Povezujem"
  // postavi klicatelj — bralnik v `unovci`, odprta povezava z začetnim stanjem.
  const izvedi = useCallback(
    async (zeton: string) => {
      try {
        await povezi(zeton);
        // Z domače strani se vrnemo nanjo; povezava, ki je aplikacijo šele
        // odprla, pa za sabo nima ničesar, kamor bi se vrnila.
        if (router.canGoBack()) router.back();
        else router.replace('/');
      } catch (cause: unknown) {
        // Sporočilo je iz `NapakaPrijave` in je v slovenščini; surovo besedilo
        // sistemske napake bi bilo tu edina vsebina, kar merilo dokončanosti
        // prepoveduje, zato ima tudi nepričakovana napaka svoje besedilo.
        const nasa = cause instanceof Error && cause.name === 'NapakaPrijave';
        setPonovljivo(nasa && (cause as { ponovljivo?: unknown }).ponovljivo === true);
        setNapaka(nasa ? cause.message : SPOROCILO_NEPRICAKOVANO);
      } finally {
        zaklep.current = false;
        setPovezujem(false);
      }
    },
    [povezi, router],
  );

  // Zaporo preveri klicatelj (`prebrano`); tu se samo postavi.
  const unovci = useCallback(
    (zeton: string) => {
      zaklep.current = true;
      setNapaka(null);
      setPovezujem(true);
      void izvedi(zeton);
    },
    [izvedi],
  );

  // Odprta povezava: žeton pride kot parameter poti. Unovči se enkrat — ista
  // vrednost ob ponovnem izrisu ne sme sprožiti druge zahteve, ker je žeton
  // enkraten in bi druga zahteva uspešno povezavo pokazala kot neveljavno kodo.
  const izPovezave = useRef<string | null>(null);
  useEffect(() => {
    if (typeof z !== 'string' || z.length === 0 || izPovezave.current === z) return;
    izPovezave.current = z;
    // Kar po obliki ni žeton, ne gre na strežnik; sporočilo je že v stanju.
    if (!nastavljen || !jeZeton(z) || zaklep.current) return;
    zaklep.current = true;
    void izvedi(z);
  }, [izvedi, nastavljen, z]);

  const prebrano = useCallback(
    ({ data }: { data: string }) => {
      if (zaklep.current || obdelano.current === data) return;
      obdelano.current = data;
      const zeton = zetonIzPovezave(data);
      if (zeton === null) {
        setNapaka(SPOROCILO_NI_NASA_KODA);
        return;
      }
      unovci(zeton);
    },
    [unovci],
  );

  const poskusiZnova = useCallback(() => {
    // Ista koda sme znova do strežnika: nedosegljiv strežnik je ni porabil.
    obdelano.current = null;
    // Žeton iz odprte povezave se pošlje znova. Družina z enim telefonom kode
    // ne more prebrati s kamero — gumb „Odpri na tem telefonu" je njena edina
    // pot, in „Poskusi znova" mora zanjo pomeniti prav to.
    if (izPovezaveVelja && ponovljivo && nastavljen && jeZeton(z) && !zaklep.current) {
      unovci(z);
      return;
    }
    setNapaka(null);
  }, [izPovezaveVelja, nastavljen, ponovljivo, unovci, z]);

  const preberiSKamero = useCallback(() => {
    obdelano.current = null;
    setIzPovezaveVelja(false);
    setNapaka(null);
  }, []);

  // Sistemska navigacijska vrstica riše čez vsebino (Android je edge-to-edge),
  // zato besedilo in gumbi potrebujejo odmik, sicer so pod njo.
  const odmikSpodaj = { paddingBottom: theme.spacing + insets.bottom };

  if (!nastavljen) {
    return (
      <View testID="povezi-vsebina" style={[styles.sredina, odmikSpodaj]}>
        <Text testID="prenos-ni-nastavljen" style={styles.napaka}>
          Prenos ni nastavljen, zato telefona ni mogoče povezati. Povej staršu.
        </Text>
      </View>
    );
  }

  if (povezujem) {
    return (
      <View testID="povezi-vsebina" style={[styles.sredina, odmikSpodaj]}>
        <ActivityIndicator color={theme.accent} />
        <Text testID="povezujem" style={styles.pojasnilo}>
          Povezujem telefon…
        </Text>
      </View>
    );
  }

  if (!permission) {
    return (
      <View testID="povezi-vsebina" style={[styles.sredina, odmikSpodaj]}>
        <ActivityIndicator color={theme.accent} />
      </View>
    );
  }

  const sporocilo =
    napaka !== null ? (
      <View style={styles.sporocilo}>
        <Text testID="napaka-povezave" style={styles.napaka}>
          {napaka}
        </Text>
        {/* Po zavrnjeni odprti povezavi ponovitve ni: koda je mrtva in otrok
            potrebuje novo. Ostane kamera, če je na voljo. */}
        {!izPovezaveVelja || ponovljivo ? (
          <Pressable
            accessibilityRole="button"
            testID="gumb-znova"
            style={({ pressed }) => [styles.gumb, pressed && styles.gumbPritisnjen]}
            onPress={poskusiZnova}
          >
            <Text style={styles.gumbNapis}>Poskusi znova</Text>
          </Pressable>
        ) : null}
        {/* Po neuspeli odprti povezavi je druga pot nova koda pred kamero. */}
        {izPovezaveVelja && permission?.granted ? (
          <Pressable
            accessibilityRole="button"
            testID="gumb-kamera"
            style={({ pressed }) => [
              styles.gumb,
              styles.gumbDrugotni,
              pressed && styles.gumbPritisnjen,
            ]}
            onPress={preberiSKamero}
          >
            <Text style={styles.gumbNapis}>Preberi novo kodo s kamero</Text>
          </Pressable>
        ) : null}
      </View>
    ) : (
      <Text testID="navodilo" style={styles.pojasnilo}>
        Prosi starša, naj na spletni strani pri tvojem imenu izbere »Poveži telefon«, in
        usmeri kamero v kodo.
      </Text>
    );

  if (!permission.granted) {
    return (
      <View testID="povezi-vsebina" style={[styles.sredina, odmikSpodaj]}>
        {/* Sporočilo z gumbom tudi tu: odprta povezava kamere ne potrebuje. */}
        {napaka !== null ? sporocilo : null}
        <Text testID="brez-kamere" style={styles.naslov}>
          Potrebujem dovoljenje za kamero
        </Text>
        <Text style={styles.pojasnilo}>
          {permission.canAskAgain
            ? 'Brez dovoljenja ne morem prebrati kode. Dovoljenje lahko daš zdaj.'
            : 'Dovoljenje je zavrnjeno. Vklopiš ga lahko v nastavitvah telefona.'}
        </Text>
        <Pressable
          accessibilityRole="button"
          testID="gumb-dovoljenje"
          style={({ pressed }) => [styles.gumb, pressed && styles.gumbPritisnjen]}
          onPress={() => {
            if (permission.canAskAgain) void requestPermission();
            else void Linking.openSettings();
          }}
        >
          <Text style={styles.gumbNapis}>
            {permission.canAskAgain ? 'Dovoli kamero' : 'Odpri nastavitve'}
          </Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Dokler napaka čaka na „Poskusi znova", bralnik miruje: sicer bi koda,
          ki je še pred kamero, sporočilo takoj prepisala. */}
      <CameraView
        style={styles.kamera}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        onBarcodeScanned={napaka === null ? prebrano : undefined}
      />
      <View testID="povezi-vsebina" style={[styles.spodaj, odmikSpodaj]}>
        {sporocilo}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.background,
  },
  kamera: {
    flex: 1,
  },
  sredina: {
    flex: 1,
    justifyContent: 'center',
    gap: theme.spacing,
    padding: theme.spacing * 1.5,
    backgroundColor: theme.background,
  },
  spodaj: {
    gap: theme.spacing,
    padding: theme.spacing * 1.5,
    backgroundColor: theme.surface,
  },
  sporocilo: {
    gap: theme.spacing,
  },
  naslov: {
    color: theme.text,
    fontSize: 22,
    fontWeight: '600',
    textAlign: 'center',
  },
  pojasnilo: {
    color: theme.textMuted,
    fontSize: 16,
    textAlign: 'center',
  },
  napaka: {
    color: theme.danger,
    fontSize: 16,
    textAlign: 'center',
  },
  gumb: {
    paddingVertical: theme.spacing * 1.25,
    borderRadius: theme.radius,
    backgroundColor: theme.accent,
  },
  gumbDrugotni: {
    backgroundColor: theme.background,
    borderWidth: 1,
    borderColor: theme.border,
  },
  gumbPritisnjen: {
    opacity: 0.7,
  },
  gumbNapis: {
    color: theme.text,
    fontSize: 20,
    fontWeight: '600',
    textAlign: 'center',
  },
});
