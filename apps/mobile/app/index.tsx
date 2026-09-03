import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { theme } from '@/ui/theme';

export default function HomeScreen() {
  const router = useRouter();

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
  buttonPressed: {
    opacity: 0.7,
  },
  buttonLabel: {
    color: theme.text,
    fontSize: 20,
    fontWeight: '600',
    textAlign: 'center',
  },
});
