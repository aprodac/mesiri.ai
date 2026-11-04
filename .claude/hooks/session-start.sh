#!/bin/bash
# TM-77: every session first sees what is already being worked on. Prints only; never fails the session.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -n "${TEAMMATE_TOKEN:-}" ] || { echo "Request log not reachable (no TEAMMATE_TOKEN)."; exit 0; }
echo "Being worked on now (don't start these again; add to one with: inbox.py item note <n> ...):"
TEAMMATE_PROJECT="${TEAMMATE_PROJECT:-mesiri}" timeout 10 python3 teammate/inbox.py items --status in_progress 2>/dev/null | head -25
echo "Check in on yours: python3 teammate/inbox.py item start <n>  (then item usage / item done --cost)"
echo "New problem? item add checks for repeats. Between steps: inbox.py limits; at HAND OVER: item handover <n> --note ..."
exit 0
