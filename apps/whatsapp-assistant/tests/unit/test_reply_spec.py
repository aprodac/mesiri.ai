"""channel/replies.py's ReplySpec: WA-14 media fields, their exclusivity
rules, and with_prefix keeping every field."""

from __future__ import annotations

import dataclasses

import pytest

from channel.replies import CtaLink, ListRow, ReplyDocument, ReplySpec


def test_existing_constructions_are_unchanged():
    reply = ReplySpec(text="hi", buttons=(ListRow("y", "Yes"),))
    assert reply.image is None and reply.document is None and reply.cta is None


def test_image_and_document_are_mutually_exclusive():
    with pytest.raises(ValueError):
        ReplySpec(text="x", image=b"png", document=ReplyDocument(b"%PDF", "a.pdf"))


@pytest.mark.parametrize(
    "extra",
    [{"buttons": (ListRow("y", "Yes"),)}, {"list_rows": (ListRow("a", "A"),)}],
)
def test_cta_cannot_carry_buttons_or_a_list(extra):
    with pytest.raises(ValueError):
        ReplySpec(text="x", cta=CtaLink("Open", "https://e.x"), **extra)


def test_with_prefix_keeps_every_field():
    """The five call sites that prepend a confirmation used to copy fields
    by hand and would have silently dropped any new one."""
    original = ReplySpec(
        text="Which site?",
        list_button_label="Choose",
        list_rows=(ListRow("s1", "Block A"),),
        image=b"png",
    )

    prefixed = original.with_prefix("Saved.")

    assert prefixed.text == "Saved.\n\nWhich site?"
    for f in dataclasses.fields(ReplySpec):
        if f.name != "text":
            assert getattr(prefixed, f.name) == getattr(original, f.name), f.name
