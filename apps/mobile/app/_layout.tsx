import * as React from 'react'
import { Stack, useRouter, useSegments } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nProvider } from '../src/lib/i18n'
import { SessionProvider, SiteProvider, useSession } from '../src/lib/session'
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
    </Stack>
  )
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <SessionProvider>
            <SiteProvider>
              <StatusBar style="dark" />
              <Gate />
            </SiteProvider>
          </SessionProvider>
        </I18nProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  )
}
