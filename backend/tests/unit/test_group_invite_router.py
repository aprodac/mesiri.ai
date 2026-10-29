"""WA-87: the mesiri_group_invite template button redirects through here
because Meta refuses a button linking straight to chat.whatsapp.com."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from mesiri.domains.organizations.group_invite_router import whatsapp_group_invite


async def test_a_valid_code_redirects_to_the_real_whatsapp_invite() -> None:
    response = await whatsapp_group_invite("AbCdEfGhIjK1234567890")
    assert response.status_code == 302
    assert response.headers["location"] == "https://chat.whatsapp.com/AbCdEfGhIjK1234567890"


@pytest.mark.parametrize(
    "code",
    [
        "short",  # under 10 chars
        "x" * 33,  # over 32 chars
        "has a space",
        "../../etc/passwd",
        "javascript:alert(1)",
    ],
)
async def test_a_malformed_code_is_refused(code: str) -> None:
    with pytest.raises(HTTPException) as refused:
        await whatsapp_group_invite(code)
    assert refused.value.status_code == 404
