"""UX-102 (22 Nov 2026, Ilan, in the sample company's Tell Mesiri: "even after selecting site it always keeps asking
in loop"): WhatsApp sends a button's title with its tap; the dashboard's Tell Mesiri, the Live deck and the mobile
app send only the button's id, and the web route made the message's text that id. "Annex" arrived as
``apiag:opt:<question>:0``: it named no site, so the held lines were asked about again, every tap.

The class: every option button tapped outside WhatsApp (a site, a trade, a material, a person). The fix reads the
title from the question that was asked, for every channel. Guards: a tap with its title (WhatsApp) is unchanged; a
tap on an earlier question's button is still answered by the code as closed.
"""

from __future__ import annotations

from tests.agent_api.test_api_question_buttons_266 import (
    CLOSED,
    SHIFT,
    TRADE,
    _asked,
    _options,
    _say,
)
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _stand_in_tools  # noqa: F401

from agent_api import whatsapp as wa


def _heard(h: Harness) -> list[str]:
    """Record the words each message reaches the model with."""
    heard: list[str] = []
    real = h.service._on_words

    async def spy(said, message, ctx, **kw):
        heard.append(said)
        return await real(said, message, ctx, **kw)

    h.service._on_words = spy  # type: ignore[method-assign]
    return heard


async def test_the_reported_tap_with_only_its_id_is_read_as_its_title() -> None:
    h = await _asked(TRADE)
    heard = _heard(h)
    tap = _options(h)[1]
    await _say(h, tap, ["Sheri, 5 helper."], tap=tap)  # the web route: text is the id
    assert heard == ["Helper"]
    assert h.sent[-1].text.startswith("Sheri, 5 helper.")


async def test_sibling_a_tap_with_no_text_at_all_is_read_as_its_title() -> None:
    h = await _asked(TRADE)
    heard = _heard(h)
    await _say(h, "", ["Sheri, 5 mason."], tap=_options(h)[0])
    assert heard == ["Mason"]


async def test_guard_a_whatsapp_tap_with_its_title_is_unchanged() -> None:
    h = await _asked(TRADE)
    heard = _heard(h)
    await _say(h, "Mason", ["Sheri, 5 mason."], tap=_options(h)[0])
    assert heard == ["Mason"]


async def test_guard_an_earlier_questions_button_sent_as_its_id_is_still_closed() -> None:
    h = await _asked(TRADE)
    old = _options(h)
    await _say(h, "vere oru karyam: ethu shift ennu chodikku", [[SHIFT], "Which shift?"])
    await _say(h, old[0], ["THE MODEL MUST NOT BE ASKED"], tap=old[0])
    assert h.sent[-1].text.startswith(CLOSED)


def test_a_button_id_names_its_number() -> None:
    assert wa.question_of("apiag:opt:q1:2") == "q1"
