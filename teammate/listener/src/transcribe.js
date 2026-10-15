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

/**
 * What a call cost, from the token counts Gemini reports with every answer.
 * Prices are USD per 1M tokens (gemini-3.8-flash paid tier, ai.google.dev/gemini-api/docs/pricing, read
 * 15 Oct 2026: input $0.75, output incl. thinking $3.75 through 31 Dec 2026; both double from 1 Jan 2027).
 * Override with TEAMMATE_GEMINI_PRICE_IN / _OUT and the rupee rate with TEAMMATE_USD_INR.
 */
export function costOf(usage, { priceIn, priceOut, usdInr }) {
  const input = Number(usage?.promptTokenCount || 0);
  const output = Number(usage?.candidatesTokenCount || 0) + Number(usage?.thoughtsTokenCount || 0);
  const usd = (input * priceIn + output * priceOut) / 1e6;
  return { input_tokens: input, output_tokens: output, usd, inr: usd * usdInr };
}

export class Transcriber {
  /** @param {{ apiKey: string, model?: string, fetchImpl?: typeof fetch, prices?: { priceIn: number, priceOut: number, usdInr: number } }} opts */
  constructor({ apiKey, model = "gemini-3.8-flash", fetchImpl = fetch, prices = {} }) {
    if (!apiKey) throw new Error("Gemini API key missing");
    this.apiKey = apiKey;
    this.model = model;
    this.fetch = fetchImpl;
    this.prices = {
      priceIn: Number(prices.priceIn ?? process.env.TEAMMATE_GEMINI_PRICE_IN ?? 0.75),
      priceOut: Number(prices.priceOut ?? process.env.TEAMMATE_GEMINI_PRICE_OUT ?? 3.75),
      usdInr: Number(prices.usdInr ?? process.env.TEAMMATE_USD_INR ?? 88),
    };
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

  /** @returns {Promise<{transcript: string, translation: string, language: string|null, cost: object}>} */
  async voice(audio, mime = "audio/ogg") {
    const { data, cost } = await this.generate([
      { inline_data: { mime_type: mime.split(";")[0].trim(), data: audio.toString("base64") } },
      { text: VOICE_PROMPT },
    ]);
    const transcript = String(data.transcript || "").trim();
    return {
      transcript,
      translation: String(data.translated_text || "").trim() || transcript,
      language: data.detected_language || null,
      cost,
    };
  }

  /** @returns {Promise<{translation: string|null, language: string|null, cost: object}>} null translation = already English */
  async text(text) {
    const { data, cost } = await this.generate([{ text: TEXT_PROMPT + text }]);
    const translation = String(data.translated_text || "").trim();
    return { translation: translation && translation !== text.trim() ? translation : null, language: data.detected_language || null, cost };
  }

  async generate(parts) {
    const call = (thinkingOff) =>
      this.fetch(`${API}/models/${this.model}:generateContent`, {
        method: "POST",
        headers: { "x-goog-api-key": this.apiKey, "content-type": "application/json" },
        body: JSON.stringify({
          contents: [{ role: "user", parts }],
          generationConfig: {
            temperature: 0,
            responseMimeType: "application/json",
            ...(thinkingOff ? { thinkingConfig: { thinkingBudget: 0 } } : {}),
          },
        }),
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    let res = await call(!this.noThinkingConfig);
    // Newer models may not take a thinking budget: retry once without it, and remember.
    if (res.status === 400 && !this.noThinkingConfig) {
      const text = await res.text();
      if (!/thinking/i.test(text)) throw new Error(`Gemini 400: ${text.slice(0, 200)}`);
      this.noThinkingConfig = true;
      res = await call(false);
    }
    if (!res.ok) throw new Error(`Gemini ${res.status}: ${(await res.text()).slice(0, 200)}`);
    const body = await res.json();
    const raw = body?.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") || "";
    const json = raw.slice(raw.indexOf("{"), raw.lastIndexOf("}") + 1);
    if (!json) throw new Error(`Gemini returned no JSON (${body?.candidates?.[0]?.finishReason || "no candidates"})`);
    return { data: JSON.parse(json), cost: { model: this.model, ...costOf(body.usageMetadata, this.prices) } };
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
  /**
   * @param {{ store: import('./store.js').Store, transcriber: Transcriber | null, readFile: (path: string) => Buffer, log?: (msg: string) => void, auto?: boolean }} opts
   * auto: translate every new message in team/customer chats in the background. Off by default (owner's
   * choice, 15 Oct): messages are translated only when someone asks (translate()).
   */
  constructor({ store, transcriber, readFile, log = () => {}, auto = false }) {
    this.auto = auto;
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
      auto: this.auto,
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
      this.log(`Gemini: key works (${this.transcriber.model}); ${this.auto ? "translating new messages automatically" : "translating on request only"}`);
      if (!this.auto) return;
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

  /**
   * Translates one message on request (voice note / audio: transcript + English; text: English), records
   * what the call cost, and returns it. Already-translated messages come back from the store, free.
   * Only messages in chats labelled team or customer; personal / unlabelled chats are never sent.
   */
  async translate(n, { force = false } = {}) {
    if (!this.transcriber) throw new Error("translation is off (no Gemini key)");
    const m = this.store.getMessage(n);
    if (!m) throw new Error(`no message #${n}`);
    if (!["team", "customer"].includes(m.chat_role)) throw new Error(`#${n} is in a chat that isn't labelled team or customer`);
    if (!force && (m.transcript || m.translation)) {
      return { n, cached: true, transcript: m.transcript, translation: m.translation, language: m.language, cost: null };
    }
    let r;
    if (m.kind === "voice" || m.kind === "audio") {
      if (!m.media_path) throw new Error(`#${n} has no audio file saved`);
      r = await this.transcriber.voice(this.readFile(m.media_path), m.media_mime || "audio/ogg");
      this.store.setAi(n, { transcript: r.transcript, translation: r.translation, language: r.language });
    } else if (m.text && needsTranslation(m.text)) {
      r = await this.transcriber.text(m.text);
      this.store.setAi(n, { translation: r.translation, language: r.language });
    } else {
      throw new Error(`#${n} has nothing to translate`);
    }
    this.store.addAiUsage({ n, model: r.cost.model, input_tokens: r.cost.input_tokens, output_tokens: r.cost.output_tokens, usd: r.cost.usd, inr: r.cost.inr });
    this.log(`Gemini: #${n} translated for Rs ${r.cost.inr.toFixed(3)}`);
    return { n, cached: false, transcript: r.transcript || null, translation: r.translation, language: r.language, cost: r.cost };
  }

  /** Runs the queue now, or once more after the current run (automatic mode only). */
  kick() {
    if (!this.auto) return null;
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
            this.store.addAiUsage({ n: m.n, model: r.cost.model, input_tokens: r.cost.input_tokens, output_tokens: r.cost.output_tokens, usd: r.cost.usd, inr: r.cost.inr });
          } else if (needsTranslation(m.text)) {
            const r = await this.transcriber.text(m.text);
            this.store.setAi(m.n, { translation: r.translation, language: r.language });
            this.store.addAiUsage({ n: m.n, model: r.cost.model, input_tokens: r.cost.input_tokens, output_tokens: r.cost.output_tokens, usd: r.cost.usd, inr: r.cost.inr });
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
