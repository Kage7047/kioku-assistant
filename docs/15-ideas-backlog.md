# Ideas backlog — Kioku features for later

Parked feature ideas, roughly ranked. Not committed to a phase yet.

## Voice notes  *(nice-to-have, later)*
Send Kioku a **Telegram voice message** → it transcribes it and acts on it (capture, ask, command —
whatever the transcript says). The ingest pipeline already handles files/photos, so most of the wiring
exists; the missing piece is audio → text (Whisper API, or a Composio/OpenAI transcription call) in
`telegram_bot.on_voice` + `ingest`. Very Kioku; low urgency. **User: "nice idea for later."**

## Full browser automation  *(bigger build, needs the Docker image + testing)*
Kioku has `WebSearch` + `WebFetch` (read a page) but **no click-through browser** — it can't log in,
navigate a JS-heavy app, or view a Google Business Profile interactively. Real headless browsing needs
Playwright + Chromium in the worker image (~500MB) or a hosted browser MCP (browserbase / Composio
browser tool). Relevant for the "Google Maps Rescue" side-business (viewing profiles). Deferred because
it can't be tested from a dev box and inflates the image. Revisit when that business is active.

## Others (captured in passing)
- **Contextual "what are we working on" state** — a short-lived working-context note the assistant keeps
  current so a chat thread doesn't cold-start.
- **iOS Shortcut / share-sheet capture** — POST to `/inbox` from the phone (endpoint already exists).
- **Deeper People-CRM** — contact timelines, auto-prep before any calendar meeting with a known person.
