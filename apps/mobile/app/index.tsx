import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { opisVerzije } from '@/config/verzija';
import { useKvizi } from '@/sync/use-kvizi';
import { useSync } from '@/sync/use-sync';
import { theme } from '@/ui/theme';

export default function HomeScreen() {
  const router = useRouter();
  const { nastavljen, povzetek, osvezi } = useSync();
  const { cakajocih, osvezi: osveziKvize } = useKvizi();

  // Števci se osvežijo ob vsakem prihodu na zaslon — po slikanju in po kvizu
  // je to edini trenutek, ko jih uporabnica pogleda.
  useFocusEffect(
    useCallback(() => {
      void osvezi();
      void osveziKvize();
    }, [osvezi, osveziKvize]),
  );

  return (
    <View style={styles.container}>
      <Text style={styles.intro}>Kaj bomo danes?</Text>

      <Pressable
        accessibilityRole="button"
        style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
        onPress={() => router.push('/slikaj')}
      >
        <Text style={styles.buttonLabel}>Slikaj snov</Text>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        style={({ pressed }) => [
          styles.button,
          styles.buttonSecondary,
          pressed && styles.buttonPressed,
        ]}
        onPress={() => router.push('/zgodovina')}
      >
        <Text style={styles.buttonLabel}>Zgodovina</Text>
      </Pressable>

      {/* Vedno viden; kadar kaj čaka, nosi število in poudarjen rob (V2-R02).
          Število pride iz lokalne baze, zato je pravo tudi brez omrežja. */}
      <Pressable
        accessibilityRole="button"
        testID="gumb-kvizi"
        style={({ pressed }) => [
          styles.button,
          styles.buttonSecondary,
          cakajocih > 0 && styles.buttonOznacen,
          pressed && styles.buttonPressed,
        ]}
        onPress={() => router.push('/kvizi')}
      >
        <Text style={styles.buttonLabel}>
          {cakajocih > 0 ? `Kvizi · ${cakajocih}` : 'Kvizi'}
        </Text>
      </Pressable>

      <StanjePrenosa nastavljen={nastavljen} pending={povzetek.pending} failed={povzetek.failed} />

      {/* Katera gradnja je nameščena (V1-R06). Samo izpis — brez dotika, da
          ne tekmuje z gumboma nad sabo. */}
      <Text testID="verzija" style={styles.verzija}>
        {opisVerzije()}
      </Text>
    </View>
  );
}

type StanjePrenosaProps = {
  nastavljen: boolean;
  pending: number;
  failed: number;
};

/**
 * Stanje prenosa na domači strani.
 *
 * Brez modalnih oken in brez zvončkov: ena vrstica, ki pove, ali je kaj še na
 * telefonu. Neuspeli dobijo svojo vrstico, ker se jih drugače ne opazi —
 * števec čakajočih se sam od sebe zmanjšuje, števec neuspelih pa ne.
 */
export function StanjePrenosa({ nastavljen, pending, failed }: StanjePrenosaProps) {
  if (!nastavljen) {
    return (
      <View style={styles.stanje}>
        <Text testID="prenos-ni-nastavljen" style={styles.stanjeBesedilo}>
          Prenos ni nastavljen. Posnetki se shranjujejo na telefon.
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.stanje}>
      <Text testID="stevec-cakajocih" style={styles.stanjeBesedilo}>
        {pending === 0 ? 'Vse preneseno' : `Za prenos: ${pending}`}
      </Text>
      {failed > 0 ? (
        <Text testID="stevec-neuspelih" style={styles.stanjeNapaka}>
          Prenos ni uspel: {failed}. Odpri Zgodovino in poskusi znova.
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    gap: theme.spacing,
    padding: theme.spacing * 1.5,
    backgroundColor: theme.background,
  },
  intro: {
    marginBottom: theme.spacing,
    color: theme.textMuted,
    fontSize: 18,
    textAlign: 'center',
  },
  button: {
    paddingVertical: theme.spacing * 1.25,
    borderRadius: theme.radius,
    backgroundColor: theme.accent,
  },
  buttonSecondary: {
    backgroundColor: theme.surface,
    borderWidth: 1,
    borderColor: theme.border,
  },
  buttonOznacen: {
    borderWidth: 2,
    borderColor: theme.accent,
  },
  buttonPressed: {
    opacity: 0.7,
  },
  buttonLabel: {
    color: theme.text,
    fontSize: 20,
    fontWeight: '600',
    textAlign: 'center',
  },
  stanje: {
    marginTop: theme.spacing,
    gap: theme.spacing * 0.25,
  },
  stanjeBesedilo: {
    color: theme.textMuted,
    fontSize: 15,
    textAlign: 'center',
  },
  stanjeNapaka: {
    color: theme.danger,
    fontSize: 15,
    textAlign: 'center',
  },
  verzija: {
    marginTop: theme.spacing * 1.5,
    color: theme.textMuted,
    fontSize: 12,
    opacity: 0.7,
    textAlign: 'center',
  },
});
