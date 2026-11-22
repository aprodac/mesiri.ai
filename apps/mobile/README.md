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

## The look: the blueprint system (MOB-14, 22 Nov 2026)

Design: canvas page V4 and [mobile-ux-v2-plan.md](../../docs/plans/mobile-ux-v2-plan.md) §4c–4d. Tokens in
`src/theme.ts`, parts in `src/components/ui.tsx`; new screens use those, never their own colours or sizes.

- **Colours, one job each:** paper `#f8f7f3` (ground), white cards, drawing ink `#15233f` (words, structure, the
  bottom bar, navy actions), blueprint `#1e3a6e` (the one hero per screen; its drawing grid only on Today's title
  block), highlighter yellow `#ffd23f` (do this now), brick `#c4472f` (something is wrong).
- **Four cues, the same everywhere:**
  - `CategoryTile`: what kind of thing (people, work, materials, machines, problems, photos, weather), one tinted tile
    and icon each (`category` in the theme).
  - `StateMark`: what state, by shape and colour: done ✓, to tell (dashed), needs attention !, waiting, not saved yet
    (dashed yellow), from your voice.
  - `TimeChip`: how urgent: solid = act now (OVERDUE, TODAY, ANSWERED), outlined = know it (TOMORROW, OPEN).
  - Actions: **one `accent` (yellow) button per screen**, `primary` navy on a card, `secondary` outline, `text` to look;
    `MesiriPanel` whenever Mesiri talks.
- **Soft shapes:** cards 18–22 px, pill buttons and chips. The bottom bar is a floating ink pill with the yellow mic.
- **Type:** Archivo Narrow headings (swap in `family`), Archivo text, JetBrains Mono for figures and references.
  Malayalam falls back to the phone's Noto Sans.

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
