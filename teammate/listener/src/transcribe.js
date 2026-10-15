// Voice notes -> transcript + English, and Malayalam (or other non-English)
// text -> English, through Gemini (TM-07).
//
// Same model and response shape as Mesiri's voice pipeline
// (platform/ai GeminiProvider.understand_voice: JSON, no
// thinking; transcript / translated_text / detected_language), called over
// plain REST so this kit stays a dependency-light Node service other repos
// can use too.

const API = "https://generativelanguage.googleapis.com/v1beta";
const TIMEOUT_MS = 60_000;

const VOICE_PROMPT =
  "You will be given a WhatsApp voice note from a customer or team member of a software company. " +
  "Most are in Malayalam, some in English, Hindi or a mix. Transcribe it accurately in its own " +
  "language and script, then translate it into clear English. Respond with JSON only: " +
  '{"transcript": verbatim, original language; "translated_text": English translation, same as ' +
  'transcript if already English; "detected_language": the language\'s common English name, ' +
  'e.g. "Malayalam"}. If there is no speech, use empty strings.';

const TEXT_PROMPT =
  "Translate this WhatsApp message into clear English. It may be Malayalam in Malayalam script, " +
  "Malayalam typed in English letters (Manglish), another language, or already English. Keep " +
  "names, email addresses, numbers and product terms as they are. Respond with JSON only: " +
  '{"translated_text": the English translation, or "" if the message is already plain English; ' +
  '"detected_language": the language\'s common English name, e.g. "Malayalam", "English"}.\n\n' +
  "Message:\n";

export class Transcriber {
  /** @param {{ apiKey: string, model?: string, fetchImpl?: typeof fetch }} opts */
  constructor({ apiKey, model = "gemini-3.8-flash", fetchImpl = fetch }) {
    if (!apiKey) throw new Error("Gemini API key missing");
    this.apiKey = apiKey;
    this.model = model;
    this.fetch = fetchImpl;
  }

