import * as React from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { useRouter } from 'expo-router'
import { CloudOff, MessageSquareReply, TriangleAlert } from 'lucide-react-native'
import { useOutbox, useSignal, type OutboxItem } from '../lib/outbox'
import { useWords } from '../lib/i18n'
import { colors, font, radius, space, TOUCH } from '../theme'

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
          <CloudOff size={22} color={colors.brand} />
          <View style={{ flex: 1 }}>
            <Text style={{ color: '#fff', fontSize: 15, fontWeight: '700' }}>{t.waitingToSend(pending)}</Text>
            <Text style={{ color: '#d6d3cd', fontSize: 12 }}>{online ? t.sendingNow : t.waitingNote}</Text>
          </View>
        </View>
      ) : null}
      {answered.map((x) => (
        <View key={x.id} style={[styles.card, styles.answered]}>
          <MessageSquareReply size={22} color={colors.brandInk} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={font.strong}>{t.answered}</Text>
            <Text style={font.tiny} numberOfLines={1}>
              {[name(x), when(x), x.place].filter(Boolean).join(' · ')}
            </Text>
          </View>
          <Pressable accessibilityRole="button" onPress={() => router.push({ pathname: '/speak', params: { from: x.id } })} style={styles.action}>
            <Text style={styles.actionText}>{t.check}</Text>
          </Pressable>
        </View>
      ))}
      {failed.map((x) => (
        <View key={x.id} style={[styles.card, styles.failed]}>
          <TriangleAlert size={22} color={colors.warn} />
          <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
            <Text style={font.strong}>
              {t.notSent} · {name(x)}
            </Text>
            <Text style={[font.tiny, { color: colors.warn }]}>{x.error}</Text>
            <View style={{ flexDirection: 'row', gap: space.sm, marginTop: 6 }}>
              <Pressable accessibilityRole="button" onPress={() => retry(x.id)} style={styles.action}>
                <Text style={styles.actionText}>{t.sendAgain}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" onPress={() => dismiss(x.id)} style={[styles.action, styles.quiet]}>
                <Text style={styles.actionText}>{t.discard}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: 14, borderRadius: 16 },
  waiting: { backgroundColor: colors.charcoal },
  answered: { backgroundColor: colors.brandSoft, borderWidth: 1, borderColor: colors.brand },
  failed: { backgroundColor: colors.warnSoft, alignItems: 'flex-start' },
  action: { minHeight: TOUCH - 4, paddingHorizontal: 14, borderRadius: radius.md, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.field, justifyContent: 'center' },
  quiet: { backgroundColor: 'transparent' },
  actionText: { fontSize: 14, fontWeight: '700', color: colors.ink },
})
