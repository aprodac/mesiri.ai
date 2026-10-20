"""CapabilityHelpService — unit tests (fake provider, no network)."""

from __future__ import annotations

import json

import pytest

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.capability_help import CapabilityHelpService


class FakeJsonGeneration:
    """Records the prompts it was given and replays a canned completion."""

    def __init__(self, reply: str = '{"keys": []}', *, raises: Exception | None = None) -> None:
        self._reply = reply
        self._raises = raises
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None
        self.calls = 0

    async def generate_json(
        self, system_prompt: str, user_prompt: str, *, correlation_id: str | None = None
    ) -> str:
        self.calls += 1
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        if self._raises is not None:
            raise self._raises
        return self._reply


async def test_matches_are_returned_in_model_order():
    provider = FakeJsonGeneration(
        json.dumps({"keys": ["finance.transfer", "finance.petty_cash"]})
    )
    matched = await CapabilityHelpService(provider).match("how do I move money?")
    assert matched == (WorkflowKey.TRANSFER, WorkflowKey.PETTY_CASH)


async def test_the_catalogue_sent_to_the_model_comes_from_the_registry():
    """The prompt is built from the live registry, which is what stops help
    from describing a capability that doesn't exist -- and from missing one
    that does."""
    provider = FakeJsonGeneration()
    await CapabilityHelpService(provider).match("anything")

    assert provider.user_prompt is not None
    catalogue = json.loads(provider.user_prompt.split("CATALOGUE:\n", 1)[1].split("\n\nQUESTION")[0])
    keys = {entry["key"] for entry in catalogue}
    # A spread across categories, including ones no hand-written menu ever
    # mentioned.
    assert {"material.receipt", "finance.reverse", "dpr.request", "automation.setup"} <= keys
    # Never the system-triggered one.
    assert "labour.worker_promotion" not in keys


async def test_a_hallucinated_key_is_dropped():
    provider = FakeJsonGeneration(json.dumps({"keys": ["finance.teleport", "finance.transfer"]}))
    matched = await CapabilityHelpService(provider).match("q")
    assert matched == (WorkflowKey.TRANSFER,)


async def test_duplicate_keys_are_collapsed():
    provider = FakeJsonGeneration(
        json.dumps({"keys": ["finance.transfer", "finance.transfer"]})
    )
    assert await CapabilityHelpService(provider).match("q") == (WorkflowKey.TRANSFER,)


async def test_more_than_three_matches_are_capped():
    provider = FakeJsonGeneration(
        json.dumps(
            {
                "keys": [
                    "finance.transfer",
                    "finance.petty_cash",
                    "expense.submit",
                    "finance.reverse",
                ]
            }
        )
    )
    assert len(await CapabilityHelpService(provider).match("q")) == 3


@pytest.mark.parametrize("reply", ["not json at all", "{}", '{"keys": "nope"}', "[]", "null"])
async def test_a_malformed_completion_degrades_to_no_matches(reply: str):
    """Help is where a confused user goes. A bad completion must fall back to
    the full menu, never to an error."""
    assert await CapabilityHelpService(FakeJsonGeneration(reply)).match("q") == ()


async def test_a_provider_failure_degrades_to_no_matches():
    provider = FakeJsonGeneration(raises=TimeoutError("provider down"))
    assert await CapabilityHelpService(provider).match("q") == ()


async def test_a_restricted_workflow_is_never_offered_to_a_role_that_cannot_use_it():
    """A site engineer asking "how do I add someone to the project?" must not
    be taught a workflow whose role gate will refuse them."""
    provider = FakeJsonGeneration(json.dumps({"keys": ["project.add_member"]}))
    service = CapabilityHelpService(provider)

    assert await service.match("q", role="SITE_ENGINEER") == ()
    assert await service.match("q", role="PROJECT_MANAGER") == (WorkflowKey.ADD_PROJECT_MEMBER,)


async def test_the_restricted_workflow_is_absent_from_the_prompt_too():
    """Not just filtered from the answer -- never offered to the model at
    all, so it cannot be suggested in the first place."""
    provider = FakeJsonGeneration()
    await CapabilityHelpService(provider).match("q", role="SITE_ENGINEER")

    assert provider.user_prompt is not None
    assert "project.add_member" not in provider.user_prompt
    assert "finance.account_admin" not in provider.user_prompt
    # Open workflows are still there.
    assert "material.receipt" in provider.user_prompt


async def test_an_unknown_role_still_sees_the_open_workflows():
    provider = FakeJsonGeneration(json.dumps({"keys": ["material.receipt"]}))
    service = CapabilityHelpService(provider)
    assert await service.match("q", role="SOMETHING_NEW") == (WorkflowKey.MATERIAL_RECEIPT,)


async def test_kind_is_returned_and_smalltalk_is_recognised():
    provider = FakeJsonGeneration('{"keys": [], "kind": "smalltalk"}')
    answer = await CapabilityHelpService(provider).answer("are you hardcoded")
    assert answer.kind == "smalltalk" and answer.keys == ()


@pytest.mark.parametrize(
    "reply",
    ['{"keys": []}', '{"keys": [], "kind": "weird"}', '{"keys": [], "kind": 3}', "not json", "[]"],
)
async def test_a_missing_or_bad_kind_falls_back_to_capability(reply: str):
    answer = await CapabilityHelpService(FakeJsonGeneration(reply)).answer("what can you do")
    assert answer.kind == "capability"


async def test_a_provider_failure_is_a_capability_answer():
    provider = FakeJsonGeneration(raises=RuntimeError("down"))
    answer = await CapabilityHelpService(provider).answer("hi")
    assert answer.kind == "capability" and answer.keys == ()
