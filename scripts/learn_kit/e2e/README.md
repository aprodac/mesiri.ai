# Playing the guided project end to end (local, real app + real Postgres)

Used 17 Nov 2026 to play chapters "Set up Green Villa" and "The BOQ" (SS-69 part 1) start to finish. Not CI.

```bash
# 1. Postgres 16 (one-time, as root): initdb into /var/tmp/mesiri-pg/data as user postgres, then
#    CREATE ROLE mesiri LOGIN SUPERUSER PASSWORD 'mesiri_local_dev'; CREATE DATABASE mesiri OWNER mesiri;
# 2. Start Postgres, migrate, start the API on :8000 (dummy WhatsApp settings: nothing can be sent)
scripts/learn_kit/e2e/up.sh
# 3. The dashboard on :5173
(cd apps/dashboard && npx vite --port 5173 &)
# 4. A fresh real company + owner token (a sandbox is made from it when the guided project starts)
PYTHONPATH=backend/src MESIRI_POSTGRES__HOST=127.0.0.1 python scripts/learn_kit/e2e/make_real_company.py > /tmp/real.json
# 5. Optional: choose the kind of person (new_to_construction | guided | bring_data | switching | free)
curl -s -X PUT -H "Authorization: Bearer $(python3 -c "import json;print(json.load(open('/tmp/real.json'))['token'])")" \
  -H 'Content-Type: application/json' -d '{"start_mode":"new_to_construction"}' localhost:8000/me/start-mode
# 6. Play it (Playwright; prints each step's title and words, screenshots into the folder)
mkdir -p /tmp/journey && (cd apps/dashboard && NODE_PATH=$(npm root -g) node ../../scripts/learn_kit/e2e/play_journey.cjs /tmp/real.json /tmp/journey new_to_construction)
```

The script does each "your turn" the way a person would (types the dates, fills the contract dialog, uploads the
kit's estimate, taps a wrong then the right line, Add all, picks 4.1 Plastering). Extend it for each new chapter.
Don't press Escape in it: Escape stops the guide.

`audit_chapters.cjs` (UX-107) jumps to chapters from the bubble's list and logs, per step, the address it opened, what it
lit and a screenshot (`node audit_chapters.cjs /tmp/real.json /tmp/audit 5 15`; `APP=` for another dashboard address).
It presses Next / Skip through every "Your turn", so later chapters run on what was not done.
