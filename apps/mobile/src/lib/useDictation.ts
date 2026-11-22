import * as React from 'react'
import { useAudioRecorder, useAudioRecorderState } from 'expo-audio'
import { Platform } from 'react-native'
import { ApiError, fileBody } from './api'
import { dictate, type Dictated } from './mesiri'
import { contentTypeOf, doneRecording, readyToRecord, VOICE_NOTE } from './recorder'

// MOB-06: one recorder for a whole form; each field's mic records into that field only. Tap to start, tap to stop;
// the words (in English) go to the field that asked. Needs signal: with none, the field says so and stays typeable.

/** A field's spoken words are short: half a minute is plenty, and stops a forgotten mic. */
const FIELD_SECONDS = 30

export function useDictation(onWords: (field: string, words: Dictated) => void, onError: (field: string, message: string) => void) {
  const recorder = useAudioRecorder(VOICE_NOTE)
  const state = useAudioRecorderState(recorder, 200)
  const [field, setField] = React.useState<string | null>(null)
  const [phase, setPhase] = React.useState<'idle' | 'recording' | 'hearing'>('idle')

  const stop = React.useCallback(async () => {
    const which = field
    setPhase('hearing')
    try {
      await recorder.stop()
    } finally {
      void doneRecording()
    }
    try {
      if (!recorder.uri || !which) throw new Error('Nothing was recorded. Try again.')
      const blob = await fileBody(recorder.uri)
      const words = await dictate(blob, Platform.OS === 'web' ? contentTypeOf(blob) : 'audio/mp4')
      onWords(which, words)
    } catch (e) {
      if (which) onError(which, e instanceof ApiError || e instanceof Error ? e.message : String(e))
    } finally {
      setPhase('idle')
      setField(null)
    }
  }, [field, recorder, onWords, onError])

  const start = React.useCallback(
    async (which: string) => {
      try {
        if (!(await readyToRecord())) return onError(which, 'mic')
        await recorder.prepareToRecordAsync()
        recorder.record({ forDuration: FIELD_SECONDS })
        setField(which)
        setPhase('recording')
      } catch {
        onError(which, 'mic')
      }
    },
    [recorder, onError],
  )

  // Stopped by its time limit: hear what there is.
  React.useEffect(() => {
    if (phase === 'recording' && !state.isRecording && (state.durationMillis ?? 0) > 500) void stop()
  }, [phase, state.isRecording, state.durationMillis, stop])

  React.useEffect(() => () => void doneRecording(), [])

  return {
    field,
    phase,
    /** The mic of ``which`` was tapped: start, or stop (and hear) if it is the one recording. */
    toggle: (which: string) => {
      if (phase === 'hearing') return
      if (phase === 'recording') {
        if (which === field) void stop()
        return
      }
      void start(which)
    },
  }
}
