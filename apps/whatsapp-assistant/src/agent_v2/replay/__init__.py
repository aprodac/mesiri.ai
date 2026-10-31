"""Request 185: replay real conversations through the assistant and measure the experience.

``corpus``  real WhatsApp conversations (fetched read-only from production, kept OUT of the repo)
``checks``  hard, deterministic UX checks: one per failure seen live 27-31 Oct
``report``  the per-conversation and total numbers, as text

The same checks run on what production actually answered (the baseline) and on what a new
engine answers when the conversation is replayed (tests/agent_v2/test_replay_live.py).
"""
