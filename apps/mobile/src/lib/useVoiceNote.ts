import * as React from 'react'
import { useAudioRecorder, useAudioRecorderState } from 'expo-audio'
import { fileBody } from './api'
import { sendVoice, type AssistantResponse } from './mesiri'
import { contentTypeOf, doneRecording, level, MAX_SECONDS, readyToRecord, VOICE_NOTE } from './recorder'

// One voice note to Mesiri, for a screen that is not the Speak screen (a form's "speak to fill"):
// tap to start, tap to stop, and the assistant's answer (its replies and the list waiting for Save).

export type VoicePhase = 'idle' | 'recording' | 'sending'

export function useVoiceNote(onAnswer: (res: AssistantResponse) => void, onError: (message: string) => void) {
  const recorder = useAudioRecorder(VOICE_NOTE)
  const state = useAudioRecorderState(recorder, 150)
  const [phase, setPhase] = React.useState<VoicePhase>('idle')

  const start = React.useCallback(async () => {
    try {
      if (!(await readyToRecord())) return onError('mic')
      await recorder.prepareToRecordAsync()
      recorder.record({ forDuration: MAX_SECONDS })
      setPhase('recording')
    } catch {
      onError('mic')
    }
  }, [recorder, onError])

  const stop = React.useCallback(async () => {
    setPhase('sending')
    try {
      await recorder.stop()
    } finally {
      void doneRecording()
    }
    try {
      if (!recorder.uri) throw new Error('nothing recorded')
      const blob = await fileBody(recorder.uri)
      onAnswer(await sendVoice(blob, contentTypeOf(blob)))
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setPhase('idle')
    }
  }, [recorder, onAnswer, onError])

  // The door's one-minute limit: stop and send by itself.
  React.useEffect(() => {
    if (phase === 'recording' && !state.isRecording && (state.durationMillis ?? 0) > 500) void stop()
  }, [phase, state.isRecording, state.durationMillis, stop])

  React.useEffect(() => () => void doneRecording(), [])

  return {
    phase,
    seconds: Math.floor((state.durationMillis ?? 0) / 1000),
    level: level(state.metering),
    toggle: phase === 'recording' ? stop : start,
  }
}
