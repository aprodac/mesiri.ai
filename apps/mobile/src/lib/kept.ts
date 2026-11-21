import { ApiError } from './api'
import { getValue, setValue } from './storage'

// MOB-07: the last good answer of a read the app needs on site (sites, today's day, stock, the material catalog,
// units), kept on the phone. With no connection the kept copy is shown instead of an empty screen, even after the
// app was closed; any other refusal (signed out, not allowed) is still an error.

const PREFIX = 'mesiri_kept:'

export function kept<T>(key: string, read: () => Promise<T>): () => Promise<T> {
  return async () => {
    try {
      const fresh = await read()
      void setValue(PREFIX + key, fresh)
      return fresh
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        const old = await getValue<T>(PREFIX + key)
        if (old !== null) return old
      }
      throw e
    }
  }
}

/** Signing out forgets every kept copy, so the next person on this phone never sees the last one's. */
export async function forgetKept(): Promise<void> {
  try {
    const AsyncStorage = (await import('@react-native-async-storage/async-storage')).default
    const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith(PREFIX))
    if (keys.length) await AsyncStorage.multiRemove(keys)
  } catch {
    // Nothing kept, or storage unavailable: nothing to forget.
  }
}
