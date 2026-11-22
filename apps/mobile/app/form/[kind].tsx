import * as React from 'react'
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useOutbox } from '../../src/lib/outbox'
import { Mic } from 'lucide-react-native'
import { useWords } from '../../src/lib/i18n'
import {
  fetchMaterials,
  fetchUnits,
  newKey,
  type AssistantResponse,
  type Dictated,
  type CatalogMaterial,
  type ReadyEntry,
} from '../../src/lib/mesiri'
import { todayFor, useSession, useSite } from '../../src/lib/session'
import { useVoiceNote } from '../../src/lib/useVoiceNote'
import { useDictation } from '../../src/lib/useDictation'
import { spokenNumber } from '../../src/lib/numbers'
import { ApiError } from '../../src/lib/api'
import { kept } from '../../src/lib/kept'
import { BackHeader, Button, Chip, Label, Screen } from '../../src/components/ui'
import { colors, family, font, radius, space, TOUCH } from '../../src/theme'

// MOB-05: a form for one kind of entry, posting to the route the dashboard's own form uses. "Speak to fill" sends
// a voice note to the same Mesiri as WhatsApp; the entry it prepares (the list waiting for Save, as data) fills the
// fields, marked "From your voice". Saved with that entry's idempotency key, so the assistant's own Save of the same
// entry later can only answer "already saved"; then the assistant's own Remove takes it off Mesiri's list.

type Kind = 'received' | 'used' | 'problem'

const KINDS: Record<Kind, { tool: string; method: string; path: string }> = {
  received: { tool: 'record_receipt', method: 'POST', path: '/materials/inflows' },
  used: { tool: 'record_usage', method: 'POST', path: '/materials/outflows' },
  problem: { tool: 'report_issue', method: 'POST', path: '/progress/issues' },
}

const ISSUE_TYPES: { id: string; en: string; ml: string }[] = [
  { id: 'MATERIAL_SHORTAGE', en: 'Material short', ml: 'സാധനം കുറവ്' },
  { id: 'LABOUR_SHORTAGE', en: 'Labour short', ml: 'പണിക്കാർ കുറവ്' },
  { id: 'EQUIPMENT_BREAKDOWN', en: 'Machine broke', ml: 'മെഷീൻ കേടായി' },
  { id: 'WEATHER', en: 'Weather', ml: 'കാലാവസ്ഥ' },
  { id: 'DRAWING_PENDING', en: 'Drawing pending', ml: 'ഡ്രോയിംഗ് കിട്ടിയില്ല' },
  { id: 'INSPECTION_WAITING', en: 'Waiting for inspection', ml: 'പരിശോധന കാത്ത്' },
  { id: 'QUALITY', en: 'Quality', ml: 'ഗുണനിലവാരം' },
  { id: 'SAFETY', en: 'Safety', ml: 'സുരക്ഷ' },
  { id: 'ACCESS', en: 'Access', ml: 'വഴി' },
  { id: 'OTHER', en: 'Other', ml: 'മറ്റുള്ളവ' },
]
const SEVERITIES: { id: string; en: string; ml: string }[] = [
  { id: 'LOW', en: 'Low', ml: 'കുറവ്' },
  { id: 'MEDIUM', en: 'Medium', ml: 'ഇടത്തരം' },
  { id: 'HIGH', en: 'High', ml: 'കൂടുതൽ' },
  { id: 'CRITICAL', en: 'Work stopped', ml: 'പണി നിന്നു' },
]

const str = (v: unknown) => (v === null || v === undefined ? '' : String(v))
const qty = (v: unknown) => {
  const n = Number(v)
  return v === null || v === undefined || v === '' || !Number.isFinite(n) ? '' : String(+n.toFixed(3))
}

