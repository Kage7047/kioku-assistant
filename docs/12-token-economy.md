# Token economy — what's in place, and prompt caching

The whole point of the long-term vault is to spend fewer tokens without losing quality. This is
the ledger of every lever, its status, and the honest order of impact.

## Prompt caching — the straight answer

**It's automatic.** Kioku runs on the Claude Agent SDK (Claude Code under the hood), which applies
prompt caching to the **system prompt + tool definitions** on every request (Anthropic's standard
5-minute cache). We don't hand-place `cache_control` breakpoints — the SDK does.

What we do to make it actually hit:
- **A stable system-prompt prefix.** `BOOT` (the static persona/rules) is a constant string and comes
  first; the live vault files (`boot.md`/`persona.md`/`playbook.md`/`profile.md`) are appended after.
  Caching is prefix-based, so the stable head caches even when the live tail changes.
- **Dynamic content lives in the user turn, not the system prompt** — the conversation preamble and
  the pre-injected vault context are per-message and go in the prompt, so they never bust the cache.

Honest caveats:
- The **5-minute** window means intermittent use (messages > 5 min apart) re-pays the system-prompt
  input each time. That cost is small: the system prompt is ~3–4k tokens; at Haiku ($1/Mtok in) that's
  ~$0.004/request, at Sonnet ~$0.01. **It is not where the money goes.**
- **Intent tool-narrowing changes the tools block** between intents (recall vs draft mount different
  tools), so the *tool* portion of the cache is per-intent. Net still positive — narrowing saves more
  input than the occasional cache re-write costs.
- **Now measured (2026-08-20).** The orchestrator captures `cache_read_input_tokens` /
  `cache_creation_input_tokens` per run and records a `cache.usage` signal; the weekly self-review
  (`introspect`) reports the **hit ratio**. If it reads ~0% across runs, a silent invalidator is at
  work (per the caching reference) — investigate the system-prompt prefix. The binding system files
  (persona/playbook/profile) are also verified present each hour (`system.files` signal; a Telegram
  warning fires if one fails to load, so Kioku's character can't silently degrade).

**Where the money actually goes:** agentic *turns* (each turn re-sends the growing tool-result context)
and *output* tokens — not the cached system prompt. So the highest-impact levers are the ones that cut
turns and output, below.

## Levers in place (by impact)

| Lever | What it does | Status |
|---|---|---|
| **Retrieval-augmented prompting** | Pre-inject the top-k relevant vault notes so it answers in **one turn** instead of multiple `vault_search`/`vault_read` round-trips. The vault *is* the cache. | ✅ live |
| **Per-difficulty turn caps** | triage 6 / work 10 / opus 12; threaded into the pre-flight ceiling so cheap work also clears the budget more easily. | ✅ live |
| **Model routing by difficulty** | Haiku default; escalate to Sonnet only when the question has real depth; Opus rare, Fable never auto. | ✅ live |
| **Adaptive verbosity** | Simple asks get a 1–3 sentence answer (fewer **output** tokens); research earns length. Simple asks also carry 3 turns of history, not 6. | ✅ live |
| **Budget pre-flight guard** | Estimates a run's worst-case cost *before* spending; downgrades to Haiku or refuses; degrades normal→conserve→haiku_only→halt. | ✅ live |
| **Deterministic-Python first** | Vault audit, index/MAP rebuild, BM25, dedup, deadline scan — **zero model tokens**. The model only adds judgement. | ✅ live |
| **BM25 index cached** | Was rebuilt from every file on every query; now cached. | ✅ live |
| **Digest batching + loop-safety** | Notes digested a few per run (never a whole 5-hr window in one burst); stops if a batch makes no progress. | ✅ live |
| **On/off switch** | `/pause` halts all spend instantly when you need it quiet. | ✅ live |

## Available, not done (diminishing returns)

- **Verify cache hit-rate in Langfuse** — the one worth doing; confirms the above and finds any busting.
- **Extended (1-hour) cache TTL** — helps only if requests cluster within the hour; marginal here since
  the system prompt is small. Skip unless usage patterns say otherwise.
- **Batch API** (50% off) — contradicts subscription Mode-A (needs a metered key); parked by design.
- **Local Ollama triage tier** — decided SKIP (docs/11): optimizes pennies, needs always-on hardware.
- **Trim the system prompt** — playbook/persona/profile could be tightened, but it's cached and cheap;
  low priority.

## Rule of thumb
Cut **turns** and **output** before chasing cache. The vault-as-cache + turn caps + routing already do
the heavy lifting; prompt caching is a small automatic bonus on top, not the strategy.
