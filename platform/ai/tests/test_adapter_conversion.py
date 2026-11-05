"""Adapter response conversion (M3) — no network, no SDK required.

Verifies that adapters convert provider-shaped responses into Mesiri-owned
models and that malformed provider output maps to the shared error contract.
The SDK calls themselves are exercised only in provider-marked tests.
"""

import json
from types import SimpleNamespace

import pytest

from mesiri_ai.adapters.deepseek.adapter import DeepSeekExtractionProvider
from mesiri_ai.adapters.gemini.adapter import GeminiProvider
from mesiri_ai.adapters.sarvam.adapter import SarvamSpeechProvider
from mesiri_contracts.common.errors import MesiriError


def _aio(models: object) -> SimpleNamespace:
    """Shape a fake `models` object like the genai client's async surface.

    The adapter calls ``client.aio.models.generate_content`` (native async --
    it used to wrap the sync method in asyncio.to_thread, which serialized
    concurrent calls behind the default thread pool). The fakes below stay
    plain sync functions; this only adapts them to the awaited call shape.
    """

    class _AioModels:
        async def generate_content(self, **kwargs):
            return models.generate_content(**kwargs)  # type: ignore[attr-defined]

    return SimpleNamespace(aio=SimpleNamespace(models=_AioModels()))


def test_sarvam_converts_dict_response_to_speech_result():
    provider = SarvamSpeechProvider.__new__(SarvamSpeechProvider)  # skip SDK init
    raw = {"transcript": "The JCB ran for 4 hours", "language_code": "ml-IN"}
    result = provider._to_result(raw, latency_ms=120.0)
    assert result.transcript == "The JCB ran for 4 hours"
    assert result.detected_language == "ml-IN"
    assert result.translated_text == "The JCB ran for 4 hours"
    assert result.latency_ms == 120.0


def test_gemini_parses_fenced_json():
    data = GeminiProvider._parse_json('```json\n{"semantic_type": "expense"}\n```', None)
    assert data["semantic_type"] == "expense"


def test_gemini_malformed_output_maps_to_error():
    with pytest.raises(MesiriError) as exc:
        GeminiProvider._parse_json("not json at all", correlation_id="cor_x")
    assert exc.value.error_code == "PROVIDER_MALFORMED_OUTPUT"
    assert exc.value.correlation_id == "cor_x"


def test_gemini_non_object_json_is_malformed():
    with pytest.raises(MesiriError):
        GeminiProvider._parse_json("[1, 2, 3]", None)


def test_gemini_parses_json_wrapped_in_leading_commentary():
    """Regression test: a live bug where an inventory query naming a project
    inline in Malayalam ("Green Valley-ൽ...") failed translation every time,
    at any sentence length. Root cause: Gemini sometimes adds a clarifying
    sentence around the JSON for code-mixed input (an English proper noun
    embedded in a non-English sentence) -- e.g. explaining that "Green
    Valley" was left untranslated -- which the old exact-fence-stripping
    parser couldn't handle at all, throwing a non-retryable error that
    propagated all the way to "couldn't make out that message". json_mode
    (response_mime_type) should prevent this at the source now, but the
    parser must still degrade gracefully if a model ever does it anyway."""
    raw = (
        'Note: "Green Valley" appears to be a proper name and was left untranslated.\n'
        '{"translated_text": "In Green Valley, how many bags of cement are in stock?", '
        '"detected_language": "Malayalam"}'
    )
    data = GeminiProvider._parse_json(raw, None)
    assert data["translated_text"] == "In Green Valley, how many bags of cement are in stock?"


def test_gemini_parses_json_wrapped_in_trailing_commentary():
    raw = (
        '{"semantic_type": "inventory_query", "fields": {"project_name": "Green Valley"}}\n'
        "(Note: material_name omitted since the user asked about all materials.)"
    )
    data = GeminiProvider._parse_json(raw, None)
    assert data["semantic_type"] == "inventory_query"
    assert data["fields"]["project_name"] == "Green Valley"


