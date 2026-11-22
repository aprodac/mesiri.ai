import * as React from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { useQueryClient } from '@tanstack/react-query'
import { useAudioRecorder, useAudioRecorderState } from 'expo-audio'
import { Keyboard, Mic, Send, X } from 'lucide-react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { useWords } from '../src/lib/i18n'
import { fileBody, ApiError } from '../src/lib/api'
import { useOutbox, type Sent } from '../src/lib/outbox'
import { sendTap, type AssistantReply, type AssistantResponse, type ReadyEntry } from '../src/lib/mesiri'
import { contentTypeOf, doneRecording, level, MAX_SECONDS, readyToRecord, VOICE_NOTE } from '../src/lib/recorder'
import { useSite } from '../src/lib/session'
import { CategoryTile, Label, MesiriPanel, Screen, StateMark } from '../src/components/ui'
import { colors, family, font, MAIN_ACTION, radius, space, TOUCH, type Category } from '../src/theme'

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
  /** The list waiting for Save after this message (the TO SAVE sheet), as data. */
  ready?: ReadyEntry[] | null
}

/** Each kind of entry's tile (the cue system): the tool the assistant prepared it with. */
const TOOL_CATEGORY: Record<string, Category> = {
  record_attendance: 'people',
  record_work: 'work',
  correct_work: 'work',
  record_receipt: 'material',
  record_usage: 'material',
  ask_for_material: 'material',
  count_stock: 'material',
  report_issue: 'problem',
  log_machines: 'machine',
  add_machine: 'machine',
  record_expense: 'photo',
  add_bill_photo: 'photo',
  set_site_conditions: 'weather',
}
const KIND_LABEL: Record<string, string> = {
  record_attendance: 'ATTENDANCE',
  record_work: 'WORK DONE',
  record_receipt: 'MATERIAL IN',
  record_usage: 'MATERIAL USED',
  ask_for_material: 'REQUEST',
  report_issue: 'PROBLEM',
  log_machines: 'MACHINES',
  record_expense: 'EXPENSE',
  set_site_conditions: 'WEATHER AND SITE',
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
          old.map((x) => (x.id === id ? { ...x, pending: false, replies: res.replies, said: res.transcript ?? x.said, ready: res.ready } : x)),
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
            ready: item.answer.ready,
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

  // The latest TO SAVE list (the sheet is the assistant's own list; it shows once, under the last answer that has one).
  const lastWithList = [...turns].reverse().find((x) => x.ready && x.ready.length)

  return (
    <Screen dark>
      <View style={styles.top}>
        <Pressable accessibilityRole="button" accessibilityLabel={t.close} onPress={close} style={styles.close}>
          <X size={18} color="#fff" strokeWidth={2} />
        </Pressable>
        <View style={styles.sitePill}>
          <View style={styles.siteDot}>
            <Text style={styles.siteDotText}>{(current?.project.name ?? '?').slice(0, 2).toUpperCase()}</Text>
          </View>
          <Text style={styles.siteText} numberOfLines={1}>
            {current?.site.name ?? ''} · {t.today.toLowerCase()}
          </Text>
        </View>
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView ref={scroll} contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          {turns.length === 0 ? (
            <View style={{ gap: space.lg, paddingTop: space.md }}>
              <View style={styles.youSaid}>
                <View style={styles.voiceRow}>
                  <StateMark state="voice" size={18} />
                  <Label tone="yellow">{listening ? `${t.listening} · 0:${String(seconds).padStart(2, '0')}` : t.speakNow}</Label>
                </View>
                <Text style={styles.prompt}>{t.sayInOneGo}</Text>
              </View>
              <View style={styles.hints}>
                {t.hints.map((h, i) => (
                  <View key={h} style={[styles.hint, i === t.hints.length - 1 && { borderBottomWidth: 0 }]}>
                    <CategoryTile cat={(['people', 'material', 'work', 'problem', 'material'] as Category[])[i] ?? 'work'} size={28} />
                    <Text style={styles.hintText}>{h}</Text>
                  </View>
                ))}
              </View>
            </View>
          ) : null}

          {turns.map((turn) => (
            <View key={turn.id} style={{ gap: space.md }}>
              <View style={styles.youSaid}>
                <View style={styles.voiceRow}>
                  {turn.kind === 'voice' ? <StateMark state="voice" size={18} /> : null}
                  <Label tone="yellow">{turn.kind === 'tap' ? '✓' : t.youSaid}</Label>
                </View>
                <Text style={styles.saidText}>{turn.said ?? (turn.pending ? t.hearing : turn.queued ? t.voiceNote : '—')}</Text>
              </View>
              {turn.pending ? <Label tone="yellow">{t.thinking}</Label> : null}
              {turn.queued ? (
                <View style={styles.kept}>
                  <StateMark state="waiting" size={20} />
                  <Text style={[font.body, { color: colors.nightText, flex: 1 }]}>{t.keptOnPhone}</Text>
                </View>
              ) : null}
              {turn.error ? (
                <View style={[styles.kept, { backgroundColor: colors.warnSoft }]}>
                  <StateMark state="warn" size={20} />
                  <Text style={[font.body, { color: colors.warn, flex: 1 }]}>{turn.error}</Text>
                </View>
              ) : null}

              {turn === lastWithList && turn.ready ? (
                <View style={styles.sheet}>
                  <View style={styles.sheetHead}>
                    <Text style={styles.sheetTitle}>
                      {t.toSave} · {turn.ready.length}
                    </Text>
                    <View style={styles.notSaved}>
                      <Text style={styles.notSavedText}>● {t.notSavedYet}</Text>
                    </View>
                  </View>
                  {turn.ready.map((e) => (
                    <View key={e.key} style={styles.line}>
                      <CategoryTile cat={TOOL_CATEGORY[e.tool] ?? 'work'} size={34} />
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Label style={{ color: colors.blueprint }}>{KIND_LABEL[e.tool] ?? e.tool.replace(/_/g, ' ')}</Label>
                        <Text style={font.strong} numberOfLines={2}>
                          {e.summary}
                        </Text>
                      </View>
                      <StateMark state="pending" size={22} />
                    </View>
                  ))}
                </View>
              ) : null}

              {turn.replies.map((reply, i) => {
                const options = [...reply.buttons, ...reply.list_rows]
                return (
                  <MesiriPanel key={i}>
                    <Text style={styles.replyText}>{reply.text}</Text>
                    {options.length ? (
                      <View style={styles.options}>
                        {options.map((option, k) => {
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
                                (pressed || (turn.chose && !chosen)) && { opacity: 0.5 },
                              ]}
                            >
                              <Text style={[font.button, { color: colors.ink, fontSize: main ? 17 : 15 }]}>
                                {chosen ? '✓ ' : ''}
                                {option.title}
                              </Text>
                              {option.description ? <Text style={font.tiny}>{option.description}</Text> : null}
                            </Pressable>
                          )
                        })}
                      </View>
                    ) : null}
                  </MesiriPanel>
                )
              })}
            </View>
          ))}
          {notice ? <Text style={[font.small, { color: colors.brand }]}>{notice}</Text> : null}
        </ScrollView>

        {phase === 'recording' ? (
          <View style={styles.bars} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            {levels.map((l, i) => (
              <View key={i} style={[styles.bar, { height: 8 + l * 72 }]} />
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
                placeholderTextColor={colors.blueprintMid}
                multiline
                style={styles.input}
              />
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t.send}
                onPress={sendTyped}
                disabled={!draft.trim() || busy}
                style={[styles.sendButton, (!draft.trim() || busy) && { opacity: 0.5 }]}
              >
                <Send size={20} color={colors.ink} />
              </Pressable>
            </View>
          ) : null}
          <View style={styles.controls}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t.typeInstead}
              onPress={() => setTyping((v) => !v)}
              disabled={phase === 'recording'}
              style={[styles.round, phase === 'recording' && { opacity: 0.3 }]}
            >
              <Keyboard size={22} color="#fff" strokeWidth={1.8} />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={phase === 'recording' ? t.tapToStop : t.speakToMesiri}
              disabled={phase === 'sending' || phase === 'starting' || busy}
              onPress={phase === 'recording' ? stop : start}
              style={[styles.bigMic, phase === 'recording' && styles.bigMicOn, (phase === 'sending' || busy) && { opacity: 0.5 }]}
            >
              {phase === 'recording' ? <View style={styles.stopSquare} /> : <Mic size={34} color={colors.ink} strokeWidth={2.2} />}
            </Pressable>
            <View style={{ width: TOUCH + 4 }} />
          </View>
          <Text style={styles.footnote}>{phase === 'recording' ? t.tapToStop : turns.length ? t.sayAChange : t.speakNow}</Text>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  )
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14, paddingVertical: space.md, gap: space.md },
  close: { width: 44, height: 44, borderRadius: 22, borderWidth: 1, borderColor: 'rgba(255,255,255,0.4)', alignItems: 'center', justifyContent: 'center' },
  sitePill: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: 'rgba(255,255,255,0.12)', borderRadius: radius.pill, paddingVertical: 6, paddingLeft: 6, paddingRight: 12, flexShrink: 1 },
  siteDot: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  siteDotText: { fontFamily: family.display, fontSize: 12, color: colors.ink },
  siteText: { fontFamily: family.display, fontSize: 15, color: '#fff', flexShrink: 1 },
  body: { paddingHorizontal: 14, paddingBottom: space.lg, gap: space.lg, flexGrow: 1 },
  youSaid: { backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: radius.lg, padding: 14, gap: 8 },
  voiceRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  prompt: { fontFamily: family.display, fontSize: 26, lineHeight: 31, color: '#fff' },
  hints: { backgroundColor: 'rgba(255,255,255,0.06)', borderRadius: radius.lg, paddingHorizontal: 12 },
  hint: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 48, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.1)' },
  hintText: { fontFamily: family.body, fontSize: 15, color: colors.nightText },
  saidText: { fontFamily: family.semi, color: '#fff', fontSize: 19, lineHeight: 28 },
  kept: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: 'rgba(255,255,255,0.1)', borderRadius: radius.lg, padding: 12 },
  sheet: { backgroundColor: colors.ground, borderRadius: radius.xl, overflow: 'hidden' },
  sheetHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14, paddingTop: 12, paddingBottom: 10 },
  sheetTitle: { fontFamily: family.display, fontSize: 20, letterSpacing: 0.5, color: colors.ink },
  notSaved: { borderWidth: 1.5, borderStyle: 'dashed', borderColor: colors.brandEdge, backgroundColor: colors.brandSoft, borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 2 },
  notSavedText: { fontFamily: family.monoMedium, fontSize: 9, letterSpacing: 1, color: colors.brandInk },
  line: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, paddingVertical: 9, borderTopWidth: 1, borderTopColor: colors.lineSoft },
  replyText: { fontFamily: family.body, fontSize: 15, lineHeight: 22, color: colors.blueprint },
  options: { gap: 8 },
  option: { minHeight: TOUCH - 4, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.ink, backgroundColor: 'transparent', justifyContent: 'center', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 6 },
  optionMain: { minHeight: MAIN_ACTION, backgroundColor: colors.brand, borderColor: colors.brand },
  optionChosen: { backgroundColor: colors.ink, borderColor: colors.ink },
  bars: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, height: 88 },
  bar: { width: 4, borderRadius: 2, backgroundColor: colors.brand },
  bottom: { paddingHorizontal: 14, paddingTop: space.md, gap: space.md },
  typeRow: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-end' },
  input: { flex: 1, minHeight: 52, maxHeight: 140, borderRadius: radius.lg, backgroundColor: 'rgba(255,255,255,0.1)', color: '#fff', fontFamily: family.body, fontSize: 17, paddingHorizontal: 16, paddingVertical: 14 },
  sendButton: { width: 52, height: 52, borderRadius: 26, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  controls: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: space.xl },
  round: { width: TOUCH + 4, height: TOUCH + 4, borderRadius: 26, borderWidth: 1, borderColor: 'rgba(255,255,255,0.4)', alignItems: 'center', justifyContent: 'center' },
  bigMic: { width: 84, height: 84, borderRadius: 42, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  bigMicOn: { borderWidth: 8, borderColor: 'rgba(255,210,63,0.3)' },
  stopSquare: { width: 26, height: 26, borderRadius: 6, backgroundColor: colors.ink },
  footnote: { fontFamily: family.monoMedium, color: colors.blueprintSoft, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', textAlign: 'center' },
})
