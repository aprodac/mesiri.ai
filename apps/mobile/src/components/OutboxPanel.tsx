import * as React from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { ArrowRight, CloudOff, TriangleAlert } from 'lucide-react-native'
import { useOutbox, useSignal, type OutboxItem } from '../lib/outbox'
import { useWords } from '../lib/i18n'
import { colors, family, font, radius, space, TOUCH } from '../theme'

// MOB-07 on Today: what waits on the phone for signal, the answers that came for notes sent later, and anything
// the API refused (with its reason, to try again or discard). Nothing here goes away without the person seeing it.

export function OutboxPanel() {
  const { t, lang } = useWords()
  const router = useRouter()
  const online = useSignal()
  const { items, pending, retry, dismiss } = useOutbox()
  const answered = items.filter((x) => x.status === 'answered')
  const failed = items.filter((x) => x.status === 'failed')
  if (!pending && !answered.length && !failed.length) return null

  const when = (x: OutboxItem) =>
    new Date(x.createdAt).toLocaleTimeString(lang === 'ml' ? 'ml-IN' : 'en-IN', { hour: 'numeric', minute: '2-digit' })
  const name = (x: OutboxItem) => (x.kind === 'voice' ? `${t.voiceNote} ${x.title}` : x.title)

  return (
    <View style={{ gap: space.sm }}>
      {pending ? (
        <View style={[styles.card, styles.waiting]} accessibilityLiveRegion="polite">
          <CloudOff size={20} color={colors.brand} strokeWidth={2} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.titleLight}>{t.waitingToSend(pending)}</Text>
            <Text style={[font.tiny, { color: colors.nightMuted }]}>{online ? t.sendingNow : t.waitingNote}</Text>
          </View>
        </View>
      ) : null}
      {answered.map((x) => (
        <Pressable
          key={x.id}
          accessibilityRole="button"
          onPress={() => router.push({ pathname: '/speak', params: { from: x.id } })}
          style={({ pressed }) => [styles.card, styles.answered, pressed && { opacity: 0.7 }]}
        >
          <View style={styles.yellowMark} />
          <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
            <Text style={styles.title}>{t.answered}</Text>
            <Text style={font.tiny} numberOfLines={1}>
              {[name(x), when(x), x.place].filter(Boolean).join(' · ')}
            </Text>
          </View>
          <Text style={styles.link}>{t.check}</Text>
          <ArrowRight size={16} color={colors.ink} strokeWidth={2.2} />
        </Pressable>
      ))}
      {failed.map((x) => (
        <View key={x.id} style={[styles.card, styles.failed]}>
          <TriangleAlert size={20} color={colors.warn} strokeWidth={2} />
          <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
            <Text style={styles.title}>
              {t.notSent} · {name(x)}
            </Text>
            <Text style={[font.tiny, { color: colors.warn }]}>{x.error}</Text>
            <View style={{ flexDirection: 'row', gap: space.lg, marginTop: 4 }}>
              <Pressable accessibilityRole="button" onPress={() => retry(x.id)} style={styles.textButton}>
                <Text style={styles.link}>{t.sendAgain}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" onPress={() => dismiss(x.id)} style={styles.textButton}>
                <Text style={[styles.link, { color: colors.muted }]}>{t.discard}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: space.lg, paddingVertical: 14, borderRadius: radius.md },
  waiting: { backgroundColor: colors.charcoal },
  answered: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.line, minHeight: TOUCH + 12 },
  failed: { backgroundColor: colors.warnSoft, alignItems: 'flex-start' },
  yellowMark: { width: 10, height: 10, borderRadius: 2, backgroundColor: colors.brand },
  title: { fontFamily: family.displaySemi, fontSize: 15, color: colors.ink },
  titleLight: { fontFamily: family.displaySemi, fontSize: 15, color: '#fff' },
  link: { fontFamily: family.displaySemi, fontSize: 15, color: colors.ink },
  textButton: { minHeight: TOUCH - 8, justifyContent: 'center' },
})