def test_gemini_still_rejects_response_with_no_json_object_at_all():
    """The commentary-tolerant fallback must not silently accept text that
    never contained a JSON object in the first place -- that's still a real
    provider failure, not something to paper over."""
    with pytest.raises(MesiriError) as exc:
        GeminiProvider._parse_json("I'm sorry, I don't understand this request.", None)
    assert exc.value.error_code == "PROVIDER_MALFORMED_OUTPUT"


async def test_gemini_json_mode_sets_response_mime_type():
    """extract()/translate_to_english()/analyze_image()/generate_json() must
    ask Gemini for a strict-JSON response (response_mime_type=
    "application/json") -- the primary defense against the commentary-
    wrapped-JSON bug above, stopping it at the source rather than relying
    only on _parse_json's fallback parsing."""
    captured: dict = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            captured["config"] = config
            return SimpleNamespace(text='{"translated_text": "hello", "detected_language": "en"}')

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(
        model="gemini-test", timeout_seconds=5, max_retries=0
    )
    provider._client = _aio(_FakeModels())

    await provider.translate_to_english("hello", correlation_id="cor_1")

    assert captured["config"] is not None
    assert captured["config"].response_mime_type == "application/json"


def _png_bytes(width: int, height: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_downscale_shrinks_a_large_photo_and_reports_jpeg():
    from io import BytesIO

    from PIL import Image

    from mesiri_ai.adapters.gemini.adapter import _downscale_image

    original = _png_bytes(4000, 3000)
    out, mime = _downscale_image(original, "image/png", 1568)

    assert mime == "image/jpeg"
    assert len(out) < len(original)
    with Image.open(BytesIO(out)) as img:
        assert max(img.size) == 1568
        # Aspect ratio preserved (4:3 -> 1568x1176).
        assert img.size == (1568, 1176)


def test_downscale_leaves_an_already_small_image_untouched():
    """A no-op must return the *original* bytes, not a re-encoded copy --
    re-encoding a small image would cost quality and time for nothing."""
    from mesiri_ai.adapters.gemini.adapter import _downscale_image

    original = _png_bytes(800, 600)
    out, mime = _downscale_image(original, "image/png", 1568)

    assert out is original
    assert mime == "image/png"


def test_downscale_is_disabled_by_zero_and_skips_non_images():
    from mesiri_ai.adapters.gemini.adapter import _downscale_image

    original = _png_bytes(4000, 3000)
    assert _downscale_image(original, "image/png", 0) == (original, "image/png")
    assert _downscale_image(b"%PDF-1.4 not an image", "application/pdf", 1568) == (
        b"%PDF-1.4 not an image",
        "application/pdf",
    )


def test_downscale_fails_open_on_undecodable_bytes():
    """Fail-open contract: a resize problem must never be the reason a
    receipt can't be read -- garbage in returns the same garbage out for
    Gemini to reject on its own terms, rather than raising here."""
    from mesiri_ai.adapters.gemini.adapter import _downscale_image

    junk = b"not really an image at all"
    assert _downscale_image(junk, "image/jpeg", 1568) == (junk, "image/jpeg")


async def test_gemini_analyze_image_downscales_before_sending():
    from io import BytesIO

    from PIL import Image

    captured: dict = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            captured["contents"] = contents
            return SimpleNamespace(
                text='{"document_classification": "receipt", "description": "x", "fields": {}}'
            )

    class _FakePart:
        @staticmethod
        def from_bytes(*, data, mime_type):
            captured["data"] = data
            captured["mime_type"] = mime_type
            return "part"

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(
        model="gemini-test", timeout_seconds=5, max_retries=0, max_image_edge=1024
    )
    provider._client = _aio(_FakeModels())

    with pytest.MonkeyPatch.context() as mp:
        import google.genai

        mp.setattr(google.genai.types, "Part", _FakePart)
        await provider.analyze_image(_png_bytes(3000, 2000), mime_type="image/png")

    assert captured["mime_type"] == "image/jpeg"
    with Image.open(BytesIO(captured["data"])) as img:
        assert max(img.size) == 1024


async def test_gemini_understand_voice_returns_combined_result_in_one_call():
    """understand_voice() merges transcribe+extract into one generate_content
    call -- previously two sequential calls (~4.5s combined, measured). One
    call in, one JSON response out with transcript/translated_text/
    detected_language alongside the usual extraction fields.

    Phase B4 (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md): the mocked
    response uses the new "intents" envelope (a list), not the pre-B4 flat
    "semantic_type"/"fields" shape -- this is the real, intended prompt/
    response contract change, not a regression to work around."""
    captured: dict = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            captured["config"] = config
            captured["contents"] = contents
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "transcript": "ജെസിബി നാല് മണിക്കൂർ ഓടി",
                        "translated_text": "The JCB ran for 4 hours",
                        "detected_language": "Malayalam",
                        "intents": [
                            {
                                "semantic_type": "equipment_usage",
                                "fields": {"equipment_name": "JCB", "duration_hours": 4},
                                "missing_fields": [],
                                "field_confidences": {
                                    "equipment_name": 0.97,
                                    "duration_hours": 0.95,
                                },
                            }
                        ],
                    }
                )
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    result = await provider.understand_voice(b"audio-bytes", correlation_id="cor_1")

    assert captured["config"].response_mime_type == "application/json"
    assert result.transcript == "ജെസിബി നാല് മണിക്കൂർ ഓടി"
    assert result.translated_text == "The JCB ran for 4 hours"
    assert result.detected_language == "Malayalam"
    assert result.semantic_type == "equipment_usage"
    assert result.fields == {"equipment_name": "JCB", "duration_hours": 4}
    # One call, not two -- both the audio and the extraction prompt travel
    # together as a single `contents` payload.
    assert len(captured["contents"]) == 2


