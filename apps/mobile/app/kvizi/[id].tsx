import * as Crypto from 'expo-crypto';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useSQLiteContext } from 'expo-sqlite';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { OCENE } from '@/constants/ocene';
import { najdiKviz, postavkeKviza, zapisiPoskus } from '@/db/kvizi';
import { asMaterialsDatabase } from '@/db/open';
import { useKvizi } from '@/sync/use-kvizi';
import { usePrijava } from '@/sync/use-prijava';
import type { Ocena, PostavkaKviza } from '@/types';
import { theme } from '@/ui/theme';

type Nalozeno = { ime: string; postavke: PostavkaKviza[] };

/**
 * Reševanje enega kviza (V2-R02): vprašanje → *Pokaži odgovor* → ocena.
 *
 * **Ocena je hkrati „naprej"** (`ADR-014`): gumba „naprej" ni, zato
 * neocenjenega vprašanja ni. Pred razkritjem odgovora gumbov za oceno ni.
 *
 * Kviz se odpre pri **prvi neocenjeni postavki** (`docs/odlocitve/ADR-019` A):
 * zapuščen kviz ostane odprt in se nadaljuje, kjer je Maša ostala. Postavka,
 * odgovorjena že na strežniku, šteje za odgovorjeno (`ADR-019` E).
 *
 * Trije žigi (`ADR-019` D): `shown_at`, ko se vprašanje izriše; `revealed_at`
 * ob dotiku *Pokaži odgovor*; `answered_at` ob oceni.
 */
export default function ResevanjeKvizaScreen() {
  const router = useRouter();
  const database = useSQLiteContext();
  const insets = useSafeAreaInsets();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { odpri, zapri, osvezi, sprozi } = useKvizi();
  const { seja } = usePrijava();
  // Glej `slikaj/[subject].tsx`: optional chaining v odvisnostih ne gre skozi
  // React Compiler.
  const lastnik = seja?.userId ?? null;

  const [kviz, setKviz] = useState<Nalozeno | null>(null);
  const [niga, setNiga] = useState(false);
  const [napaka, setNapaka] = useState<string | null>(null);
  const [razkrito, setRazkrito] = useState(false);
  const [shranjevanjeNiUspelo, setShranjevanjeNiUspelo] = useState(false);

  const pokazanoOb = useRef<string | null>(null);
  const razkritoOb = useRef<string | null>(null);
  /** Zapora proti dvojnemu dotiku; ref in ne stanje, ker mora veljati takoj. */
  const shranjujem = useRef(false);

  // Dokler je zaslon odprt, ga usklajevanje ne pobriše, tudi če ga strežnik
  // ne vrača več — sicer bi Maši izginil pod prsti (`ADR-019` C).
  useEffect(() => {
    if (!id) return;
    odpri(id);
    return () => zapri();
  }, [id, odpri, zapri]);

  useEffect(() => {
    if (!id) return;
    let aktiven = true;
    const db = asMaterialsDatabase(database);

    Promise.all([najdiKviz(db, id), postavkeKviza(db, id)])
      .then(([najden, postavke]) => {
        if (!aktiven) return;
        if (najden === null || postavke.length === 0) {
          setNiga(true);
          return;
        }
        setKviz({ ime: najden.name, postavke });
      })
      .catch((cause: unknown) => {
        if (aktiven) setNapaka(cause instanceof Error ? cause.message : String(cause));
      });

    return () => {
      aktiven = false;
    };
  }, [database, id]);

  const indeks = kviz ? kviz.postavke.findIndex((postavka) => !postavka.odgovorjena) : -1;
  const trenutna = kviz && indeks >= 0 ? kviz.postavke[indeks] : null;
  const trenutnaId = trenutna?.id ?? null;

  // `shown_at` je trenutek, ko se vprašanje izriše — tudi ob nadaljevanju
  // zapuščenega kviza, ker je takrat vprašanje res pred njo.
  useEffect(() => {
    if (trenutnaId === null) return;
    pokazanoOb.current = new Date().toISOString();
    razkritoOb.current = null;
  }, [trenutnaId]);

  const pokaziOdgovor = useCallback(() => {
    razkritoOb.current = new Date().toISOString();
    setRazkrito(true);
  }, []);

  const oceni = useCallback(
    async (ocena: Ocena) => {
      if (!kviz || !trenutna || shranjujem.current) return;
      shranjujem.current = true;
      setShranjevanjeNiUspelo(false);

      const zdaj = new Date().toISOString();
      try {
        await zapisiPoskus(asMaterialsDatabase(database), {
          id: Crypto.randomUUID(),
          quiz_id: trenutna.quiz_id,
          quiz_item_id: trenutna.id,
          mode: 'samoocena',
          rating: ocena,
          shown_at: pokazanoOb.current ?? zdaj,
          revealed_at: razkritoOb.current ?? zdaj,
          answered_at: zdaj,
          uploaded_at: null,
          // Čigav je odgovor (V3-R04). Brez prijave `null`; tak poskus posvoji
          // prva prijava, tuj pa se ne pošlje (`docs/odlocitve/ADR-036` B).
          user_id: lastnik,
        });
      } catch {
        // Ocena ni zapisana, zato vprašanje ostane pred njo in odgovor
        // razkrit — ponoven dotik je ves popravek.
        setShranjevanjeNiUspelo(true);
        shranjujem.current = false;
        return;
      }

      const postavke = kviz.postavke.map((postavka) =>
        postavka.id === trenutna.id ? { ...postavka, odgovorjena: true } : postavka,
      );
      setKviz({ ...kviz, postavke });
      setRazkrito(false);
      shranjujem.current = false;

      void osvezi();
      // Po zadnji oceni ne čakamo petih minut: poskusi naj gredo gor takoj,
      // če je telefon v domačem omrežju.
      if (postavke.every((postavka) => postavka.odgovorjena)) sprozi();
    },
    [database, kviz, lastnik, osvezi, sprozi, trenutna],
  );

  if (!id || niga) {
    return (
      <View style={[styles.centered, { paddingBottom: theme.spacing * 1.5 + insets.bottom }]}>
        <Text style={styles.naslov}>Tega kviza ni na telefonu</Text>
        <Text style={styles.besedilo}>
          Morda je bil medtem umaknjen. Vrni se na seznam kvizov.
        </Text>
        <Gumb oznaka="Nazaj na kvize" onPress={() => router.back()} />
      </View>
    );
  }

  if (napaka) {
    return (
      <View style={[styles.centered, { paddingBottom: theme.spacing * 1.5 + insets.bottom }]}>
        <Text style={styles.naslov}>Kviza ni bilo mogoče odpreti</Text>
        <Text style={styles.besedilo}>
          Vrni se in poskusi znova. Če se ponovi, zapri in znova odpri
          aplikacijo — ocene, ki si jih že dala, ostanejo na telefonu.
        </Text>
        <Text style={styles.podrobnost}>Podrobnost: {napaka}</Text>
      </View>
    );
  }

  if (!kviz) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={theme.accent} />
      </View>
    );
  }

  if (!trenutna) {
    // Brez številk ocen: rezultat je lastnikov, ne Mašin (`ADR-019` B).
    return (
      <View
        testID="konec"
        style={[styles.centered, { paddingBottom: theme.spacing * 1.5 + insets.bottom }]}
      >
        <Stack.Screen options={{ title: kviz.ime }} />
        <Text style={styles.naslov}>Kviz je končan</Text>
        <Text style={styles.besedilo}>
          Hvala! Ocene se prenesejo same, ko bo telefon v domačem omrežju.
        </Text>
        <Gumb oznaka="Nazaj na kvize" onPress={() => router.back()} />
      </View>
    );
  }

  return (
    <View style={styles.zaslon}>
      <Stack.Screen options={{ title: kviz.ime }} />
      <ScrollView contentContainerStyle={styles.vsebina}>
        <Text testID="napredek" style={styles.napredek}>
          {`Vprašanje ${indeks + 1} od ${kviz.postavke.length}`}
        </Text>
        <Text testID="vprasanje" style={styles.vprasanje}>
          {trenutna.question_text}
        </Text>
        {razkrito ? (
          <Text testID="odgovor" style={styles.odgovor}>
            {trenutna.answer_text}
          </Text>
        ) : null}
      </ScrollView>

      {/* Gumbi so ob spodnjem robu, zato prištejejo sistemski odmik — sicer
          bi „Lahko" končal pod navigacijsko vrstico. */}
      <View
        testID="spodnja-vrstica"
        style={[styles.spodaj, { paddingBottom: theme.spacing + insets.bottom }]}
      >
        {shranjevanjeNiUspelo ? (
          <Text testID="napaka-shranjevanja" style={styles.napaka}>
            Ocene ni bilo mogoče shraniti. Pritisni jo še enkrat.
          </Text>
        ) : null}
        {razkrito ? (
          <View style={styles.ocene}>
            {OCENE.map((ocena) => (
              <Gumb
                key={ocena.value}
                oznaka={ocena.label}
                onPress={() => void oceni(ocena.value)}
              />
            ))}
          </View>
        ) : (
          <Gumb oznaka="Pokaži odgovor" poudarjen onPress={pokaziOdgovor} />
        )}
      </View>
    </View>
  );
}

