import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { usePrijava } from '@/sync/use-prijava';
import { useSync } from '@/sync/use-sync';
import { theme } from '@/ui/theme';

/**
 * Prijava in odjava na telefonu (V3-R04).
 *
 * Zaslon in ne vrata: do njega se pride z domače strani, aplikacija pa brez
 * njega dela naprej (`docs/odlocitve/ADR-036` A). Kar prijava odklene, je
 * **prenos**, ne kamera.
 *
 * Ko je kdo prijavljen, isti zaslon ponudi odjavo — ločenega zanjo ni, ker je
 * to ista stvar z dveh strani in ker je odjava dejanje, ki se zgodi redko.
 */
export default function PrijavaScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { seja, prijavi, odjavi } = usePrijava();
  const { nastavljen } = useSync();

  const [ime, setIme] = useState('');
  const [geslo, setGeslo] = useState('');
  const [napaka, setNapaka] = useState<string | null>(null);
  const [tece, setTece] = useState(false);

  const posljiPrijavo = useCallback(async () => {
    if (tece) return;
    setNapaka(null);
    setTece(true);
    try {
      await prijavi(ime.trim(), geslo);
      // Geslo ne sme ostati v stanju zaslona dlje, kot je nujno.
      setGeslo('');
      router.back();
    } catch (cause: unknown) {
      // Sporočilo je iz `NapakaPrijave` in je v slovenščini; surovo besedilo
      // sistemske napake bi bilo tu edina vsebina, kar merilo dokončanosti
      // prepoveduje, zato ima tudi nepričakovana napaka svoje besedilo.
      setNapaka(
        cause instanceof Error && cause.name === 'NapakaPrijave'
          ? cause.message
          : 'Prijava ni uspela. Poskusi znova.',
      );
    } finally {
      setTece(false);
    }
  }, [geslo, ime, prijavi, router, tece]);

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

  if (seja) {
    return (
      <View
        testID="odjava-vsebina"
        style={[styles.container, { paddingBottom: theme.spacing + insets.bottom }]}
      >
        <Text testID="prijavljen" style={styles.naslov}>
          Prijavljena si kot {seja.ime}.
        </Text>
        <Text style={styles.pojasnilo}>
          Odjava izbriše prijavo s te naprave. Posnetki in odgovori ostanejo na telefonu in
          se prenesejo, ko se spet prijaviš.
        </Text>
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
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        testID="prijava-vsebina"
        contentContainerStyle={[
          styles.vsebina,
          { paddingBottom: theme.spacing + insets.bottom },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.naslov}>Prijavi se</Text>
        <Text style={styles.pojasnilo}>
          Prijava je potrebna samo za prenos na strežnik. Slikaš lahko tudi brez nje —
          posnetki počakajo na telefonu.
        </Text>

        {!nastavljen ? (
          <Text testID="prenos-ni-nastavljen" style={styles.napaka}>
            Prenos ni nastavljen, zato prijava ni mogoča. Povej staršu.
          </Text>
        ) : null}

        <Text style={styles.oznaka}>Uporabniško ime</Text>
        <TextInput
          testID="polje-ime"
          style={styles.polje}
          value={ime}
          onChangeText={setIme}
          autoCapitalize="none"
          autoCorrect={false}
          textContentType="username"
          placeholder="npr. masa"
          placeholderTextColor={theme.textMuted}
        />

        <Text style={styles.oznaka}>Geslo</Text>
        <TextInput
          testID="polje-geslo"
          style={styles.polje}
          value={geslo}
          onChangeText={setGeslo}
          secureTextEntry
          autoCapitalize="none"
          autoCorrect={false}
          textContentType="password"
          onSubmitEditing={() => void posljiPrijavo()}
        />

        {napaka !== null ? (
          <Text testID="napaka-prijave" style={styles.napaka}>
            {napaka}
          </Text>
        ) : null}

        <Pressable
          accessibilityRole="button"
          testID="gumb-prijava"
          disabled={tece || !nastavljen}
          style={({ pressed }) => [
            styles.gumb,
            (pressed || tece || !nastavljen) && styles.gumbPritisnjen,
          ]}
          onPress={() => void posljiPrijavo()}
        >
          <Text style={styles.gumbNapis}>{tece ? 'Prijavljam…' : 'Prijavi se'}</Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.background,
  },
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
  oznaka: {
    marginTop: theme.spacing * 0.5,
    color: theme.textMuted,
    fontSize: 14,
  },
  polje: {
    padding: theme.spacing * 0.75,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
    color: theme.text,
    fontSize: 18,
  },
  napaka: {
    marginTop: theme.spacing * 0.5,
    color: theme.danger,
    fontSize: 15,
  },
  gumb: {
    marginTop: theme.spacing * 1.5,
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