async def test_gemini_understand_voice_puts_the_speech_hint_first_and_only_when_given():
    """[258]: Manglish voice notes came back as English-sounding nonsense; the speaker's language and the company's
    own words now travel in the same (one) call, ahead of the transcription instructions. No hint: the prompt is
    as before."""
    prompts: list[str] = []

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            prompts.append(contents[0])
            return SimpleNamespace(text=json.dumps({"transcript": "x", "intents": []}))

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    hint = "Speaker uses Manglish. Likely words: Green Villa, Cement, M Sand, helper, mason."
    await provider.understand_voice(b"audio", correlation_id="cor_1", speech_hint=hint)
    await provider.understand_voice(b"audio", correlation_id="cor_2")

    with_hint, without = prompts
    assert with_hint.startswith("About the speaker") and hint in with_hint
    assert with_hint.endswith(without)  # the rest of the prompt is unchanged
    assert "About the speaker" not in without


async def test_gemini_transcribe_requests_json_with_translation_and_language():
    """transcribe() asks Gemini to transcribe, translate, and identify the
    source language in one call -- it used to only transcribe and silently
    copy the transcript into translated_text (no real translation ever
    happened), which the control panel's log viewer correctly flagged as
    "Translation did not run" on every non-English voice message. Regression
    coverage for that fix: response_mime_type must be set (structured JSON,
    not a bare transcript string) and thinking stays off (transcription/
    translation doesn't need reasoning)."""
    captured: dict = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            captured["config"] = config
            return SimpleNamespace(
                text=(
                    '{"transcript": "ജേസിബി ഓടി",'
                    ' "translated_text": "The JCB ran",'
                    ' "detected_language": "Malayalam"}'
                )
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(
        model="gemini-test", timeout_seconds=5, max_retries=0
    )
    provider._client = _aio(_FakeModels())

    result = await provider.transcribe(b"audio-bytes", correlation_id="cor_1")

    assert captured["config"].response_mime_type == "application/json"
    assert result.translated_text == "The JCB ran"
    assert result.detected_language == "Malayalam"


async def test_gemini_transcribe_falls_back_to_transcript_when_translation_missing():
    """A response that parses but omits translated_text must not silently
    lose the message -- transcript is a safe, always-available fallback
    (extract() reads either just fine, per the translate_to_english removal),
    unlike translate_to_english's stricter fail-loud guard."""

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(text='{"transcript": "hi there", "detected_language": "English"}')

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(
        model="gemini-test", timeout_seconds=5, max_retries=0
    )
    provider._client = _aio(_FakeModels())

    result = await provider.transcribe(b"audio-bytes", correlation_id="cor_1")

    assert result.transcript == "hi there"
    assert result.translated_text == "hi there"


async def test_gemini_translate_raises_when_translated_text_missing():
    """Regression test: a live bug where a Malayalam material report reached
    extraction/the control-panel logs viewer with NO translation ever having
    happened, no error, no warning anywhere -- translate_to_english used to
    default translated_text to the original input whenever Gemini's JSON
    response omitted that key, making a silently failed translation
    indistinguishable from a working one. It must now fail loud, exactly
    like a JSON-parse failure already does in this same method."""

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(text='{"detected_language": "ml"}')

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    with pytest.raises(MesiriError) as exc:
        await provider.translate_to_english(
            "ഇന്നൊരു 46 ചാക്ക് സിമൻറ് വന്നിട്ടുണ്ടായിരുന്നു", correlation_id="cor_x"
        )
    assert exc.value.error_code == "PROVIDER_MALFORMED_OUTPUT"
    assert exc.value.correlation_id == "cor_x"


async def test_gemini_translate_raises_when_translated_text_blank():
    """A present-but-empty translated_text is equally useless -- must also
    raise, not silently propagate an empty string as "the translation"."""

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(text='{"translated_text": "", "detected_language": "ml"}')

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    with pytest.raises(MesiriError):
        await provider.translate_to_english("hello", correlation_id=None)


async def test_gemini_translate_raises_when_text_unchanged_for_non_english_source():
    """Regression test: a SECOND, distinct silent-translation-failure mode
    found live after the missing-key fix above shipped -- Gemini returned a
    *populated* translated_text that was just the original Malayalam text
    echoed back verbatim (not omitted), for a message naming a project
    inline ("ഗ്രീൻവാലി"). The missing-key check doesn't catch this since
    translated_text isn't empty; a separate check is needed for "claims a
    non-English source but the text didn't change at all"."""

    malayalam_text = "ഗ്രീൻവാലിയിൽ എന്തൊക്കെ ഉണ്ട്"

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(
                text=json.dumps(
                    {"translated_text": malayalam_text, "detected_language": "Malayalam"}
                )
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    with pytest.raises(MesiriError) as exc:
        await provider.translate_to_english(malayalam_text, correlation_id="cor_z")
    assert exc.value.error_code == "PROVIDER_MALFORMED_OUTPUT"


async def test_gemini_translate_raises_when_reformatted_but_still_untranslated():
    """Regression test: a THIRD silent-failure variant found live -- Gemini
    reformatted punctuation/whitespace around otherwise-untouched Malayalam
    words (the input ended in a Malayalam question mark; the "translation"
    came back slightly different byte-for-byte but still 100% Malayalam),
    dodging the exact-equality check while the words stayed untranslated.
    _looks_untranslated (script-based, not string-equality) must catch this."""
    original = "മച്ചാനേ, നമ്മുടെ ഗ്രീൻ വാലിയിൽ എന്തൊക്കെ ഉണ്ട് എന്ന് പറയാമോ?"
    reformatted_but_still_malayalam = "മച്ചാനേ, നമ്മുടെ ഗ്രീൻ വാലിയിൽ എന്തൊക്കെ ഉണ്ട് എന്ന് പറയാമോ"  # noqa: RUF001

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "translated_text": reformatted_but_still_malayalam,
                        "detected_language": "Malayalam",
                    }
                )
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    with pytest.raises(MesiriError) as exc:
        await provider.translate_to_english(original, correlation_id="cor_v")
    assert exc.value.error_code == "PROVIDER_MALFORMED_OUTPUT"


