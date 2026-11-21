import * as React from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { useQueryClient } from '@tanstack/react-query'
import { useAudioRecorder, useAudioRecorderState } from 'expo-audio'
import { Building2, Keyboard, Mic, Send, X } from 'lucide-react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useWords } from '../src/lib/i18n'
import { fileBody, ApiError } from '../src/lib/api'
import { useOutbox, type Sent } from '../src/lib/outbox'
import { sendTap, type AssistantReply, type AssistantResponse } from '../src/lib/mesiri'
import { contentTypeOf, doneRecording, level, MAX_SECONDS, readyToRecord, VOICE_NOTE } from '../src/lib/recorder'
import { useSite } from '../src/lib/session'
import { Screen } from '../src/components/ui'
import { colors, font, MAIN_ACTION, radius, space, TOUCH } from '../src/theme'

// Speak to Mesiri: the same assistant as WhatsApp, through the dashboard's Tell Mesiri door. A voice note or
// a typed line prepares entries; nothing is saved until the person taps the assistant's own Save button.
// One screen, one conversation: what they said on the right, Mesiri's replies (and buttons) on the left.

type Phase = 'starting' | 'recording' | 'sending' | 'idle'

interface Turn {
  id: number
  said: string | null
  kind: 'voice' | 'text' | 'tap'
  replies: AssistantReply[]
  pending: boolean
  error?: string
  chose?: string
  /** MOB-07: kept on the phone (no signal); its answer comes on Today. */
  queued?: boolean
}

const BARS = 28

