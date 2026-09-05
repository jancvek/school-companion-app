import { StyleSheet, Text, View } from 'react-native';

import type { SyncStatus } from '../types';
import { theme } from './theme';

/**
 * Oznaka stanja prenosa na kartici v zgodovini.
 *
 * Besedilo je v slovenščini in pove stanje, ne kode. `synced` dobi svojo
 * oznako in ne praznine — brez nje se „preneseno" ne bi ločilo od „zaslon
 * še ni prebral stanja".
 */

const OZNAKE: Record<SyncStatus, { besedilo: string; barva: string }> = {
  pending: { besedilo: 'Čaka na prenos', barva: theme.textMuted },
  synced: { besedilo: 'Preneseno', barva: theme.accent },
  failed: { besedilo: 'Prenos ni uspel', barva: theme.danger },
};

export type SyncBadgeProps = {
  status: SyncStatus;
};

export function SyncBadge({ status }: SyncBadgeProps) {
  const oznaka = OZNAKE[status];
  if (!oznaka) return null;

  return (
    <View style={styles.ovoj}>
      <View style={[styles.pika, { backgroundColor: oznaka.barva }]} />
      <Text testID={`stanje-prenosa-${status}`} style={styles.besedilo}>
        {oznaka.besedilo}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  ovoj: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing * 0.4,
  },
  pika: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  besedilo: {
    color: theme.textMuted,
    fontSize: 14,
  },
});
