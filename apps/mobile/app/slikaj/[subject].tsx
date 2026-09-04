import { CameraView, useCameraPermissions } from 'expo-camera';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
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
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { captureReducer, initialCaptureState } from '@/capture/session';
import { findSubject } from '@/constants/subjects';
import { asMaterialsDatabase } from '@/db/open';
import { saveCapture } from '@/materials/save';
import { theme } from '@/ui/theme';

/** Kako dolgo se vidi napis „Shranjeno", preden sam ugasne. */
export const POTRDITEV_MS = 2000;

export default function CaptureScreen() {
  const router = useRouter();
  const database = useSQLiteContext();
  const insets = useSafeAreaInsets();
  const { subject: subjectParam } = useLocalSearchParams<{ subject: string }>();
  const subject = findSubject(subjectParam);

  const [permission, requestPermission] = useCameraPermissions();
  const [session, dispatch] = useReducer(captureReducer, initialCaptureState);
  const [busy, setBusy] = useState(false);
  const [shranjenih, setShranjenih] = useState(0);
  const [potrditev, setPotrditev] = useState(false);

  const cameraRef = useRef<CameraView>(null);
  // Zaporo drži referenca, ker se stanje posodobi šele ob naslednjem izrisu —
  // dva dotika v istem tiku bi sicer oba videla `false`.
  //
  // Zakaj en posnetek ne more dati dveh vrstic, čeprav se zapora po uspehu
  // spet sprosti — obrambi sta dve in nobena ni „izris pride prej":
  //   1. Med shranjevanjem je izrisan `busy = true`, `Pressable` pa `onPress`
  //      ob `disabled` sploh ne pokliče.
  //   2. Ob uspehu tečejo `setShranjenih`, `pokaziPotrditev`,
  //      `dispatch(retake)` in `setBusy(false)` v enem samem sinhronem
  //      zaporedju (med njimi ni `await`), zato jih React združi v en izris.
  //      Izrisanega stanja s hkrati `busy === false` in posnetkom v predogledu
  //      po uspešnem shranjevanju torej ni.
  // Če kdo doda `await` pred `finally` ali odstrani `disabled={busy}`, to
  // sklepanje pade.
  const zaklep = useRef(false);
  const casovnik = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (casovnik.current) clearTimeout(casovnik.current);
    };
  }, []);

  const pokaziPotrditev = useCallback(() => {
    setPotrditev(true);
    if (casovnik.current) clearTimeout(casovnik.current);
    casovnik.current = setTimeout(() => setPotrditev(false), POTRDITEV_MS);
  }, []);

  const takePicture = useCallback(async () => {
    if (zaklep.current) return;
    zaklep.current = true;
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
      Alert.alert('Fotografiranje ni uspelo', opisKamerineNapake(error));
    } finally {
      zaklep.current = false;
      setBusy(false);
    }
  }, []);

  const save = useCallback(async () => {
    const photo = session.photo;
    if (zaklep.current || !photo || !subject) return;

    zaklep.current = true;
    setBusy(true);
    try {
      await saveCapture(asMaterialsDatabase(database), {
        subject: subject.value,
        takenAt: photo.takenAt,
        sourceUri: photo.uri,
      });

      // ADR-003: ostanemo na kameri istega predmeta, da je mogoče zaporedno
      // posneti več strani iste snovi. Potrditev zato ne sme biti modalna.
      setShranjenih((n) => n + 1);
      pokaziPotrditev();
      dispatch({ type: 'retake' });
    } catch (error) {
      // Predogled ostane odprt, da posnetek ni izgubljen, in poskus je mogoč
      // znova.
      Alert.alert('Shranjevanje ni uspelo', opisShranjevalneNapake(error));
    } finally {
      zaklep.current = false;
      setBusy(false);
    }
  }, [database, pokaziPotrditev, session.photo, subject]);

  // Sistemska navigacijska vrstica riše čez vsebino (Android je edge-to-edge),
  // zato gumbi potrebujejo odmik, sicer so pod njo.
  const odmikSpodaj = { paddingBottom: theme.spacing + insets.bottom };

  if (!subject) {
    return (
      <Message
        title="Neznan predmet"
        body="Ta predmet ni na seznamu. Vrni se in izberi predmet znova."
        actionLabel="Nazaj"
        onAction={() => router.back()}
        odmikSpodaj={odmikSpodaj}
      />
    );
  }

  if (!permission) {
    return (
      <View style={[styles.centered, odmikSpodaj]}>
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
        odmikSpodaj={odmikSpodaj}
      />
    );
  }

  const stanje = <Stanje potrditev={potrditev} shranjenih={shranjenih} />;

  if (session.photo) {
    return (
      <View style={styles.container}>
        <Stack.Screen options={{ title: 'Predogled' }} />
        <Image
          source={{ uri: session.photo.uri }}
          style={styles.preview}
          resizeMode="contain"
        />
        <View testID="akcije" style={[styles.actions, odmikSpodaj]}>
          {stanje}
          <View style={styles.buttonRow}>
            <Action
              label="Ponovi"
              onPress={() => dispatch({ type: 'retake' })}
              disabled={busy}
            />
            <Action label="Shrani" primary onPress={save} disabled={busy} />
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: subject.value }} />
      <CameraView ref={cameraRef} style={styles.camera} facing="back" />
      <View testID="akcije" style={[styles.actions, odmikSpodaj]}>
        {stanje}
        <View style={styles.buttonRow}>
          <Action label="Fotografiraj" primary onPress={takePicture} disabled={busy} />
        </View>
      </View>
    </View>
  );
}

function opisNapake(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Surovo sporočilo kamere je v angleščini in samo zase ne pove ničesar. */
function opisKamerineNapake(error: unknown): string {
  return `Poskusi še enkrat. Če se ponovi, zapri in znova odpri aplikacijo.\n\nPodrobnost: ${opisNapake(error)}`;
}

/** Nasvet o prostoru sodi samo k shranjevanju, ne k vsaki napaki. */
function opisShranjevalneNapake(error: unknown): string {
  return `Posnetek ni bil shranjen in ostane v predogledu.\n\nPreveri, ali ima telefon dovolj prostora.\n\nPodrobnost: ${opisNapake(error)}`;
}

type StanjeProps = {
  potrditev: boolean;
  shranjenih: number;
};

/**
 * Napis „Shranjeno" sam ugasne; števec ostane, da je ob hitrem slikanju
 * vidno, koliko strani je dejansko zapisanih.
 */
function Stanje({ potrditev, shranjenih }: StanjeProps) {
  if (!potrditev && shranjenih === 0) return null;

  return (
    <View style={styles.stanje}>
      {potrditev ? <Text style={styles.potrditev}>Shranjeno</Text> : null}
      {shranjenih > 0 ? (
        <Text style={styles.stevec}>V tej seji: {shranjenih}</Text>
      ) : null}
    </View>
  );
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
  odmikSpodaj: { paddingBottom: number };
};

function Message({ title, body, actionLabel, onAction, odmikSpodaj }: MessageProps) {
  return (
    <View style={[styles.centered, odmikSpodaj]}>
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
    gap: theme.spacing * 0.75,
    padding: theme.spacing,
  },
  stanje: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: theme.spacing,
  },
  potrditev: {
    overflow: 'hidden',
    paddingHorizontal: theme.spacing * 0.75,
    paddingVertical: theme.spacing * 0.25,
    borderRadius: theme.radius,
    backgroundColor: theme.accent,
    color: theme.text,
    fontSize: 15,
    fontWeight: '600',
  },
  stevec: {
    color: theme.textMuted,
    fontSize: 15,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: theme.spacing,
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
