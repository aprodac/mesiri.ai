#!/usr/bin/env bash
# Control panel (superadmin) at https://control.mesiri.ai (INF-15). Run on the
# VPS by .github/workflows/deploy.yml after the builds are uploaded
# (/var/www/mesiricontrol). Idempotent; each step runs only while not done:
#
#   1. a port-80 server block for control.mesiri.ai (harmless before DNS);
#   2. once control.mesiri.ai reaches this server: a Let's Encrypt
#      certificate (certbot --nginx, which adds the HTTPS lines);
#   3. once the certificate exists: api.whatsapp.mesiri.ai/mesiriadmin
#      redirects to https://control.mesiri.ai (path kept).
#
# Until DNS points here it stops after step 1 with a notice, and the old
# address keeps serving the control panel as before.
#
# Every edit is checked with `nginx -t` and undone if it fails.
# Rollback by hand: rm /etc/nginx/sites-enabled/control.mesiri.ai.conf, copy the
# newest /root/<api conf>.bak.<time> back, nginx -t, systemctl reload nginx.
# Tracked copies of the final configs: infra/nginx/*.conf.
set -euo pipefail

HOST=control.mesiri.ai
WEBROOT=/var/www/mesiricontrol
SITE=/etc/nginx/sites-available/${HOST}.conf
ENABLED=/etc/nginx/sites-enabled/${HOST}.conf

reload_or() {  # reload_or <undo command...>: nginx -t, then reload or undo.
  if nginx -t; then
    systemctl reload nginx
  else
    "$@"
    echo "::error::nginx -t failed; change undone"
    exit 1
  fi
}

# 1. Port-80 server block.
if [ ! -e "$ENABLED" ]; then
  cat > "$SITE" << CONF
# Mesiri control panel (superadmin), INF-15. Written by
# infra/deploy/nginx_control_panel.sh; certbot adds HTTPS.
server {
    listen 80;
    server_name ${HOST};
    root ${WEBROOT};
    index index.html;
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
CONF
  ln -s "$SITE" "$ENABLED"
  reload_or rm -f "$ENABLED" "$SITE"
  echo "nginx: ${HOST} port-80 block added"
fi

# 2. Certificate, once the name resolves. Let's Encrypt checks from outside,
#    so this server fetching its own name is no test: the first run (24 Oct)
#    could not, though the name already served from outside. A failed
#    certbot changes nothing and is retried on the next deploy.
if [ ! -d "/etc/letsencrypt/live/${HOST}" ]; then
  if ! getent ahostsv4 "$HOST" > /dev/null; then
    echo "::notice::${HOST} does not resolve yet (DNS). Control panel stays on api.whatsapp.mesiri.ai/mesiriadmin for now."
    exit 0
  fi
  if ! certbot --nginx -d "$HOST" --non-interactive --agree-tos --redirect; then
    echo "::warning::certbot could not get a certificate for ${HOST}; retried on the next deploy. Old address unchanged."
    exit 0
  fi
  echo "certbot: certificate for ${HOST} issued"
fi

# 3. Old address redirects.
API_CONF=$(grep -rl "server_name api.whatsapp.mesiri.ai;" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1 || true)
if [ -z "$API_CONF" ]; then
  echo "::error::nginx config for api.whatsapp.mesiri.ai not found"
  exit 1
fi
API_CONF=$(readlink -f "$API_CONF")
if grep -q "https://${HOST}/" "$API_CONF"; then
  echo "nginx: control panel on https://${HOST} (old address already redirects)"
  exit 0
fi
BACKUP="/root/$(basename "$API_CONF").bak.$(date +%s)"
cp "$API_CONF" "$BACKUP"
python3 - "$API_CONF" "$HOST" << 'PY'
import re
import sys

conf, host = sys.argv[1], sys.argv[2]
text = open(conf).read()
pattern = re.compile(r"location \^~ /mesiriadmin \{[^}]*\}")
if not pattern.search(text):
    sys.exit("could not find the /mesiriadmin location in " + conf)
text = pattern.sub(
    "location ^~ /mesiriadmin {\n"
    f"        rewrite ^/mesiriadmin/?(.*)$ https://{host}/$1 permanent;\n"
    "    }",
    text,
    count=1,
)
open(conf, "w").write(text)
PY
reload_or cp "$BACKUP" "$API_CONF"
echo "nginx: api.whatsapp.mesiri.ai/mesiriadmin now redirects to https://${HOST}"
