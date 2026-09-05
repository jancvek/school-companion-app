import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { findSubject } from '@/constants/subjects';
import { listBySubject } from '@/db/materials';
import { asMaterialsDatabase } from '@/db/open';
import { useSync } from '@/sync/use-sync';
import type { Material } from '@/types';
import { SyncBadge } from '@/ui/sync-badge';
import { theme } from '@/ui/theme';

export default function HistoryForSubjectScreen() {
  const router = useRouter();
  const database = useSQLiteContext();
  const insets = useSafeAreaInsets();
  const { subject: subjectParam } = useLocalSearchParams<{ subject: string }>();
  const subject = findSubject(subjectParam);
  const { poskusiZnova } = useSync();

  const [materials, setMaterials] = useState<Material[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [osvezitev, setOsvezitev] = useState(0);

  useEffect(() => {
    if (!subject) return;

    let aktiven = true;
    listBySubject(asMaterialsDatabase(database), subject.value)
      .then((vrstice) => {
        if (aktiven) setMaterials(vrstice);
      })
      .catch((cause: unknown) => {
        if (aktiven) setError(cause instanceof Error ? cause.message : String(cause));
      });

    // Zaslon se lahko zapre, preden poizvedba vrne rezultat.
    return () => {
      aktiven = false;
    };
  }, [database, subject, osvezitev]);

  const naPoskusiZnova = useCallback(async () => {
    await poskusiZnova();
    // Vrstice so se v bazi spremenile; seznam mora to pokazati takoj, sicer
    // gumb izgleda, kot da ni naredil ničesar.
    setOsvezitev((n) => n + 1);
  }, [poskusiZnova]);

  const jeKaksenNeuspel = (materials ?? []).some(
    (material) => material.sync_status === 'failed',
  );

  if (!subject) {
    return (
      <View style={styles.centered}>
        <Text style={styles.emptyTitle}>Neznan predmet</Text>
        <Text style={styles.emptyBody} onPress={() => router.back()}>
          Vrni se in izberi predmet s seznama.
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: subject.value }} />
        <Text style={styles.emptyTitle}>Zgodovine ni bilo mogoče prebrati</Text>
        <Text style={styles.emptyBody}>
          Vrni se in poskusi znova. Če se ponovi, zapri in znova odpri
          aplikacijo — shranjeni posnetki ostanejo na telefonu.
        </Text>
        <Text style={styles.emptyDetail}>Podrobnost: {error}</Text>
      </View>
    );
  }

  if (!materials) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: subject.value }} />
        <ActivityIndicator color={theme.accent} />
      </View>
    );
  }

  if (materials.length === 0) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: subject.value }} />
        <Text style={styles.emptyTitle}>Še ni posnetkov</Text>
        <Text style={styles.emptyBody}>
          Za predmet {subject.label} še ni shranjene snovi.
        </Text>
      </View>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: subject.value }} />
      {jeKaksenNeuspel ? (
        <Pressable
          accessibilityRole="button"
          testID="poskusi-znova"
          onPress={() => void naPoskusiZnova()}
          style={({ pressed }) => [styles.retry, pressed && styles.retryPressed]}
        >
          {/* Napis pove „vse", ker `retryFailed` vrne v vrsto neuspele zapise
              vseh predmetov, ne le tega, na katerem gumb stoji. */}
          <Text style={styles.retryLabel}>Poskusi znova prenesti vse neuspele</Text>
        </Pressable>
      ) : null}
      <FlatList
        testID="seznam-posnetkov"
        data={materials}
        keyExtractor={(material) => material.id}
        // Zadnji posnetek bi sicer obtičal pod sistemsko navigacijsko vrstico.
        contentContainerStyle={[styles.list, { paddingBottom: theme.spacing + insets.bottom }]}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Image
              testID="posnetek"
              source={{ uri: item.file_uri }}
              style={styles.thumbnail}
            />
            <View style={styles.podatki}>
              <Text style={styles.takenAt}>{formatTakenAt(item.taken_at)}</Text>
              <SyncBadge status={item.sync_status} />
            </View>
          </View>
        )}
      />
    </>
  );
}

/** ISO 8601 v UTC → berljiv lokalni čas. Ob neveljavnem nizu vrne izvirnik. */
export function formatTakenAt(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  if (Number.isNaN(date.getTime())) return isoTimestamp;
  return date.toLocaleString('sl-SI', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
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
    gap: theme.spacing,
    padding: theme.spacing,
  },
  card: {
    overflow: 'hidden',
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  thumbnail: {
    width: '100%',
    height: 220,
    backgroundColor: '#000',
  },
  podatki: {
    gap: theme.spacing * 0.35,
    padding: theme.spacing * 0.75,
  },
  takenAt: {
    color: theme.textMuted,
    fontSize: 15,
  },
  retry: {
    margin: theme.spacing,
    marginBottom: 0,
    paddingVertical: theme.spacing * 0.75,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.danger,
    backgroundColor: theme.surface,
  },
  retryPressed: {
    opacity: 0.6,
  },
  retryLabel: {
    color: theme.text,
    fontSize: 16,
    fontWeight: '600',
    textAlign: 'center',
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