export default function EntryForm() {
  const { t, lang } = useWords()
  const router = useRouter()
  const outbox = useOutbox()
  const { me } = useSession()
  const { current, places } = useSite()
  const params = useLocalSearchParams<{ kind: string }>()
  const kind: Kind = params.kind === 'used' || params.kind === 'problem' ? params.kind : 'received'
  const spec = KINDS[kind]
  const isMaterial = kind !== 'problem'

  const materials = useQuery({ queryKey: ['materials'], queryFn: kept('materials', fetchMaterials), enabled: isMaterial, staleTime: 10 * 60_000 })
  const units = useQuery({ queryKey: ['units'], queryFn: kept('units', fetchUnits), enabled: isMaterial, staleTime: 60 * 60_000 })

  // The record as it will be sent: the voice entry's whole body (fields the form doesn't show, like a rate or an
  // order line, are kept), with what the form shows on top.
  const [base, setBase] = React.useState<Record<string, unknown>>({})
  const [entry, setEntry] = React.useState<ReadyEntry | null>(null)
  const [key, setKey] = React.useState(newKey)
  const [heard, setHeard] = React.useState<Set<string>>(new Set())
  const [said, setSaid] = React.useState<string | null>(null)
  const [mesiri, setMesiri] = React.useState<string | null>(null)
  const [problem, setProblem] = React.useState<string | null>(null)
  const used = React.useRef<Set<string>>(new Set())

  const [material, setMaterial] = React.useState<CatalogMaterial | null>(null)
  const [search, setSearch] = React.useState('')
  const [quantity, setQuantity] = React.useState('')
  const [unitId, setUnitId] = React.useState<string | null>(null)
  const [supplier, setSupplier] = React.useState('')
  const [workItem, setWorkItem] = React.useState('')
  const [note, setNote] = React.useState('')
  const [issueType, setIssueType] = React.useState('OTHER')
  const [severity, setSeverity] = React.useState('MEDIUM')
  const [narrative, setNarrative] = React.useState('')

  const projectId = str(base.project_id) || current?.project.id || ''
  const siteId = str(base.site_id) || current?.site.id || ''
  const place = places.find((p) => p.site.id === siteId) ?? current

  const fill = React.useCallback(
    (e: ReadyEntry) => {
      const b = e.body
      const got = new Set<string>()
      setBase(b)
      setEntry(e)
      setKey(e.key)
      if (isMaterial) {
        const m = (materials.data?.items ?? []).find((x) => x.id === b.material_id)
        if (m) {
          setMaterial(m)
          got.add('material')
        } else if (b.material_id) {
          setMaterial({ id: str(b.material_id), name: e.summary, default_unit: null, default_unit_id: null })
          got.add('material')
        }
        if (b.unit_id) {
          setUnitId(str(b.unit_id))
          got.add('unit')
        }
        if (b.quantity !== undefined) {
          setQuantity(qty(b.quantity))
          got.add('quantity')
        }
        if (b.supplier) {
          setSupplier(str(b.supplier))
          got.add('supplier')
        }
        if (b.work_item) {
          setWorkItem(str(b.work_item))
          got.add('work')
        }
        if (b.notes) {
          setNote(str(b.notes))
          got.add('note')
        }
      } else {
        if (b.issue_type) {
          setIssueType(str(b.issue_type))
          got.add('type')
        }
        if (b.severity) {
          setSeverity(str(b.severity))
          got.add('severity')
        }
        if (b.narrative) {
          setNarrative(str(b.narrative))
          got.add('narrative')
        }
      }
      setHeard(got)
    },
    [isMaterial, materials.data],
  )

  const onAnswer = React.useCallback(
    (res: AssistantResponse) => {
      setSaid(res.transcript)
      const words = res.replies.map((r) => r.text).filter(Boolean).join('\n')
      // The newest entry of this kind that this form has not taken yet.
      const mine = [...(res.ready ?? [])].reverse().find((e) => e.tool === spec.tool && !used.current.has(e.key))
      if (mine) {
        used.current.add(mine.key)
        fill(mine)
        setMesiri(null)
        setProblem(null)
      } else {
        setMesiri(words || null)
        setProblem(t.nothingFromVoice)
      }
    },
    [fill, spec.tool, t.nothingFromVoice],
  )
  const onVoiceError = React.useCallback((m: string) => setProblem(m === 'mic' ? t.micDenied : m), [t.micDenied])
  const voice = useVoiceNote(onAnswer, onVoiceError)

  // MOB-06: a mic on each field; the words go to that field only (English), the language heard shown under it.
  const [fieldHeard, setFieldHeard] = React.useState<Record<string, string>>({})
  const [fieldError, setFieldError] = React.useState<Record<string, string>>({})
  const onWords = React.useCallback(
    (field: string, words: Dictated) => {
      const text = words.text.trim()
      setFieldError((old) => ({ ...old, [field]: '' }))
      setFieldHeard((old) => ({ ...old, [field]: words.heard ?? '' }))
      const add = (old: string) => (old.trim() ? `${old.trim()} ${text}` : text)
      if (field === 'material') setSearch(text.replace(/[.!?]+$/, ''))
      else if (field === 'quantity') {
        // The number in the words ("50 bags" → 50), and the unit when one of the units is named.
        const n = spokenNumber(text)
        if (n !== null) setQuantity(String(+n.toFixed(3)))
        else setFieldError((old) => ({ ...old, quantity: t.noNumberHeard }))
        const said = text.toLowerCase()
        const unit = (units.data?.items ?? []).find((u) => new RegExp(`\\b${u.code.toLowerCase()}\\b`).test(said) || said.includes(u.display_name.toLowerCase()))
        if (unit) setUnitId(unit.id)
      } else if (field === 'supplier') setSupplier(text.replace(/[.!?]+$/, ''))
      else if (field === 'work') setWorkItem(text.replace(/[.!?]+$/, ''))
      else if (field === 'note') setNote(add)
      else if (field === 'narrative') setNarrative(add)
    },
    [t.noNumberHeard, units.data],
  )
  const onFieldError = React.useCallback(
    (field: string, m: string) => setFieldError((old) => ({ ...old, [field]: m === 'mic' ? t.micDenied : m })),
    [t.micDenied],
  )
  const dictation = useDictation(onWords, onFieldError)
  const mic = (field: string) => (
    <FieldMic
      listening={dictation.field === field && dictation.phase === 'recording'}
      hearing={dictation.field === field && dictation.phase === 'hearing'}
      disabled={dictation.phase !== 'idle' && dictation.field !== field}
      label={dictation.field === field && dictation.phase === 'recording' ? t.tapToStop : t.speakThisField}
      onPress={() => dictation.toggle(field)}
    />
  )
  const under = (field: string) =>
    fieldError[field] ? (
      <Text style={[font.tiny, { color: colors.warn }]}>{fieldError[field]}</Text>
    ) : fieldHeard[field] ? (
      <Text style={font.tiny}>
        {t.heardAs} {fieldHeard[field]}
      </Text>
    ) : null

  const save = useMutation({
    mutationFn: async () => {
      const date = str(base.occurred_date) || todayFor(me)
      const body: Record<string, unknown> = { ...base, project_id: projectId, site_id: siteId }
      if (isMaterial) {
        Object.assign(body, {
          material_id: material?.id,
          unit_id: unitId,
          quantity: Number(quantity),
          occurred_date: date,
          notes: note.trim() || null,
        })
        if (kind === 'received') body.supplier = supplier.trim() || null
        else body.work_item = workItem.trim() || null
      } else {
        Object.assign(body, { issue_type: issueType, severity, narrative: narrative.trim() })
      }
      // MOB-07: through the phone's outbox, so no signal keeps it to send later. Then off Mesiri's list (its own
      // Remove tap, sent after the save). The same key means its Save can't record it twice even if that tap is lost.
      return outbox.saveRecord({
        method: entry?.method ?? spec.method,
        path: entry?.path ?? spec.path,
        body,
        key,
        removeId: entry?.remove_id,
        title: `${title}: ${summaryLine()}`,
        place: place ? `${place.project.name} · ${place.site.name}` : '',
      })
    },
    onSuccess: (sent) => {
      if (sent.status === 'queued') setProblem(t.savedOnPhone)
      setTimeout(() => (router.canGoBack() ? router.back() : router.replace('/')), sent.status === 'queued' ? 1800 : 700)
    },
  })

  const summaryLine = () => {
    if (!isMaterial) return narrative.trim()
    const unit = (units.data?.items ?? []).find((u) => u.id === unitId)?.code ?? ''
    return `${quantity} ${unit} ${material?.name ?? ''}`.replace(/\s+/g, ' ').trim()
  }

  const check = (): string | null => {
    if (isMaterial && !material) return t.pickMaterial
    if (isMaterial && !(Number(quantity) > 0)) return t.enterQuantity
    if (!isMaterial && !narrative.trim()) return t.describeProblem
    return null
  }

  const matches = React.useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return []
    return (materials.data?.items ?? []).filter((m) => m.name.toLowerCase().includes(q) || (m.category ?? '').toLowerCase().includes(q)).slice(0, 6)
  }, [search, materials.data])

  const title = kind === 'received' ? t.materialsIn : kind === 'used' ? t.materialsUsed : t.problems
  const tag = (field: string) =>
    heard.has(field) ? (
      <View style={styles.tag}>
        <View style={styles.tagMark} />
        <Label style={{ color: colors.brandInk }}>{t.fromVoice}</Label>
      </View>
    ) : null
  const unitList = units.data?.items ?? []
  const shownUnits = unitList.filter((u) => u.id === unitId || u.id === material?.default_unit_id).concat(unitList.filter((u) => u.id !== unitId && u.id !== material?.default_unit_id))

  return (
    <Screen>
      <BackHeader title={title} subtitle={place ? `${place.project.name} · ${place.site.name}` : undefined} />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={voice.phase === 'recording' ? t.tapToStop : t.speakToFill}
            disabled={voice.phase === 'sending'}
            onPress={() => void voice.toggle()}
            style={({ pressed }) => [styles.speak, voice.phase === 'recording' && styles.speakOn, pressed && { opacity: 0.8 }]}
          >
            <View style={styles.speakIcon}>
              {voice.phase === 'recording' ? <View style={styles.stop} /> : <Mic size={18} color={colors.ink} />}
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[font.button, { color: '#fff' }]}>
                {voice.phase === 'recording' ? `${t.listening} · 0:${String(voice.seconds).padStart(2, '0')}` : voice.phase === 'sending' ? t.thinking : t.speakToFill}
              </Text>
              <Text style={[font.tiny, { color: colors.nightMuted }]}>{voice.phase === 'recording' ? t.tapToStop : t.speakToFillHint}</Text>
            </View>
          </Pressable>

          {said ? (
            <View style={styles.heard}>
              <Label>{t.youSaid}</Label>
              <Text style={font.body}>{said}</Text>
            </View>
          ) : null}
          {mesiri ? <Text style={[font.body, styles.mesiri]}>{mesiri}</Text> : null}
          {problem ? <Text style={{ color: colors.warn, fontSize: 14 }}>{problem}</Text> : null}

          {isMaterial ? (
            <>
              <Field label={t.material} tag={tag('material')}>
                {material ? (
                  <Pressable accessibilityRole="button" onPress={() => setMaterial(null)} style={[styles.input, styles.picked, heard.has('material') && styles.fromVoice]}>
                    <Text style={styles.inputText}>{material.name}</Text>
                    <Text style={font.tiny}>✕</Text>
                  </Pressable>
                ) : (
                  <>
                    <View style={styles.withMic}>
                      <TextInput accessibilityLabel={t.material} value={search} onChangeText={setSearch} placeholder={t.searchMaterial} placeholderTextColor={colors.faint} style={[styles.input, styles.grow]} />
                      {mic('material')}
                    </View>
                    {under('material')}
                    {matches.map((m) => (
                      <Pressable
                        key={m.id}
                        accessibilityRole="button"
                        onPress={() => {
                          setMaterial(m)
                          setUnitId(m.default_unit_id)
                          setSearch('')
                        }}
                        style={({ pressed }) => [styles.match, pressed && { opacity: 0.7 }]}
                      >
                        <Text style={font.strong}>{m.name}</Text>
                        <Text style={font.tiny}>{[m.default_unit, m.category].filter(Boolean).join(' · ')}</Text>
                      </Pressable>
                    ))}
                  </>
                )}
              </Field>
              <Field label={t.howMuch} tag={tag('quantity')}>
                <View style={styles.withMic}>
                  <TextInput accessibilityLabel={t.howMuch} value={quantity} onChangeText={setQuantity} keyboardType="decimal-pad" placeholder="0" placeholderTextColor={colors.faint} style={[styles.input, styles.big, styles.grow, heard.has('quantity') && styles.fromVoice]} />
                  {mic('quantity')}
                </View>
                {under('quantity')}
              </Field>
              <Field label={t.unit} tag={tag('unit')}>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
                  {shownUnits.map((u) => (
                    <Chip key={u.id} label={u.code} selected={u.id === unitId} onPress={() => setUnitId(u.id)} />
                  ))}
                </ScrollView>
              </Field>
              {kind === 'received' ? (
                <Field label={t.supplier} tag={tag('supplier')}>
                  <View style={styles.withMic}>
                    <TextInput accessibilityLabel={t.supplier} value={supplier} onChangeText={setSupplier} style={[styles.input, styles.grow, heard.has('supplier') && styles.fromVoice]} />
                    {mic('supplier')}
                  </View>
                  {under('supplier')}
                </Field>
              ) : (
                <Field label={t.usedFor} tag={tag('work')}>
                  <View style={styles.withMic}>
                    <TextInput accessibilityLabel={t.usedFor} value={workItem} onChangeText={setWorkItem} style={[styles.input, styles.grow, heard.has('work') && styles.fromVoice]} />
                    {mic('work')}
                  </View>
                  {under('work')}
                </Field>
              )}
              <Field label={t.note} tag={tag('note')}>
                <View style={styles.withMic}>
                  <TextInput accessibilityLabel={t.note} value={note} onChangeText={setNote} multiline style={[styles.input, styles.multi, styles.grow, heard.has('note') && styles.fromVoice]} />
                  {mic('note')}
                </View>
                {under('note')}
              </Field>
            </>
          ) : (
            <>
              <Field label={t.problemType} tag={tag('type')}>
                <View style={styles.chips}>
                  {ISSUE_TYPES.map((x) => (
                    <Chip key={x.id} label={lang === 'ml' ? x.ml : x.en} selected={issueType === x.id} onPress={() => setIssueType(x.id)} />
                  ))}
                </View>
              </Field>
              <Field label={t.severity} tag={tag('severity')}>
                <View style={styles.chips}>
                  {SEVERITIES.map((x) => (
                    <Chip key={x.id} label={lang === 'ml' ? x.ml : x.en} selected={severity === x.id} onPress={() => setSeverity(x.id)} />
                  ))}
                </View>
              </Field>
              <Field label={t.whatHappened} tag={tag('narrative')}>
                <View style={styles.withMic}>
                  <TextInput accessibilityLabel={t.whatHappened} value={narrative} onChangeText={setNarrative} multiline style={[styles.input, styles.multi, styles.grow, heard.has('narrative') && styles.fromVoice]} />
                  {mic('narrative')}
                </View>
                {under('narrative')}
              </Field>
            </>
          )}
          <Text style={font.tiny}>{t.englishNote}</Text>
          {save.isError ? (
            <Text accessibilityRole="alert" style={{ color: colors.danger, fontSize: 15 }}>
              {save.error instanceof ApiError ? save.error.message : String(save.error)}
            </Text>
          ) : null}
        </ScrollView>
        <View style={styles.footer}>
          <Button
            label={save.isSuccess ? `✓ ${t.saved}` : t.save}
            busy={save.isPending}
            disabled={save.isSuccess}
            onPress={() => {
              const wrong = check()
              if (wrong) setProblem(wrong)
              else {
                setProblem(null)
                save.mutate()
              }
            }}
          />
        </View>
      </KeyboardAvoidingView>
    </Screen>
  )
}

