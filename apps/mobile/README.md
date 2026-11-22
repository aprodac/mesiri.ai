# Mesiri mobile app (site engineer)

The site engineer's day on a phone: **Today** (the site's day as rows), **Site** (stock), **Requests**, **More**,
and the mic in the middle of the bottom bar that speaks to the same Mesiri as WhatsApp.
Design and build order: [docs/plans/mobile-site-engineer-plan.md](../../docs/plans/mobile-site-engineer-plan.md)
(tracker section MOB).

Expo 54 + expo-router. Every call is the dashboard's own API, as the signed-in person.

## Run it

```bash
pnpm install --filter @mesiri/mobile...
cd apps/mobile
EXPO_PUBLIC_API_URL=http://<your-computer's-ip>:8000 npx expo start   # Expo Go on an Android phone
```

Without `EXPO_PUBLIC_API_URL` the app talks to production (`https://api.whatsapp.mesiri.ai`).
After changing it, start with `--clear`: Metro caches the old value.

To look at the screens in a browser (Chromium at 390 px): `npx expo export --clear --platform web`, then serve
`dist/`. The browser build is for looking only: Chrome records WebM, which the voice route refuses; phones
record m4a, which it takes.

## The look (MOB-13, 22 Nov 2026)

Swiss minimal, built for a site, easy on the eye. Tokens and type in `src/theme.ts`, parts in
`src/components/ui.tsx`; new screens use those, never their own colours or sizes.

- **Paper and ink:** warm off-white ground (`#f2f0eb`), cards a shade lighter, near-black ink (`#17191c`). No pure
  white, no pure black, no shadows; hairlines (`line`) separate things.
- **One accent, used sparingly:** safety yellow (`#f2c230`) only as a fill: the mic, the progress tape, the active
  tab's bar, "from your voice", the main choice on the dark Speak screen. Never as text on paper.
- **Main buttons are ink** with a yellow icon; secondary is a hairline outline.
- **Type:** Inter Tight for headings and figures (tabular), Inter for reading, IBM Plex Mono capitals for labels and
  references ("01", "GREEN VILLA", "REQ-0012"), like a drawing. Malayalam falls back to the phone's Noto Sans.
- **Construction, quietly:** a 3 px hazard stripe on the main screens, numbered rows, the day as a segmented tape,
  stock as gauges (days left against two weeks), square status marks (tick outline / dashed plus / brick !).
- **Site sizes:** 48 px targets, 54 px main actions, 64 px mic (88 px on Speak).

## Where things are

| | |
|---|---|
| `app/` | Screens (expo-router): `(app)/` the four tabs, `speak.tsx`, `switch-site.tsx`, `day/[section].tsx`, `login.tsx` |
| `src/lib/mesiri.ts` | The API routes the app uses, with their shapes |
| `src/lib/session.tsx` | Who is signed in; the working site |
| `src/lib/day.ts` | The site's day as Today's rows |
| `src/lib/i18n.tsx` | The app's words, English and Malayalam |
| `src/lib/recorder.ts` | Voice note settings (AAC in .m4a, mono, 16 kHz, up to 60 s) |
| `src/theme.ts` | Brand colours and sizes (48 px touch targets, 56 px main actions, 72 px mic) |

`react`, `react-dom` and `react-native` are pinned to what Expo 54 expects (19.1.0 / 0.81.5); the dashboard
uses a newer React, and a mismatch renders nothing.
