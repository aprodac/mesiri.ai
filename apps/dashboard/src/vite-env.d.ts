/// <reference types="vite/client" />

// opus-recorder ships no types; only what lib/voice-recorder.ts uses.
declare module 'opus-recorder' {
  interface RecorderConfig {
    encoderPath?: string
    sourceNode?: MediaStreamAudioSourceNode
    encoderSampleRate?: number
    numberOfChannels?: number
    encoderApplication?: number
    streamPages?: boolean
  }
  export default class Recorder {
    constructor(config?: RecorderConfig)
    static isRecordingSupported(): boolean
    ondataavailable: (data: Uint8Array<ArrayBuffer>) => void
    start(): Promise<void>
    stop(): Promise<void>
    close(): Promise<void>
  }
}