type GumbProps = { oznaka: string; onPress(): void; poudarjen?: boolean };

function Gumb({ oznaka, onPress, poudarjen = false }: GumbProps) {
  return (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.gumb,
        poudarjen && styles.gumbPoudarjen,
        pressed && styles.gumbPritisnjen,
      ]}
      onPress={onPress}
    >
      <Text style={styles.gumbOznaka}>{oznaka}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  zaslon: {
    flex: 1,
    backgroundColor: theme.background,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    gap: theme.spacing * 0.75,
    padding: theme.spacing * 1.5,
    backgroundColor: theme.background,
  },
  vsebina: {
    gap: theme.spacing,
    padding: theme.spacing * 1.25,
  },
  napredek: {
    color: theme.textMuted,
    fontSize: 15,
  },
  vprasanje: {
    color: theme.text,
    fontSize: 22,
    fontWeight: '600',
  },
  odgovor: {
    padding: theme.spacing,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
    color: theme.text,
    fontSize: 19,
  },
  spodaj: {
    gap: theme.spacing * 0.5,
    paddingHorizontal: theme.spacing,
    paddingTop: theme.spacing * 0.5,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  ocene: {
    gap: theme.spacing * 0.5,
  },
  gumb: {
    paddingVertical: theme.spacing * 0.9,
    borderRadius: theme.radius,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  gumbPoudarjen: {
    borderColor: theme.accent,
    backgroundColor: theme.accent,
  },
  gumbPritisnjen: {
    opacity: 0.7,
  },
  gumbOznaka: {
    color: theme.text,
    fontSize: 18,
    fontWeight: '600',
    textAlign: 'center',
  },
  naslov: {
    color: theme.text,
    fontSize: 22,
    fontWeight: '600',
    textAlign: 'center',
  },
  besedilo: {
    color: theme.textMuted,
    fontSize: 16,
    textAlign: 'center',
  },
  podrobnost: {
    color: theme.textMuted,
    fontSize: 13,
    opacity: 0.7,
    textAlign: 'center',
  },
  napaka: {
    color: theme.danger,
    fontSize: 15,
    textAlign: 'center',
  },
});