/** A field's own mic: a square beside it; yellow while it listens, a spinner while the words are heard. */
function FieldMic({ listening, hearing, disabled, label, onPress }: { listening: boolean; hearing: boolean; disabled: boolean; label: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={disabled || hearing}
      onPress={onPress}
      style={({ pressed }) => [styles.fieldMic, listening && styles.fieldMicOn, (pressed || disabled) && { opacity: 0.4 }]}
    >
      {hearing ? <ActivityIndicator color={colors.ink} /> : listening ? <View style={styles.stop} /> : <Mic size={20} color={colors.ink} strokeWidth={1.9} />}
    </Pressable>
  )
}

function Field({ label, tag, children }: { label: string; tag?: React.ReactNode; children: React.ReactNode }) {
  return (
    <View style={{ gap: 8 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <Label tone="ink">{label}</Label>
        {tag}
      </View>
      {children}
    </View>
  )
}

const styles = StyleSheet.create({
  body: { paddingHorizontal: space.lg, paddingBottom: 32, gap: space.xl },
  speak: { minHeight: 60, borderRadius: radius.md, backgroundColor: colors.ink, flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: 14, paddingVertical: 10 },
  speakOn: { borderWidth: 2, borderColor: colors.brand },
  speakIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  stop: { width: 12, height: 12, borderRadius: 2, backgroundColor: colors.ink },
  heard: { borderLeftWidth: 0, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: space.md, gap: 4 },
  mesiri: { backgroundColor: colors.card, borderRadius: radius.md, padding: space.md, borderWidth: 1, borderColor: colors.line },
  input: { minHeight: 54, borderRadius: radius.md, borderWidth: 1, borderColor: colors.field, backgroundColor: colors.card, paddingHorizontal: 14, fontFamily: family.semi, fontSize: 17, color: colors.ink },
  inputText: { fontFamily: family.semi, fontSize: 17, color: colors.ink, flex: 1 },
  picked: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  big: { fontFamily: family.display, fontSize: 26, letterSpacing: -0.5, fontVariant: ['tabular-nums'] },
  multi: { minHeight: 88, paddingTop: 14, textAlignVertical: 'top', fontFamily: family.body },
  fromVoice: { backgroundColor: colors.brandWash, borderColor: colors.brand },
  tag: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  tagMark: { width: 8, height: 8, borderRadius: 1, backgroundColor: colors.brand },
  match: { minHeight: TOUCH + 4, justifyContent: 'center', paddingHorizontal: 14, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.lineSoft, backgroundColor: colors.card },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  withMic: { flexDirection: 'row', gap: space.sm, alignItems: 'stretch' },
  grow: { flex: 1, minWidth: 0 },
  fieldMic: { width: 54, minHeight: 54, borderRadius: radius.md, borderWidth: 1, borderColor: colors.field, backgroundColor: colors.card, alignItems: 'center', justifyContent: 'center' },
  fieldMicOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  footer: { padding: space.lg, paddingBottom: 24, backgroundColor: colors.ground, borderTopWidth: 1, borderTopColor: colors.line },
})
