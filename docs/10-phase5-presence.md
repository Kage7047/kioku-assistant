# Phase 5 — Presence (LATER, deferred by choice)

The hardware-y, most "Iron Man" layer. Deferred on purpose — it changes the *feeling* most but
adds the most moving parts. The persona (4.1) gives this its character when it lands.

## 5.1 Voice
Real ambient voice, not just transcribing a Telegram voice note:
- **Ears:** wake word + STT (local Whisper on the local machine / a mini-PC, or a hosted STT). Telegram
  voice-note transcription is the cheap interim step (an ingest slot already anticipated).
- **Mouth:** TTS with a single consistent voice, so Kioku *sounds* like Kioku.
- **Loop:** push-to-talk on desktop first (80% of the feeling, little latency risk), then always-on
  wake-word. Hardest parts are latency and false wakes, not the models.

## 5.2 Ambient (the apartment as its body)
Tie Kioku to **Home Assistant** (MCP) so it lives in the space, not a chat window:
- Scenes as commands: **focus** when deep work starts, **wind-down** at night, **date-night**.
- Context-aware: knows you're heads-down → holds notifications; morning brief on the **kitchen
  display** instead of your phone; end-of-day debrief when you sit down.
- The izakaya apartment becomes an output surface — Kioku present in the room.

## Why later
Voice + ambient need extra hardware (always-on mic, HA setup), tuning (latency, wake words), and
they don't unlock new *capability* — they change *presence*. Everything in Phase 4 (agency,
character, coding on your machine, autonomy) is higher-leverage first. Governor rules are unchanged:
scenes and voice actions that spend money or are irreversible still hit approval gates.
