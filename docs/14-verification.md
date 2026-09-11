# Verification runbook — confirm the live system

A lot shipped fast and can't be tested from a dev box (no Agent SDK, no Railway/Composio/Telegram
access). Run this once in Telegram + the dashboard to confirm it all works, then report what breaks.
Ordered by importance: the top items verify the paths most likely to be misconfigured.

## 0. Deploy health
- [ ] Railway: **api** and **worker** both green; `/health` returns `{ok:true}`.
- [ ] Telegram `/start` → the capability list (proves the bot + api are up).

## 1. Command precision (the old hijack bug)
- [ ] "what's my grocery budget this month?" → **answers the question** (does NOT dump budget stats).
- [ ] `/budget` → the credit/mode line.
- [ ] "learn python for the interview" → a real answer (NOT the weekly-learning task).

## 2. Formatting & files on mobile
- [ ] Any answer → **bold / links / bullets render** (not raw `**` or `[x](url)`).
- [ ] `opportunities` (or `introspect`) → arrives as a **document** you can open on your phone.

## 3. Composio — the linchpin (Gmail / Calendar / Drive)
The code shape is confirmed correct; this checks the connection + `COMPOSIO_API_KEY`.
- [ ] "what's on my calendar this week?" → **real events** (not "I can't access your calendar").
- [ ] "any important unread mail?" → reads real mail.
- [ ] If either fails: check `COMPOSIO_API_KEY` (and `COMPOSIO_USER_ID` if not 'default') on the **worker**.

## 4. Vault — activate your notes
- [ ] `organize` → progress notices ("digested N notes… M left"); repeat over a few days until 0 left.
- [ ] Recall something from an imported note ("what did I discuss about the Visa role?") → real recall.

## 5. Self-scheduling (end to end)
- [ ] "send me a one-line hello every day at HH:MM" (pick 3–4 min out) → it confirms + schedules.
- [ ] At HH:MM → the message arrives. Check `system/schedules.json` in the vault shows it.
- [ ] "remove that scheduled task" (or delete the line) → gone.

## 6. Acting with the gate
- [ ] "prep me for my next meeting" → a briefing (pulls calendar + notes).
- [ ] "draft a reply to <a recruiter thread>" → a **Gmail draft** appears in your Gmail (nothing sent).
- [ ] "put a focus block tomorrow 3–4pm on my calendar" → the event is **created** (auto, no approval).

## 7. Proactivity on demand
- [ ] `ideas` → 1–3 concrete proposals + file. `opportunities` → fit-scored roles. `introspect` → cost/errors/**cache hit ratio**.

## 8. On/off + limits
- [ ] `/pause` → then send anything → "paused" reply; `/resume` → back to normal.
- [ ] (When you actually hit a usage limit) → a clear "usage limit reached" reply within ~3 min, NOT a long "stale".

## 9. Scheduled proactive (arrive on their own)
- [ ] Morning **07:00 local** → the brief (calendar + mail + dev/ops).
- [ ] Over the week: Wed 10:00 proposals; Mon/Thu 08:00 opportunities; Sun review/learn/self-review.

## If something breaks
Tell me: which step, what you sent, what came back (screenshot if formatting). Most likely culprits and
fixes are config, not code: `COMPOSIO_API_KEY` (Composio), `DASHBOARD_TOKEN` + a public domain (dashboard),
`TIMEZONE` (brief timing), embeddings keys (recall quality). I'll fix whatever the test surfaces.
