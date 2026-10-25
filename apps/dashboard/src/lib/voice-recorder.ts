import encoderPath from 'opus-recorder/dist/encoderWorker.min.js?url'

// A voice note from the browser for Tell Mesiri (WEB-36), encoded as
// Ogg/Opus here so it reaches Mesiri as WhatsApp's voice notes do: the speech
// step and its billing read Ogg only, and Chrome (WebM) and Safari (MP4)
// would not record that themselves. The encoder is libopus in WebAssembly
// (opus-recorder), loaded the first time someone records.

/** Longest recording, as WhatsApp's own voice-note habit: a minute. */
export const MAX_SECONDS = 60

export interface VoiceNote {
  audio: Blob
  seconds: number
}

export interface Recording {
  /** Finish and hand over the note. */
  stop(): Promise<VoiceNote>
  /** Throw it away. */
  cancel(): void
}

export function canRecord(): boolean {
  return typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== 'undefined'
}

/**
 * Start recording. Must be called from a tap or click (browsers only let a
 * page start audio then). `onLevel` gets the input loudness, 0..1, about 30
 * times a second, for the live waveform. Rejects if the microphone is refused.
 */
export async function startRecording(onLevel: (level: number) => void): Promise<Recording> {
  // Created before any await, while the tap still counts as the user's.
  const context = new AudioContext()
  let stream: MediaStream | null = null
  let frame = 0
  const cleanup = () => {
    cancelAnimationFrame(frame)
    stream?.getTracks().forEach((t) => t.stop())
    void context.close().catch(() => undefined)
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    const { default: Recorder } = await import('opus-recorder')
    const source = context.createMediaStreamSource(stream)

    const analyser = context.createAnalyser()
    analyser.fftSize = 512
    source.connect(analyser)
    const samples = new Uint8Array(analyser.fftSize)
    const tick = () => {
      analyser.getByteTimeDomainData(samples)
      let sum = 0
      for (const s of samples) sum += ((s - 128) / 128) ** 2
      onLevel(Math.min(1, Math.sqrt(sum / samples.length) * 3))
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)

    const recorder = new Recorder({
      encoderPath,
      sourceNode: source,
      encoderSampleRate: 16000,
      numberOfChannels: 1,
      encoderApplication: 2048, // speech
    })
    const data = new Promise<Blob>((resolve) => {
      recorder.ondataavailable = (buffer) => resolve(new Blob([buffer], { type: 'audio/ogg' }))
    })
    await recorder.start()
    const started = performance.now()

    let done = false
    return {
      async stop() {
        if (done) throw new Error('already stopped')
        done = true
        const seconds = (performance.now() - started) / 1000
        await recorder.stop()
        const audio = await data
        cleanup()
        return { audio, seconds }
      },
      cancel() {
        if (done) return
        done = true
        void recorder.stop().catch(() => undefined)
        cleanup()
      },
    }
  } catch (err) {
    cleanup()
    throw err
  }
}
