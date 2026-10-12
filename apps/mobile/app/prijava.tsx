import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { usePrijava } from '@/sync/use-prijava';
import { theme } from '@/ui/theme';

/**
 * Kdo je povezan na tem telefonu, in odjava (V3-R04, V6-R01).
 *
 * Do `V6-R01` je bil to prijavni obrazec z uporabniškim imenom in geslom.
 * Otrok gesla nima več (`docs/odlocitve/ADR-058`): telefon poveže starš s QR
 * kodo na zaslonu `app/povezi.tsx`, tu pa ostane to, kar se po povezavi še
 * da narediti — odjava in ponovna povezava.
 *
 * Zaslon in ne vrata: aplikacija brez povezave dela naprej (`ADR-036` A).
 */
export default function PrijavaScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { seja, odjavi } = usePrijava();

  const [tece, setTece] = useState(false);

  const posljiOdjavo = useCallback(async () => {
    if (tece) return;
    setTece(true);
    try {
      await odjavi();
      router.back();
    } finally {
      setTece(false);
    }
  }, [odjavi, router, tece]);

  const gumbPovezi = (
    <Pressable
      accessibilityRole="button"
      testID="gumb-povezi"
      disabled={tece}
      style={({ pressed }) => [styles.gumb, (pressed || tece) && styles.gumbPritisnjen]}
      onPress={() => router.push('/povezi')}
    >
      <Text style={styles.gumbNapis}>
        {seja ? 'Poveži znova s QR kodo' : 'Poveži s QR kodo'}
      </Text>
    </Pressable>
  );

  if (seja) {
    return (
      <View
        testID="odjava-vsebina"
        style={[
          styles.container,
          styles.vsebina,
          { paddingBottom: theme.spacing + insets.bottom },
        ]}
      >
        <Text testID="prijavljen" style={styles.naslov}>
          Prijavljena si kot {seja.ime}.
        </Text>
        <Text style={styles.pojasnilo}>
          Odjava izbriše prijavo s te naprave. Posnetki in odgovori ostanejo na telefonu in
          se prenesejo, ko ti starš telefon spet poveže.
        </Text>
        <Text style={styles.pojasnilo}>
          Če aplikacija pravi, da je prijava potekla, prosi starša za novo kodo in telefon
          poveži znova.
        </Text>
        {gumbPovezi}
        <Pressable
          accessibilityRole="button"
          testID="gumb-odjava"
          disabled={tece}
          style={({ pressed }) => [
            styles.gumb,
            styles.gumbDrugotni,
            (pressed || tece) && styles.gumbPritisnjen,
          ]}
          onPress={() => void posljiOdjavo()}
        >
          <Text style={styles.gumbNapis}>{tece ? 'Odjavljam…' : 'Odjavi se'}</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View
      testID="prijava-vsebina"
      style={[
        styles.container,
        styles.vsebina,
        { paddingBottom: theme.spacing + insets.bottom },
      ]}
    >
      <Text testID="ni-povezan" style={styles.naslov}>
        Telefon ni povezan
      </Text>
      <Text style={styles.pojasnilo}>
        Povezava je potrebna samo za prenos na strežnik. Slikaš lahko tudi brez nje —
        posnetki počakajo na telefonu.
      </Text>
      <Text style={styles.pojasnilo}>
        Gesla ne potrebuješ. Prosi starša, naj ti pokaže kodo za povezavo telefona.
      </Text>
      {gumbPovezi}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.background,
  },
  /**
   * Odmik vsebine od robov. Uporabita ga **obe** veji zaslona. Brez tega se
   * besedilo in gumb dotikata levega in desnega roba — edini zaslon v
   * aplikaciji, kjer bi bilo tako.
   *
   * `paddingBottom` vsaka veja prišteje sama, ker mora vanj prišteti še
   * spodnji odmik varnega območja (Android riše edge-to-edge).
   */
  vsebina: {
    gap: theme.spacing * 0.5,
    padding: theme.spacing * 1.5,
  },
  naslov: {
    marginBottom: theme.spacing * 0.5,
    color: theme.text,
    fontSize: 22,
    fontWeight: '600',
  },
  pojasnilo: {
    marginBottom: theme.spacing,
    color: theme.textMuted,
    fontSize: 15,
  },
  gumb: {
    marginTop: theme.spacing * 0.5,
    paddingVertical: theme.spacing * 1.25,
    borderRadius: theme.radius,
    backgroundColor: theme.accent,
  },
  gumbDrugotni: {
    backgroundColor: theme.surface,
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
