#!/bin/bash
R="$(cd "$(dirname "$0")/../../.." && pwd)"; PG=/usr/lib/postgresql/16/bin; D=/var/tmp/mesiri-pg
su postgres -c "$PG/pg_ctl -D $D/data status" >/dev/null 2>&1 || su postgres -c "$PG/pg_ctl -D $D/data -l $D/log -o '-p 5432 -k /var/tmp' start" >/dev/null
sleep 1
export MESIRI_POSTGRES__HOST=127.0.0.1
(cd $R/backend && timeout 300 python -m alembic upgrade head 2>&1 | tail -1)
pkill -f "uvicorn main:app"; sleep 1
cd $R/apps/whatsapp-assistant/src
export PYTHONPATH="$R/backend/src:$R/shared/contracts/src:$R/platform/ai/src:$R/apps/whatsapp-assistant/src" WHATSAPP_VERIFY_TOKEN=x WHATSAPP_APP_SECRET=x WHATSAPP_ACCESS_TOKEN=x
nohup python -m uvicorn main:app --port 8000 > /var/tmp/app.log 2>&1 &
for i in $(seq 1 60); do curl -s -m 2 localhost:8000/health >/dev/null && echo "app up" && exit 0; sleep 2; done
echo "app failed"; tail -20 /var/tmp/app.log