  /** Confirms the key and model work; throws a readable error if not. */
  async check() {
    const res = await this.fetch(`${API}/models/${this.model}`, {
      headers: { "x-goog-api-key": this.apiKey },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`Gemini ${res.status}: ${(await res.text()).slice(0, 200)}`);
    return true;
  }

  /** @returns {Promise<{transcript: string, translation: string, language: string|null}>} */
  async voice(audio, mime = "audio/ogg") {
    const data = await this.generate([
      { inline_data: { mime_type: mime.split(";")[0].trim(), data: audio.toString("base64") } },
      { text: VOICE_PROMPT },
    ]);
    const transcript = String(data.transcript || "").trim();
    return {
      transcript,
      translation: String(data.translated_text || "").trim() || transcript,
      language: data.detected_language || null,
    };
  }

  /** @returns {Promise<{translation: string|null, language: string|null}>} null translation = already English */
  async text(text) {
    const data = await this.generate([{ text: TEXT_PROMPT + text }]);
    const translation = String(data.translated_text || "").trim();
    return { translation: translation && translation !== text.trim() ? translation : null, language: data.detected_language || null };
  }

  async generate(parts) {
    const res = await this.fetch(`${API}/models/${this.model}:generateContent`, {
      method: "POST",
      headers: { "x-goog-api-key": this.apiKey, "content-type": "application/json" },
      body: JSON.stringify({
        contents: [{ role: "user", parts }],
        generationConfig: { temperature: 0, responseMimeType: "application/json", thinkingConfig: { thinkingBudget: 0 } },
      }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`Gemini ${res.status}: ${(await res.text()).slice(0, 200)}`);
    const body = await res.json();
    const raw = body?.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") || "";
    const json = raw.slice(raw.indexOf("{"), raw.lastIndexOf("}") + 1);
    if (!json) throw new Error(`Gemini returned no JSON (${body?.candidates?.[0]?.finishReason || "no candidates"})`);
    return JSON.parse(json);
  }
}

// Voice notes and audio files are transcribed; text is translated unless it
// has nothing to translate (no letters, or just links / email addresses).
export function needsTranslation(text) {
  const stripped = (text || "").replace(/https?:\/\/\S+|\S+@\S+\.\S+|@\d+/g, " ");
  return /\p{L}{2,}/u.test(stripped);
}

/**
 * Works through the store's pending messages one at a time: on start, every
 * few minutes, and whenever a new message is stored (kick). A message that
 * fails three times is left alone.
 */
export class AiWorker {
  /** @param {{ store: import('./store.js').Store, transcriber: Transcriber | null, readFile: (path: string) => Buffer, log?: (msg: string) => void }} opts */
  constructor({ store, transcriber, readFile, log = () => {} }) {
    this.store = store;
    this.transcriber = transcriber;
    this.readFile = readFile;
    this.log = log;
    this.running = null;
    this.again = false;
    this.ok = null;
    this.lastError = null;
  }

  status() {
    if (!this.transcriber) return { enabled: false };
    return {
      enabled: true,
      model: this.transcriber.model,
      ok: this.ok,
      last_error: this.lastError,
      pending: this.store.countPendingAi(),
    };
  }

  async start({ intervalMs = 5 * 60_000 } = {}) {
    if (!this.transcriber) return this.log("Gemini: off (no TEAMMATE_GEMINI_API_KEY)");
    try {
      await this.transcriber.check();
      this.ok = true;
      this.log(`Gemini: key works (${this.transcriber.model})`);
      const retried = this.store.retryFailedAi();
      if (retried) this.log(`Gemini: retrying ${retried} message(s) that failed before`);
    } catch (e) {
      this.ok = false;
      this.lastError = String(e.message || e);
      return this.log(`Gemini: key check failed -- ${this.lastError}`);
    }
    this.timer = setInterval(() => this.kick(), intervalMs);
    this.timer.unref?.();
    this.kick();
  }

  /** Runs the queue now, or once more after the current run. */
  kick() {
    if (!this.transcriber || this.ok === false) return this.running;
    if (this.running) {
      this.again = true;
      return this.running;
    }
    this.running = this.drain().finally(() => {
      this.running = null;
      if (this.again) {
        this.again = false;
        this.kick();
      }
    });
    return this.running;
  }

  async drain() {
    let done = 0;
    const failed = new Set(); // retried on the next run, not straight away
    for (;;) {
      const batch = this.store.pendingAi(20 + failed.size).filter((m) => !failed.has(m.n));
      if (!batch.length) break;
      for (const m of batch) {
        try {
          if (m.kind === "voice" || m.kind === "audio") {
            const r = await this.transcriber.voice(this.readFile(m.media_path), m.media_mime || "audio/ogg");
            this.store.setAi(m.n, r);
          } else if (needsTranslation(m.text)) {
            const r = await this.transcriber.text(m.text);
            this.store.setAi(m.n, { translation: r.translation, language: r.language });
          } else {
            this.store.setAi(m.n, {});
          }
          done++;
        } catch (e) {
          const msg = String(e.message || e);
          this.lastError = `#${m.n}: ${msg.slice(0, 200)}`;
          this.log(`Gemini failed on #${m.n}: ${msg.replace(/\s+/g, " ").slice(0, 160)}`);
          failed.add(m.n);
          // Busy / rate-limited is temporary: it doesn't use up the message's 3
          // attempts. On a rate limit, stop until the next run (every 5 min).
          const status = Number(msg.match(/^Gemini (\d{3})/)?.[1]);
          if (status === 429) return done;
          // Key / account / model problems (401, 403, 404) are setup problems, not this message's:
          // stop until the next run without using up its attempts.
          if (![401, 403, 404, 500, 502, 503, 504].includes(status)) this.store.failAi(m.n);
          if ([401, 403, 404].includes(status)) return done;
        }
      }
    }
    if (done) this.log(`Gemini: ${done} message(s) transcribed / translated`);
    return done;
  }
}