export default function Speak() {
  const { t } = useWords()
  const router = useRouter()
  const insets = useSafeAreaInsets()
  const client = useQueryClient()
  const { current } = useSite()
  const params = useLocalSearchParams<{ typing?: string; from?: string }>()
  const outbox = useOutbox()
  const placeLabel = current ? `${current.project.name} · ${current.site.name}` : ''
  const recorder = useAudioRecorder(VOICE_NOTE)
  const state = useAudioRecorderState(recorder, 150)
  const [phase, setPhase] = React.useState<Phase>(params.typing || params.from ? 'idle' : 'starting')
  const [typing, setTyping] = React.useState(!!params.typing)
  const [draft, setDraft] = React.useState('')
  const [turns, setTurns] = React.useState<Turn[]>([])
  const [levels, setLevels] = React.useState<number[]>(() => Array(BARS).fill(0.1))
  const [notice, setNotice] = React.useState<string | null>(null)
  const nextId = React.useRef(1)
  const scroll = React.useRef<ScrollView>(null)

  // The bars follow the voice.
  React.useEffect(() => {
    if (phase !== 'recording') return
    setLevels((old) => [...old.slice(1), level(state.metering)])
  }, [state.durationMillis, state.metering, phase])

  const seconds = Math.floor((state.durationMillis ?? 0) / 1000)

  const run = React.useCallback(
    async (turn: Omit<Turn, 'id' | 'replies' | 'pending'>, call: () => Promise<AssistantResponse | Sent>) => {
      const id = nextId.current++
      setTurns((old) => [...old, { ...turn, id, replies: [], pending: true }])
      try {
        const got = await call()
        if ('status' in got && got.status === 'queued') {
          setTurns((old) => old.map((x) => (x.id === id ? { ...x, pending: false, queued: true } : x)))
          return
        }
        const res = 'status' in got ? got.answer : got
        if (!res) return
        setTurns((old) =>
          old.map((x) => (x.id === id ? { ...x, pending: false, replies: res.replies, said: res.transcript ?? x.said } : x)),
        )
        // Whatever was saved shows on Today and Site at once.
        void client.invalidateQueries({ queryKey: ['site-day'] })
        void client.invalidateQueries({ queryKey: ['stock'] })
        void client.invalidateQueries({ queryKey: ['requests'] })
      } catch (e) {
        const message = e instanceof ApiError ? e.message : String(e)
        setTurns((old) => old.map((x) => (x.id === id ? { ...x, pending: false, error: message } : x)))
      } finally {
        setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50)
      }
    },
    [client],
  )

  const start = React.useCallback(async () => {
    setNotice(null)
    setPhase('starting')
    try {
      if (!(await readyToRecord())) {
        setNotice(t.micDenied)
        setTyping(true)
        setPhase('idle')
        return
      }
      await recorder.prepareToRecordAsync()
      recorder.record({ forDuration: MAX_SECONDS })
      setLevels(Array(BARS).fill(0.1))
      setPhase('recording')
    } catch {
      setNotice(t.micDenied)
      setTyping(true)
      setPhase('idle')
    }
  }, [recorder, t])

  const stop = React.useCallback(async () => {
    setPhase('sending')
    try {
      await recorder.stop()
    } finally {
      void doneRecording()
    }
    const uri = recorder.uri
    if (!uri) {
      setPhase('idle')
      return
    }
    const length = (state.durationMillis ?? 0) / 1000
    await run({ said: null, kind: 'voice' }, async () => {
      // Phones record m4a; only the web build needs to look at the file to know.
      const type = Platform.OS === 'web' ? contentTypeOf(await fileBody(uri)) : 'audio/mp4'
      return outbox.sendVoice(uri, type, length, placeLabel)
    })
    setPhase('idle')
  }, [recorder, run, outbox, placeLabel, state.durationMillis])

  // Opening the screen starts listening, like pressing a walkie-talkie; opened from Today on a note's later answer
  // (MOB-07), it shows that answer, its buttons live.
  React.useEffect(() => {
    if (params.from) {
      const item = outbox.take(params.from)
      if (item?.answer) {
        setTurns([
          {
            id: nextId.current++,
            said: item.answer.transcript ?? item.text ?? null,
            kind: item.kind === 'text' ? 'text' : 'voice',
            replies: item.answer.replies,
            pending: false,
          },
        ])
      }
      return
    }
    if (!params.typing) void start()
    return () => {
      void doneRecording()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The door's one-minute limit: stop and send by itself.
  React.useEffect(() => {
    if (phase === 'recording' && !state.isRecording && (state.durationMillis ?? 0) > 500) void stop()
  }, [phase, state.isRecording, state.durationMillis, stop])

  const sendTyped = async () => {
    const text = draft.trim()
    if (!text) return
    setDraft('')
    await run({ said: text, kind: 'text' }, () => outbox.sendText(text, placeLabel))
  }

  const tap = (turnId: number, optionId: string, title: string) => {
    setTurns((old) => old.map((x) => (x.id === turnId ? { ...x, chose: title } : x)))
    void run({ said: title, kind: 'tap' }, () => sendTap(optionId))
  }

  const close = async () => {
    if (phase === 'recording') {
      try {
        await recorder.stop()
      } catch {
        // already stopped
      }
      void doneRecording()
    }
    if (router.canGoBack()) router.back()
    else router.replace('/')
  }

  const busy = turns.some((x) => x.pending)
  const listening = phase === 'recording' || phase === 'starting'

  return (
    <Screen dark>
      <View style={styles.top}>
        <Pressable accessibilityRole="button" accessibilityLabel={t.close} onPress={close} style={styles.round}>
          <X size={22} color="#fff" />
        </Pressable>
        <View style={styles.sitePill}>
          <Building2 size={16} color={colors.brand} />
          <Text style={{ color: colors.nightText, fontSize: 13 }} numberOfLines={1}>
            {current ? `${current.project.name} · ${current.site.name}` : ''}
          </Text>
        </View>
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView ref={scroll} contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          {turns.length === 0 ? (
            <View style={{ gap: space.md }}>
              <Text style={[styles.status, { textAlign: 'center' }]}>
                {listening ? `${t.listening} · 0:${String(seconds).padStart(2, '0')}` : t.speakNow}
              </Text>
              <View style={{ gap: space.sm }}>
                <Text style={{ color: colors.nightMuted, fontSize: 13 }}>{t.sayInOneGo}</Text>
                <View style={styles.hints}>
                  {t.hints.map((h) => (
                    <View key={h} style={styles.hint}>
                      <Text style={{ color: colors.nightText, fontSize: 13 }}>{h}</Text>
                    </View>
                  ))}
                </View>
              </View>
            </View>
          ) : null}

          {turns.map((turn) => (
            <View key={turn.id} style={{ gap: space.sm }}>
              <View style={styles.saidBubble}>
                <Text style={styles.saidLabel}>{turn.kind === 'tap' ? '✓' : t.youSaid}</Text>
                <Text style={styles.saidText}>{turn.said ?? (turn.pending ? t.hearing : turn.queued ? t.voiceNote : '—')}</Text>
              </View>
              {turn.pending ? <Text style={styles.thinking}>{t.thinking}</Text> : null}
              {turn.queued ? (
                <View style={[styles.reply, { backgroundColor: colors.nightCard, borderColor: colors.charcoal }]}>
                  <Text style={[font.body, { color: colors.nightText }]}>{t.keptOnPhone}</Text>
                </View>
              ) : null}
              {turn.error ? (
                <View style={[styles.reply, { borderColor: colors.danger }]}>
                  <Text style={[font.body, { color: colors.danger }]}>{turn.error}</Text>
                </View>
              ) : null}
              {turn.replies.map((reply, i) => (
                <View key={i} style={styles.reply}>
                  <View style={styles.replyHead}>
                    <View style={styles.badge}>
                      <Text style={{ fontWeight: '800', color: colors.ink }}>M</Text>
                    </View>
                  </View>
                  <Text style={styles.replyText}>{reply.text}</Text>
                  {[...reply.buttons, ...reply.list_rows].length ? (
                    <View style={styles.options}>
                      {[...reply.buttons, ...reply.list_rows].map((option, k) => {
                        const main = k === 0 && reply.type === 'buttons'
                        const chosen = turn.chose === option.title
                        return (
                          <Pressable
                            key={option.id}
                            accessibilityRole="button"
                            disabled={!!turn.chose || busy}
                            onPress={() => tap(turn.id, option.id, option.title)}
                            style={({ pressed }) => [
                              styles.option,
                              main && styles.optionMain,
                              chosen && styles.optionChosen,
                              (pressed || (turn.chose && !chosen)) && { opacity: 0.55 },
                            ]}
                          >
                            <Text style={{ fontSize: main ? 17 : 15, fontWeight: '700', color: colors.ink }}>{option.title}</Text>
                            {option.description ? <Text style={font.tiny}>{option.description}</Text> : null}
                          </Pressable>
                        )
                      })}
                    </View>
                  ) : null}
                </View>
              ))}
            </View>
          ))}
          {notice ? <Text style={{ color: colors.brand, fontSize: 14 }}>{notice}</Text> : null}
        </ScrollView>

        {phase === 'recording' ? (
          <View style={styles.bars} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            {levels.map((l, i) => (
              <View key={i} style={[styles.bar, { height: 8 + l * 80 }]} />
            ))}
          </View>
        ) : null}

        <View style={[styles.bottom, { paddingBottom: Math.max(insets.bottom, 16) }]}>
          {typing && phase !== 'recording' ? (
            <View style={styles.typeRow}>
              <TextInput
                accessibilityLabel={t.typeHere}
                value={draft}
                onChangeText={setDraft}
                placeholder={t.typeHere}
                placeholderTextColor={colors.nightMuted}
                multiline
                style={styles.input}
              />
              <Pressable accessibilityRole="button" accessibilityLabel={t.send} onPress={sendTyped} disabled={!draft.trim() || busy} style={[styles.sendButton, (!draft.trim() || busy) && { opacity: 0.5 }]}>
                <Send size={22} color={colors.ink} />
              </Pressable>
            </View>
          ) : null}
          <View style={styles.controls}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t.typeInstead}
              onPress={() => setTyping((v) => !v)}
              disabled={phase === 'recording'}
              style={[styles.round, { width: TOUCH + 8, height: TOUCH + 8, borderRadius: 28 }, phase === 'recording' && { opacity: 0.3 }]}
            >
              <Keyboard size={22} color="#fff" />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={phase === 'recording' ? t.tapToStop : t.speakToMesiri}
              disabled={phase === 'sending' || phase === 'starting' || busy}
              onPress={phase === 'recording' ? stop : start}
              style={[styles.bigMic, phase === 'recording' && styles.bigMicOn, (phase === 'sending' || busy) && { opacity: 0.5 }]}
            >
              {phase === 'recording' ? <View style={styles.stopSquare} /> : <Mic size={36} color={colors.ink} strokeWidth={2.2} />}
            </Pressable>
            <View style={{ width: TOUCH + 8 }} />
          </View>
          <Text style={styles.footnote}>{phase === 'recording' ? t.tapToStop : turns.length ? t.sayAChange : t.speakNow}</Text>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: space.lg, paddingVertical: space.md, gap: space.md },
  round: { width: TOUCH, height: TOUCH, borderRadius: TOUCH / 2, backgroundColor: colors.nightRaised, alignItems: 'center', justifyContent: 'center' },
  sitePill: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: colors.nightRaised, flexShrink: 1 },
  body: { padding: space.lg, gap: space.lg, flexGrow: 1 },
  status: { color: colors.nightMuted, fontSize: 13, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase' },
  hints: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  hint: { paddingVertical: 8, paddingHorizontal: 12, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.charcoal },
  saidBubble: { alignSelf: 'flex-end', maxWidth: '88%', backgroundColor: colors.nightCard, borderRadius: 18, borderTopRightRadius: 4, padding: 14, gap: 4 },
  saidLabel: { color: colors.nightMuted, fontSize: 12, fontWeight: '600' },
  saidText: { color: '#fff', fontSize: 18, lineHeight: 27, fontWeight: '600' },
  thinking: { color: colors.brand, fontSize: 14, fontWeight: '600' },
  reply: { backgroundColor: colors.card, borderRadius: 18, borderTopLeftRadius: 4, padding: 14, gap: 10, borderWidth: 1, borderColor: colors.card, maxWidth: '96%' },
  replyHead: { flexDirection: 'row' },
  badge: { width: 28, height: 28, borderRadius: 9, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  replyText: { fontSize: 16, lineHeight: 24, color: colors.ink },
  options: { gap: 8 },
  option: { minHeight: TOUCH, borderRadius: radius.md, borderWidth: 1, borderColor: colors.field, backgroundColor: colors.card, justifyContent: 'center', paddingHorizontal: 14, paddingVertical: 8 },
  optionMain: { minHeight: MAIN_ACTION, backgroundColor: colors.brand, borderColor: colors.brand, alignItems: 'center' },
  optionChosen: { borderWidth: 2, borderColor: colors.ink },
  bars: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5, height: 96 },
  bar: { width: 5, borderRadius: 3, backgroundColor: colors.brand },
  bottom: { paddingHorizontal: space.lg, paddingTop: space.md, gap: space.md },
  typeRow: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-end' },
  input: { flex: 1, minHeight: 52, maxHeight: 140, borderRadius: radius.md, backgroundColor: colors.nightCard, color: '#fff', fontSize: 17, paddingHorizontal: 14, paddingVertical: 14 },
  sendButton: { width: 52, height: 52, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  controls: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: space.xl },
  bigMic: { width: 96, height: 96, borderRadius: 48, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  bigMicOn: { borderWidth: 10, borderColor: 'rgba(250,204,21,0.25)' },
  stopSquare: { width: 30, height: 30, borderRadius: 7, backgroundColor: colors.ink },
  footnote: { color: colors.nightText, fontSize: 14, textAlign: 'center' },
})
