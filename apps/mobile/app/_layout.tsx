import * as React from 'react'
import { Stack, useRouter, useSegments } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nProvider } from '../src/lib/i18n'
import { SessionProvider, SiteProvider, useSession } from '../src/lib/session'
import { OutboxProvider } from '../src/lib/outbox'
import { useFonts } from 'expo-font'
import { ArchivoNarrow_600SemiBold } from '@expo-google-fonts/archivo-narrow/600SemiBold'
import { ArchivoNarrow_700Bold } from '@expo-google-fonts/archivo-narrow/700Bold'
import { Archivo_400Regular } from '@expo-google-fonts/archivo/400Regular'
import { Archivo_500Medium } from '@expo-google-fonts/archivo/500Medium'
import { Archivo_600SemiBold } from '@expo-google-fonts/archivo/600SemiBold'
import { JetBrainsMono_400Regular } from '@expo-google-fonts/jetbrains-mono/400Regular'
import { JetBrainsMono_500Medium } from '@expo-google-fonts/jetbrains-mono/500Medium'
import { colors } from '../src/theme'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

/** Signed out → the sign-in screen; signed in → the app. Nothing else decides where you are. */
function Gate() {
  const { state } = useSession()
  const segments = useSegments()
  const router = useRouter()
  React.useEffect(() => {
    if (state === 'loading') return
    const onLogin = segments[0] === 'login'
    if (state === 'signed_out' && !onLogin) router.replace('/login')
    if (state === 'signed_in' && onLogin) router.replace('/')
  }, [state, segments, router])
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.ground } }}>
      <Stack.Screen name="(app)" />
      <Stack.Screen name="login" />
      <Stack.Screen name="speak" options={{ presentation: 'fullScreenModal', animation: 'slide_from_bottom' }} />
      <Stack.Screen name="switch-site" options={{ presentation: 'transparentModal', animation: 'fade' }} />
      <Stack.Screen name="day/[section]" />
      <Stack.Screen name="form/[kind]" />
    </Stack>
  )
}

export default function RootLayout() {
  // Only the weights the app uses (src/theme.ts family); Malayalam falls back to the phone's Noto Sans.
  const [fontsReady, fontError] = useFonts({
    ArchivoNarrow_600SemiBold,
    ArchivoNarrow_700Bold,
    Archivo_400Regular,
    Archivo_500Medium,
    Archivo_600SemiBold,
    JetBrainsMono_400Regular,
    JetBrainsMono_500Medium,
  })
  // A font that fails to load never blocks the app: it opens in the phone's own font.
  if (!fontsReady && !fontError) return null
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <SessionProvider>
            <SiteProvider>
              <OutboxProvider>
                <StatusBar style="dark" />
                <Gate />
              </OutboxProvider>
            </SiteProvider>
          </SessionProvider>
        </I18nProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  )
}
