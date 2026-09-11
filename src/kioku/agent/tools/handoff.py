"""Heavy-coding hand-off tools (Phase 3.5) — dispatch big/local coding to Claude Code on the user's PC.

See memory/handoff.py for the queue + flow. These tools only STAGE and REPORT; the actual build runs
on the user's machine via the local runner, off the $20 Agent-SDK budget.
"""
from claude_agent_sdk import tool, create_sdk_mcp_server

from ...memory import handoff as H


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


@tool("handoff_code",
      "Hand a HEAVY coding task to a Claude Code session on the user's own machine (a SEPARATE Pro "
      "pool at full quality, with access to the owner's LOCAL files) instead of doing it here. Reach for this "
      "when: a big multi-file build or refactor; work on a LOCAL repo the cloud worker can't see; "
      "anything that would burn the Agent-SDK budget. Give a SELF-CONTAINED task (it runs without this "
      "chat's context), the target repo NAME (the runner maps it to a local path), and any context/"
      "constraints. It runs when his PC + the runner are on; the result returns to you and the vault.",
      {"task": str, "repo": str, "context": str})
async def handoff_code(args):
    rec = H.create(args["task"], args.get("repo", ""), args.get("context", ""))
    where = f" in `{rec['repo']}`" if rec["repo"] else ""
    return _text(
        f"Handed off to your local Claude Code{where} (id {rec['id']}). It'll run the moment your PC "
        f"and the runner are on — separate Pro pool, so it doesn't touch the $20 budget. I'll file the "
        f"result to _reports/ and ping you when it's back. Check status anytime with handoff_status.")


@tool("handoff_status",
      "List heavy-coding hand-offs and their state (pending / running / done / error).", {})
async def handoff_status(_args):
    items = H.list_all(20)
    if not items:
        return _text("No hand-offs yet.")
    return _text("\n".join(
        f"[{h['status']}] {h['id']} — {h['task'][:80]}" + (f" ({h['repo']})" if h.get("repo") else "")
        for h in items))


# Registered dev tasks the local runner will execute (Phase 4.5B). Deterministic ones (run_tests /
# lint / index_repo) run a bounded command; model-y ones (review_diff / scaffold) run Claude Code.
# open_pr / run_local_shell are intentionally NOT here yet — they need the approval gate wired first.
_DEV_KINDS = ("run_tests", "lint", "index_repo", "review_diff", "scaffold")


@tool("dev_task",
      "Dispatch a REGISTERED dev task to the local runner on the user's machine (Phase 4.5B), on his "
      "real repo/toolchain, off the $20 budget. kind ∈ {run_tests, lint, index_repo, review_diff, "
      "scaffold}. `repo` is the repo name (runner maps it to a path); `args` is optional extra detail "
      "(e.g. what to scaffold, which diff to review). The runner runs ONLY these kinds and refuses "
      "anything else. Result returns to you + the vault. Use handoff_code for open-ended coding.",
      {"kind": str, "repo": str, "args": str})
async def dev_task(args):
    kind = (args.get("kind") or "").strip()
    if kind not in _DEV_KINDS:
        return _text(f"Unknown dev task '{kind}'. Allowed: {', '.join(_DEV_KINDS)}. "
                     "(open_pr / shell aren't enabled yet — they need the approval gate.)")
    rec = H.create(args.get("args", "") or kind, args.get("repo", ""), "", kind=kind)
    return _text(f"Queued dev task `{kind}`"
                 + (f" in `{rec['repo']}`" if rec["repo"] else "")
                 + f" (id {rec['id']}). Runs when your PC + runner are on; result comes back to me + the vault.")


@tool("browser_task",
      "Do a REAL browser action on the user's machine (Phase 4.7) — the last mile you can otherwise "
      "only draft: fill a form, book, submit, navigate a portal. Give a clear GOAL and the SITE "
      "(domain). This is OUTBOUND and gated hardest: it STAGES for his approval first, then runs on his "
      "PC via the local runner, on ALLOW-LISTED sites only, with a human confirm at the commit step "
      "(submit/pay/book). NEVER for money or legal steps without the owner. Prefer drafting; reach for this "
      "only when a real web action is genuinely required.",
      {"goal": str, "site": str})
async def browser_task(args):
    from ...config import settings
    goal, site = (args.get("goal") or "").strip(), (args.get("site") or "").strip()
    allowed = [s.strip() for s in (settings.browser_allowed_sites or "").split(",") if s.strip()]
    if not allowed:
        return _text("Computer-use is off — no BROWSER_ALLOWED_SITES configured. I'll prepare a draft "
                     "instead; you can do the final web step, or enable an allow-listed site.")
    if site and not any(site in a or a in site for a in allowed):
        return _text(f"'{site}' isn't on the browser allow-list ({', '.join(allowed)}). I won't drive a "
                     "browser off-list — tell me to add it, or I'll draft the step for you.")
    # This tool is treated as OUTBOUND by the gate, so reaching here means it was already approved:
    # queue it to the local runner (which enforces its own enable flag + allow-list + commit confirm).
    rec = H.create(goal, "", site, kind="browser")
    return _text(f"Approved browser task queued (id {rec['id']}) for {site or 'the site'}. It runs on your "
                 "PC via the runner, and stops for your confirm at any commit step.")


handoff_server = create_sdk_mcp_server(
    name="handoff", version="0.1.0",
    tools=[handoff_code, handoff_status, dev_task, browser_task])
