import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SQLiteProvider } from 'expo-sqlite';

import { DATABASE_NAME, initializeDatabase } from '@/db/open';
import { theme } from '@/ui/theme';

export default function RootLayout() {
  return (
    <SQLiteProvider databaseName={DATABASE_NAME} onInit={initializeDatabase}>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: theme.surface },
          headerTintColor: theme.text,
          headerBackTitle: 'Nazaj',
          contentStyle: { backgroundColor: theme.background },
        }}
      >
        <Stack.Screen name="index" options={{ title: 'Šolski pomočnik' }} />
        <Stack.Screen name="slikaj/index" options={{ title: 'Izberi predmet' }} />
        <Stack.Screen name="slikaj/[subject]" options={{ title: 'Slikaj snov' }} />
        <Stack.Screen name="zgodovina/index" options={{ title: 'Zgodovina' }} />
        <Stack.Screen name="zgodovina/[subject]" options={{ title: 'Zgodovina' }} />
      </Stack>
    </SQLiteProvider>
  );
}
