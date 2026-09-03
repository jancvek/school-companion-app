import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Image, StyleSheet, Text, View } from 'react-native';

import { findSubject } from '@/constants/subjects';
import { listBySubject } from '@/db/materials';
import { asMaterialsDatabase } from '@/db/open';
import type { Material } from '@/types';
import { theme } from '@/ui/theme';

export default function HistoryForSubjectScreen() {
  const router = useRouter();
  const database = useSQLiteContext();
  const { subject: subjectParam } = useLocalSearchParams<{ subject: string }>();
  const subject = findSubject(subjectParam);

  const [materials, setMaterials] = useState<Material[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  }, [database, subject]);

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
        <Text style={styles.emptyBody}>{error}</Text>
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
      <FlatList
        data={materials}
        keyExtractor={(material) => material.id}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Image
              testID="posnetek"
              source={{ uri: item.file_uri }}
              style={styles.thumbnail}
            />
            <Text style={styles.takenAt}>{formatTakenAt(item.taken_at)}</Text>
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
  takenAt: {
    padding: theme.spacing * 0.75,
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
});
