import * as React from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native'
import { ApiError } from '../src/lib/api'
import { useWords, LANGS } from '../src/lib/i18n'
import { loginWithCode, loginWithEmail, requestCode } from '../src/lib/mesiri'
import { useSession } from '../src/lib/session'
import { Button, Chip, HazardStripe, Label, Screen } from '../src/components/ui'
import { colors, family, font, radius, space } from '../src/theme'

// Sign in with the WhatsApp number on their account and a code sent on WhatsApp (the dashboard's own
// /auth/code routes), or with email and password.

type Step = 'phone' | 'code' | 'email'

export default function Login() {
  const { t, lang, setLang } = useWords()
  const { signedIn } = useSession()
  const [step, setStep] = React.useState<Step>('phone')
  const [phone, setPhone] = React.useState('')
  const [code, setCode] = React.useState('')
  const [email, setEmail] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [hint, setHint] = React.useState<string | null>(null)

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const askCode = () =>
    run(async () => {
      const res = await requestCode(phone.trim())
      setHint(res.dev_code ? `${t.codeSent} (${res.dev_code})` : t.codeSent)
      setStep('code')
    })

  const finish = (work: () => Promise<void>) =>
    run(async () => {
      await work()
      await signedIn()
    })

  return (
    <Screen>
      <HazardStripe />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <View style={styles.langs}>
            {LANGS.map((l) => (
              <Chip key={l.id} label={l.name} selected={lang === l.id} onPress={() => setLang(l.id)} />
            ))}
          </View>
          <View style={styles.mark}>
            <View style={styles.wordRow}>
              <Text style={styles.word}>Mesiri</Text>
              <View style={styles.dot} />
            </View>
            <Label>{t.siteApp}</Label>
          </View>
          <View style={{ gap: 8 }}>
            <Text style={font.display}>{t.signInTitle}</Text>
            <Text style={[font.body, { color: colors.muted }]}>{t.signInLead}</Text>
          </View>

          {step === 'email' ? (
            <>
              <Field label={t.email} value={email} onChange={setEmail} keyboard="email-address" autoComplete="email" />
              <Field label={t.password} value={password} onChange={setPassword} secure autoComplete="password" />
              <Button kind="accent" label={t.signIn} busy={busy} disabled={!email || !password} onPress={() => finish(() => loginWithEmail(email.trim(), password))} />
              <Link label={t.usePhone} onPress={() => setStep('phone')} />
            </>
          ) : step === 'phone' ? (
            <>
              <Field label={t.phone} value={phone} onChange={setPhone} keyboard="phone-pad" placeholder={t.phonePlaceholder} autoComplete="tel" />
              <Button kind="accent" label={t.sendCode} busy={busy} disabled={phone.replace(/\D/g, '').length < 10} onPress={askCode} />
              <Link label={t.useEmail} onPress={() => setStep('email')} />
            </>
          ) : (
            <>
              {hint ? <Text style={[font.body, { color: colors.done }]}>{hint}</Text> : null}
              <Field label={t.code} value={code} onChange={setCode} keyboard="number-pad" autoComplete="one-time-code" big />
              <Button kind="accent" label={t.signIn} busy={busy} disabled={code.trim().length < 4} onPress={() => finish(() => loginWithCode(phone.trim(), code.trim()))} />
              <Link label={t.otherNumber} onPress={() => setStep('phone')} />
            </>
          )}
          {error ? (
            <Text accessibilityRole="alert" style={[font.body, { color: colors.danger }]}>
              {error}
            </Text>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  )
}

function Field({
  label,
  value,
  onChange,
  keyboard,
  placeholder,
  secure,
  big,
  autoComplete,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  keyboard?: 'phone-pad' | 'number-pad' | 'email-address'
  placeholder?: string
  secure?: boolean
  big?: boolean
  autoComplete?: 'tel' | 'email' | 'password' | 'one-time-code'
}) {
  return (
    <View style={{ gap: 6 }}>
      <Label tone="ink">{label}</Label>
      <TextInput
        accessibilityLabel={label}
        value={value}
        onChangeText={onChange}
        keyboardType={keyboard}
        placeholder={placeholder}
        placeholderTextColor={colors.faint}
        secureTextEntry={secure}
        autoCapitalize="none"
        autoComplete={autoComplete}
        style={[styles.input, big && { fontSize: 26, letterSpacing: 8, textAlign: 'center' }]}
      />
    </View>
  )
}

function Link({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={{ minHeight: 48, justifyContent: 'center', alignItems: 'center' }}>
      <Text style={{ fontFamily: family.semi, color: colors.ink, fontSize: 15, textDecorationLine: 'underline' }}>{label}</Text>
    </Pressable>
  )
}

const styles = StyleSheet.create({
  body: { padding: space.xl, gap: space.xl, paddingTop: space.lg },
  langs: { flexDirection: 'row', gap: space.sm, justifyContent: 'flex-end' },
  mark: { gap: 6, paddingTop: space.xl, paddingBottom: space.md },
  wordRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 4 },
  word: { fontFamily: family.display, fontSize: 30, lineHeight: 32, letterSpacing: -1, color: colors.ink },
  dot: { width: 9, height: 9, borderRadius: 1, backgroundColor: colors.brand, marginBottom: 6 },
  input: {
    height: 56,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.field,
    backgroundColor: colors.card,
    paddingHorizontal: space.lg,
    fontFamily: family.semi,
    fontSize: 18,
    color: colors.ink,
  },
})
