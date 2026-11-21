import { Platform } from 'react-native'
import {
  AudioQuality,
  IOSOutputFormat,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  type RecordingOptions,
} from 'expo-audio'

// A voice note as the assistant's door takes it (MOB-03): AAC in MP4 (.m4a) on Android and iPhone,
// mono at speech quality (small to send on a weak signal; Sarvam hears it as well as WhatsApp's Ogg).

/** The assistant's door takes up to a minute (web_assistant MAX_VOICE_SECONDS). */
export const MAX_SECONDS = 60

export const VOICE_NOTE: RecordingOptions = {
  extension: '.m4a',
  sampleRate: 16000,
  numberOfChannels: 1,
  bitRate: 32000,
  isMeteringEnabled: true,
  android: { outputFormat: 'mpeg4', audioEncoder: 'aac' },
  ios: { outputFormat: IOSOutputFormat.MPEG4AAC, audioQuality: AudioQuality.MEDIUM },
  // The web build is only for looking at screens; Firefox records Ogg, which the door takes.
  web: { mimeType: 'audio/ogg;codecs=opus', bitsPerSecond: 32000 },
}

export async function readyToRecord(): Promise<boolean> {
  const permission = await requestRecordingPermissionsAsync()
  if (!permission.granted) return false
  await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true })
  return true
}

export async function doneRecording(): Promise<void> {
  try {
    await setAudioModeAsync({ allowsRecording: false })
  } catch {
    // Nothing to undo.
  }
}

export function contentTypeOf(blob: Blob): string {
  if (Platform.OS !== 'web') return 'audio/mp4'
  return (blob.type || 'audio/ogg').split(';')[0]
}

/** A meter reading (dBFS, about -60 to 0) as a bar height from 0 to 1. */
export function level(metering: number | undefined): number {
  if (metering === undefined || metering === null) return 0.15
  return Math.max(0.08, Math.min(1, (metering + 60) / 60))
}
