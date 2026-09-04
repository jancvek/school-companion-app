import { FlatList, Pressable, StyleSheet, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { SUBJECTS, type Subject } from '@/constants/subjects';
import { theme } from '@/ui/theme';

type Props = {
  onSelect: (subject: Subject) => void;
};

/** Seznam vseh predmetov. Uporabljata ga obe poti — slikanje in zgodovina. */
export function SubjectList({ onSelect }: Props) {
  const insets = useSafeAreaInsets();

  return (
    <FlatList
      data={SUBJECTS}
      keyExtractor={(subject) => subject.value}
      // Zadnji predmet bi sicer obtičal pod sistemsko navigacijsko vrstico.
      contentContainerStyle={[styles.list, { paddingBottom: theme.spacing + insets.bottom }]}
      renderItem={({ item }) => (
        <Pressable
          accessibilityRole="button"
          style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
          onPress={() => onSelect(item)}
        >
          <Text style={styles.label}>{item.label}</Text>
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  list: {
    gap: theme.spacing * 0.75,
    padding: theme.spacing,
  },
  row: {
    padding: theme.spacing,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  rowPressed: {
    opacity: 0.7,
  },
  label: {
    color: theme.text,
    fontSize: 17,
  },
});
