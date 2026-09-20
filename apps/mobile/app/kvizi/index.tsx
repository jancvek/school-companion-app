import { Stack, useFocusEffect, useRouter } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { cakajociKvizi } from '@/db/kvizi';
import { asMaterialsDatabase } from '@/db/open';
import { useKvizi } from '@/sync/use-kvizi';
import { usePrijava } from '@/sync/use-prijava';
import type { KvizNaSeznamu } from '@/types';
import { theme } from '@/ui/theme';

/**
 * Kvizi, ki čakajo na reševanje (V2-R02), najstarejši prvi.
 *
 * Rešenega kviza tu ni — po zadnji oceni izgine (`docs/odlocitve/ADR-019` B).
 * Napol rešen ostane in pove, koliko je že odgovorjenega (`ADR-019` A).
 */
export default function KviziScreen() {
  const router = useRouter();
  const database = useSQLiteContext();
  const insets = useSafeAreaInsets();
  const { osvezi } = useKvizi();
  // Seznam je seznam **prijavljenega** otroka (V3-R07): na skupnem telefonu
  // sicer otrok B vidi kvize otroka A — tiste, ki so ostali, ker na njih visi
  // neprenesen tuj poskus (`docs/odlocitve/ADR-036` C, `ADR-039` E).
  const { seja } = usePrijava();
  const lastnik = seja?.userId ?? null;

  const [kvizi, setKvizi] = useState<KvizNaSeznamu[] | null>(null);
  const [napaka, setNapaka] = useState<string | null>(null);

  // Ob vsakem prihodu na zaslon: po rešenem kvizu se Maša vrne sem in kviz
  // mora biti takrat že s seznama.
  useFocusEffect(
    useCallback(() => {
      let aktiven = true;
      cakajociKvizi(asMaterialsDatabase(database), lastnik)
        .then((vrstice) => {
          if (aktiven) setKvizi(vrstice);
        })
        .catch((cause: unknown) => {
          if (aktiven) setNapaka(cause instanceof Error ? cause.message : String(cause));
        });
      void osvezi();

      return () => {
        aktiven = false;
      };
    }, [database, lastnik, osvezi]),
  );

  if (napaka) {
    return (
      <View style={styles.centered}>
        <Text style={styles.emptyTitle}>Kvizov ni bilo mogoče prebrati</Text>
        <Text style={styles.emptyBody}>
          Vrni se in poskusi znova. Če se ponovi, zapri in znova odpri
          aplikacijo — ocene, ki si jih že dala, ostanejo na telefonu.
        </Text>
        <Text style={styles.emptyDetail}>Podrobnost: {napaka}</Text>
      </View>
    );
  }

  if (!kvizi) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={theme.accent} />
      </View>
    );
  }

  if (kvizi.length === 0) {
    return (
      <View style={styles.centered}>
        <Text style={styles.emptyTitle}>Ni kvizov</Text>
        <Text style={styles.emptyBody}>
          Trenutno te ne čaka noben kviz. Ko bo objavljen nov, se pokaže tukaj.
        </Text>
      </View>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: 'Kvizi' }} />
      <FlatList
        testID="seznam-kvizov"
        data={kvizi}
        keyExtractor={(kviz) => kviz.id}
        // Zadnji kviz bi sicer obtičal pod sistemsko navigacijsko vrstico.
        contentContainerStyle={[styles.list, { paddingBottom: theme.spacing + insets.bottom }]}
        renderItem={({ item }) => (
          <Pressable
            accessibilityRole="button"
            testID="kviz"
            style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
            onPress={() => router.push({ pathname: '/kvizi/[id]', params: { id: item.id } })}
          >
            <Text style={styles.ime}>{item.name}</Text>
            {/* Oblika z dvopičjem je pravilna pri vsakem številu — brez
                sklanjanja, ki bi ga telefon moral znati sam. */}
            <Text style={styles.opis}>
              {item.odgovorjenih > 0
                ? `Odgovorjenih: ${item.odgovorjenih} od ${item.vprasanj}`
                : `Vprašanj: ${item.vprasanj}`}
            </Text>
          </Pressable>
        )}
      />
    </>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    justifyContent: 'center',
    gap: theme.spacing * 0.5,
    padding: theme.spacing * 1.5,
    backgroundColor: theme.background,
  },
  list: {
    gap: theme.spacing * 0.75,
    padding: theme.spacing,
  },
  row: {
    gap: theme.spacing * 0.25,
    padding: theme.spacing,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  rowPressed: {
    opacity: 0.7,
  },
  ime: {
    color: theme.text,
    fontSize: 17,
    fontWeight: '600',
  },
  opis: {
    color: theme.textMuted,
    fontSize: 15,
  },
  emptyTitle: {
    color: theme.text,
    fontSize: 20,
    fontWeight: '600',
    textAlign: 'center',
  },
  emptyBody: {
    color: theme.textMuted,
    fontSize: 16,
    textAlign: 'center',
  },
  emptyDetail: {
    color: theme.textMuted,
    fontSize: 13,
    opacity: 0.7,
    textAlign: 'center',
  },
});
