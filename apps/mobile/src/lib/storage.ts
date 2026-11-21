import { Platform } from 'react-native'
import * as SecureStore from 'expo-secure-store'
import AsyncStorage from '@react-native-async-storage/async-storage'

// Secrets (the sign-in token) in the phone's secure store; everything else in plain app storage.
// On the web build (used only to look at screens) both fall back to the browser's storage.

const web = Platform.OS === 'web'

export async function getSecret(key: string): Promise<string | null> {
  try {
    return web ? globalThis.localStorage?.getItem(key) ?? null : await SecureStore.getItemAsync(key)
  } catch {
    return null
  }
}

export async function setSecret(key: string, value: string | null): Promise<void> {
  try {
    if (web) {
      if (value === null) globalThis.localStorage?.removeItem(key)
      else globalThis.localStorage?.setItem(key, value)
    } else if (value === null) {
      await SecureStore.deleteItemAsync(key)
    } else {
      await SecureStore.setItemAsync(key, value)
    }
  } catch {
    // A phone that refuses the secure store keeps the person signed in for this run only.
  }
}

export async function getValue<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key)
    return raw === null ? null : (JSON.parse(raw) as T)
  } catch {
    return null
  }
}

export async function setValue(key: string, value: unknown): Promise<void> {
  try {
    if (value === null || value === undefined) await AsyncStorage.removeItem(key)
    else await AsyncStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Remembering a choice is a nicety; the app works without it.
  }
}
