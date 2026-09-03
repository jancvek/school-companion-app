import { CameraView, useCameraPermissions } from 'expo-camera';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useReducer, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { captureReducer, initialCaptureState } from '@/capture/session';
import { findSubject } from '@/constants/subjects';
import { asMaterialsDatabase } from '@/db/open';
import { saveCapture } from '@/materials/save';
import { theme } from '@/ui/theme';

export default function CaptureScreen() {
  const router = useRouter();
  const database = useSQLiteContext();
  const { subject: subjectParam } = useLocalSearchParams<{ subject: string }>();
  const subject = findSubject(subjectParam);

  const [permission, requestPermission] = useCameraPermissions();
  const [session, dispatch] = useReducer(captureReducer, initialCaptureState);
  const [busy, setBusy] = useState(false);
  const cameraRef = useRef<CameraView>(null);

  const takePicture = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      const picture = await cameraRef.current?.takePictureAsync();
      if (!picture) {
        throw new Error('Kamera ni vrnila slike.');
      }
      // Čas posnetka, ne čas shranjevanja.
      dispatch({
        type: 'captured',
        photo: { uri: picture.uri, takenAt: new Date().toISOString() },
      });
    } catch (error) {
      Alert.alert('Fotografiranje ni uspelo', opisNapake(error));
    } finally {
      setBusy(false);
    }
  }, [busy]);

  const save = useCallback(async () => {
    if (busy || !session.photo || !subject) return;
    setBusy(true);
    try {
      await saveCapture(asMaterialsDatabase(database), {
        subject: subject.value,
        takenAt: session.photo.takenAt,
        sourceUri: session.photo.uri,
      });
      router.dismissAll();
      Alert.alert('Shranjeno', `Posnetek za ${subject.label} je shranjen.`);
    } catch (error) {
      // Predogled ostane odprt, da posnetek ni izgubljen.
      Alert.alert('Shranjevanje ni uspelo', opisNapake(error));
    } finally {
      setBusy(false);
    }
  }, [busy, database, router, session.photo, subject]);

  if (!subject) {
    return (
      <Message
        title="Neznan predmet"
        body="Ta predmet ni na seznamu. Vrni se in izberi predmet znova."
        actionLabel="Nazaj"
        onAction={() => router.back()}
      />
    );
  }

  if (!permission) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={theme.accent} />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <Message
        title="Potrebujem dovoljenje za kamero"
        body={
          permission.canAskAgain
            ? 'Brez dovoljenja ne morem fotografirati snovi. Dovoljenje lahko daš zdaj.'
            : 'Dovoljenje je zavrnjeno. Vklopiš ga lahko v nastavitvah telefona.'
        }
        actionLabel={permission.canAskAgain ? 'Dovoli kamero' : 'Odpri nastavitve'}
        onAction={() => {
          if (permission.canAskAgain) {
            void requestPermission();
          } else {
            void Linking.openSettings();
          }
        }}
      />
    );
  }

  if (session.photo) {
    return (
      <View style={styles.container}>
        <Stack.Screen options={{ title: 'Predogled' }} />
        <Image
          source={{ uri: session.photo.uri }}
          style={styles.preview}
          resizeMode="contain"
        />
        <View style={styles.actions}>
          <Action label="Ponovi" onPress={() => dispatch({ type: 'retake' })} disabled={busy} />
          <Action label="Shrani" primary onPress={save} disabled={busy} />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: subject.value }} />
      <CameraView ref={cameraRef} style={styles.camera} facing="back" />
      <View style={styles.actions}>
        <Action label="Fotografiraj" primary onPress={takePicture} disabled={busy} />
      </View>
    </View>
  );
}

function opisNapake(error: unknown): string {
  const podrobnost = error instanceof Error ? error.message : String(error);
  return `${podrobnost}\n\nPreveri, ali ima telefon dovolj prostora.`;
}

type ActionProps = {
  label: string;
  onPress: () => void;
  primary?: boolean;
  disabled?: boolean;
};

function Action({ label, onPress, primary, disabled }: ActionProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.action,
        primary && styles.actionPrimary,
        (pressed || disabled) && styles.actionDimmed,
      ]}
    >
      <Text style={styles.actionLabel}>{label}</Text>
    </Pressable>
  );
}

type MessageProps = {
  title: string;
  body: string;
  actionLabel: string;
  onAction: () => void;
};

function Message({ title, body, actionLabel, onAction }: MessageProps) {
  return (
    <View style={styles.centered}>
      <Text style={styles.messageTitle}>{title}</Text>
      <Text style={styles.messageBody}>{body}</Text>
      <Action label={actionLabel} primary onPress={onAction} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.background,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    gap: theme.spacing,
    padding: theme.spacing * 1.5,
    backgroundColor: theme.background,
  },
  camera: {
    flex: 1,
  },
  preview: {
    flex: 1,
    backgroundColor: '#000',
  },
  actions: {
    flexDirection: 'row',
    gap: theme.spacing,
    padding: theme.spacing,
  },
  action: {
    flex: 1,
    paddingVertical: theme.spacing,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  actionPrimary: {
    backgroundColor: theme.accent,
    borderColor: theme.accent,
  },
  actionDimmed: {
    opacity: 0.6,
  },
  actionLabel: {
    color: theme.text,
    fontSize: 17,
    fontWeight: '600',
    textAlign: 'center',
  },
  messageTitle: {
    color: theme.text,
    fontSize: 20,
    fontWeight: '600',
    textAlign: 'center',
  },
  messageBody: {
    color: theme.textMuted,
    fontSize: 16,
    textAlign: 'center',
  },
});
