# WhatsApp call echo (WA-118 step 1)

Answers a real WhatsApp call on the live number and plays the caller's voice back. Only the numbers in
`CALL_SPIKE_ALLOWED` are answered, one call at a time, for two minutes at most. Any other caller rings out, as today.
Messages are not touched. Plan: [whatsapp-calling-plan.md](../../docs/plans/whatsapp-calling-plan.md).

## Run it on the server

Run these as root on the server, after the commit with `ingress/calls_forward.py` has deployed.

```bash
ufw allow 40000:40099/udp comment 'WA-118 call spike'
```

If the hosting provider has its own firewall, open UDP 40000-40099 there too. Then install it apart from the app:

```bash
cd /opt/mesiri/spikes/whatsapp_call_echo && python3 -m venv /opt/call-spike-venv && /opt/call-spike-venv/bin/pip install -r requirements.txt
```

Point the app at it, then restart the app:

```bash
echo 'WHATSAPP_CALLS_FORWARD_URL=http://127.0.0.1:8791/calls' >> /opt/mesiri/.env && systemctl restart mesiri
```

Start the spike, with the tester's number in international form and no `+`:

```bash
set -a; . /opt/mesiri/.env; set +a; CALL_SPIKE_ALLOWED=91XXXXXXXXXX /opt/call-spike-venv/bin/python /opt/mesiri/spikes/whatsapp_call_echo/echo.py
```

The `.env` must hold `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET` and `WHATSAPP_PHONE_NUMBER_ID`.

## What to look for

Call Mesiri's WhatsApp number from the allowed phone and speak.

| Log line or result | Answers |
| --- | --- |
| `calls webhook arrived` | Does an app in "In development" mode get `calls` webhooks |
| You hear yourself | Does audio pass the firewall without TURN |
| `accepted after`, `audio connected after` | How fast the call connects |
| `cpu% one core` | CPU per call |

## Undo

Stop the spike with Ctrl+C. Then:

```bash
sed -i '/^WHATSAPP_CALLS_FORWARD_URL=/d' /opt/mesiri/.env && systemctl restart mesiri
```

```bash
ufw delete allow 40000:40099/udp
```

## Tests

From this folder, in an environment with `requirements.txt` plus `pytest`, `pytest-asyncio` and `httpx`:

```bash
python -m pytest test_echo.py -q -o asyncio_mode=auto
```