async def test_gemini_translate_allows_genuine_translation_with_small_untranslated_proper_noun():
    """A real, working translation that leaves one proper noun in its
    original script (e.g. a project name genuinely left untransliterated)
    must NOT raise -- _looks_untranslated's 30% threshold exists precisely
    so a small embedded non-Latin name doesn't false-positive against an
    otherwise-correct English translation."""

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "translated_text": "How much cement is in stock at ഗ്രീൻവാലി?",
                        "detected_language": "Malayalam",
                    }
                )
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    result = await provider.translate_to_english(
        "ഗ്രീൻവാലിയിൽ എത്ര സിമന്റ് ഉണ്ട്?", correlation_id=None
    )
    assert result.translated_text == "How much cement is in stock at ഗ്രീൻവാലി?"


async def test_gemini_translate_allows_unchanged_text_when_source_is_already_english():
    """The prompt explicitly instructs returning the same text when the
    source is already English -- that legitimate no-op must NOT raise."""

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(
                text='{"translated_text": "50 bags of cement arrived", '
                '"detected_language": "English"}'
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    result = await provider.translate_to_english("50 bags of cement arrived", correlation_id=None)
    assert result.translated_text == "50 bags of cement arrived"


async def test_deepseek_translate_raises_when_translated_text_missing():
    """Same fail-loud regression coverage as the Gemini test above, for
    DeepSeek's equivalent (and previously identically silent) fallback."""
    from mesiri_ai.adapters.deepseek.adapter import DeepSeekExtractionProvider

    provider = DeepSeekExtractionProvider.__new__(DeepSeekExtractionProvider)
    provider._s = SimpleNamespace(
        api_key=None, base_url="https://example.test", timeout_seconds=5, max_retries=0,
        model="deepseek-test",
    )

    async def _fake_resilience(_raw, **kwargs):
        return {"choices": [{"message": {"content": '{"detected_language": "ml"}'}}]}, 42.0

    import mesiri_ai.adapters.deepseek.adapter as deepseek_module

    original = deepseek_module.call_with_resilience
    deepseek_module.call_with_resilience = _fake_resilience
    try:
        with pytest.raises(MesiriError) as exc:
            await provider.translate_to_english("ഹലോ", correlation_id="cor_y")
        assert exc.value.error_code == "PROVIDER_MALFORMED_OUTPUT"
    finally:
        deepseek_module.call_with_resilience = original


async def test_deepseek_translate_raises_when_text_unchanged_for_non_english_source():
    """DeepSeek equivalent of the Gemini "populated but unchanged" regression
    above -- same silent-failure shape, same fail-loud fix."""
    from mesiri_ai.adapters.deepseek.adapter import DeepSeekExtractionProvider

    malayalam_text = "ഗ്രീൻവാലിയിൽ എന്തൊക്കെ ഉണ്ട്"
    provider = DeepSeekExtractionProvider.__new__(DeepSeekExtractionProvider)
    provider._s = SimpleNamespace(
        api_key=None, base_url="https://example.test", timeout_seconds=5, max_retries=0,
        model="deepseek-test",
    )

    async def _fake_resilience(_raw, **kwargs):
        content = json.dumps({"translated_text": malayalam_text, "detected_language": "ml"})
        return {"choices": [{"message": {"content": content}}]}, 42.0

    import mesiri_ai.adapters.deepseek.adapter as deepseek_module

    original = deepseek_module.call_with_resilience
    deepseek_module.call_with_resilience = _fake_resilience
    try:
        with pytest.raises(MesiriError) as exc:
            await provider.translate_to_english(malayalam_text, correlation_id="cor_w")
        assert exc.value.error_code == "PROVIDER_MALFORMED_OUTPUT"
    finally:
        deepseek_module.call_with_resilience = original


# ---------------------------------------------------------------------------
# Phase B4 (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md): extract()
# parses the new "intents" envelope end-to-end, through the real adapter
# code (not just parse_extracted_intents in isolation -- see
# test_extraction_result.py for that). The Bidilaj trace (§1) is used
# directly: it is the real message that motivated this phase, simulated as
# the JSON a live model would return for it.
# ---------------------------------------------------------------------------

_BIDILAJ_INTENTS_JSON = {
    "detected_language": "Malayalam",
    "intents": [
        {"semantic_type": "project_create", "fields": {"name": "Bidilaj"}},
        {"semantic_type": "site_create", "fields": {"name": "Site A"}},
        {
            "semantic_type": "add_project_member",
            "fields": {"member_name": "Usman", "role": "site_engineer"},
        },
    ],
}


async def test_gemini_extract_parses_the_bidilaj_trace_into_three_intents():
    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(text=json.dumps(_BIDILAJ_INTENTS_JSON))

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    result = await provider.extract(
        "Add a new project, a project named Bidilaj, and then create a site "
        "called Site A. Then I need to add an engineer, a site engineer, "
        "named Usman.",
        correlation_id="cor_bidilaj",
    )

    assert result.detected_language == "Malayalam"
    assert len(result.intents) == 3
    assert [i.semantic_type for i in result.intents] == [
        "project_create",
        "site_create",
        "add_project_member",
    ]
    assert result.intents[0].fields == {"name": "Bidilaj"}
    assert result.intents[2].fields["member_name"] == "Usman"
    # events[0]-style pre-B5 callers still see a coherent single answer.
    assert result.semantic_type == "project_create"


async def test_gemini_extract_single_intent_response_still_works():
    """The overwhelmingly common case -- a real model returning exactly one
    entry in intents, unchanged in effect from before B4."""

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "detected_language": "English",
                        "intents": [
                            {
                                "semantic_type": "expense",
                                "fields": {"amount": 500, "vendor": "ABC Hardware"},
                                "missing_fields": [],
                                "field_confidences": {"amount": 0.95},
                            }
                        ],
                    }
                )
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-test", timeout_seconds=5, max_retries=0)
    provider._client = _aio(_FakeModels())

    result = await provider.extract("paid 500 to ABC Hardware", correlation_id="cor_1")

    assert len(result.intents) == 1
    assert result.semantic_type == "expense"
    assert result.fields == {"amount": 500, "vendor": "ABC Hardware"}


async def test_deepseek_extract_parses_the_bidilaj_trace_into_three_intents():
    provider = DeepSeekExtractionProvider.__new__(DeepSeekExtractionProvider)
    provider._s = SimpleNamespace(
        api_key=None, base_url="https://example.test", timeout_seconds=5, max_retries=0,
        model="deepseek-test",
    )

    async def _fake_resilience(_raw, **kwargs):
        content = json.dumps(_BIDILAJ_INTENTS_JSON)
        return {"choices": [{"message": {"content": content}}]}, 42.0

    import mesiri_ai.adapters.deepseek.adapter as deepseek_module

    original = deepseek_module.call_with_resilience
    deepseek_module.call_with_resilience = _fake_resilience
    try:
        result = await provider.extract(
            "Add a new project, a project named Bidilaj, and then create a "
            "site called Site A. Then I need to add an engineer, a site "
            "engineer, named Usman.",
            correlation_id="cor_bidilaj",
        )
    finally:
        deepseek_module.call_with_resilience = original

    assert len(result.intents) == 3
    assert [i.semantic_type for i in result.intents] == [
        "project_create",
        "site_create",
        "add_project_member",
    ]
    assert result.intents[1].fields == {"name": "Site A"}
