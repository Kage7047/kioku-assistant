"""Telegram front door. Locked to one user. Streams milestones, not every token."""
import json

import httpx
from telegram import Update
import base64

from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from ..config import settings
from ..worker.tasks import ingest_task

API = settings.resolved_api_base
TG_LIMIT = 4000   # Telegram hard limit is 4096; leave headroom


def _headers() -> dict:
    """Auth header for internal API calls once DASHBOARD_TOKEN is set (bot shares the secret)."""
    return {"Authorization": f"Bearer {settings.dashboard_token}"} if settings.dashboard_token else {}


def _authorized(update: Update) -> bool:
    allowed = settings.telegram_allowed_user_id
    return not allowed or str(update.effective_user.id) == str(allowed)


def _chunk(text: str, size: int = TG_LIMIT) -> list[str]:
    """Split a long answer into Telegram-sized pieces, preferring paragraph/line breaks."""
    text = text.strip()
    if not text:
        return []
    out, buf = [], ""
    for para in text.split("\n\n"):
        piece = (buf + "\n\n" + para) if buf else para
        if len(piece) <= size:
            buf = piece
            continue
        if buf:
            out.append(buf)
            buf = ""
        while len(para) > size:                      # a single huge paragraph
            cut = para.rfind("\n", 0, size)
            if cut <= 0:
                cut = size
            out.append(para[:cut])
            para = para[cut:].lstrip("\n")
        buf = para
    if buf:
        out.append(buf)
    return out


async def _reply_long(update: Update, text: str):
    """Send a full answer as clean, readable chunks — rendered as Telegram HTML (bold/links/code),
    with a plain-text fallback per chunk so a parse error never eats the reply."""
    from .format import to_html
    chunks = _chunk(text) or ["(no output)"]
    for part in chunks:
        try:
            await update.message.reply_text(to_html(part), parse_mode="HTML",
                                            disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            await update.message.reply_text(part)


async def _submit_and_stream(update: Update, kind: str, text: str, difficulty="triage"):
    """Fire a run, show one 'working…' line, then render the complete answer once it lands.

    Intermediate `text` events are progress previews (for the future web view); Telegram waits
    for the terminal `done` event, which now carries the whole answer, and prints it chunked.
    """
    async with httpx.AsyncClient(timeout=None, headers=_headers()) as c:
        r = await c.post(f"{API}/tasks", json={"kind": kind, "input": text, "source": "telegram",
                                               "difficulty": difficulty, "essential": True})
        run_id = r.json()["run_id"]
        await update.message.chat.send_action("typing")
        final = ""
        async with c.stream("GET", f"{API}/tasks/{run_id}/stream") as s:
            async for line in s.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                t = ev.get("type")
                if t == "preflight" and ev.get("mode") not in (None, "normal"):
                    await update.message.reply_text(
                        f"⚙️ budget mode {ev['mode']} · {int(ev.get('fraction', 0)*100)}% used")
                elif t == "text":
                    final = ev["text"]                # last preview = most complete so far
                elif t == "done":
                    if ev.get("text"):                # full answer carried on the done event
                        final = ev["text"]
                    break
        await _reply_long(update, final)


def _help_text() -> str:
    from ..memory import switch
    state = "paused ⏸ (/resume to wake)" if switch.is_paused() else "awake"
    return (
        f"Kioku 記憶 — {state}. Just talk to me — I work out what you want.\n\n"
        "• Ask / recall — “what’s my week look like?”, “who is Alex?”\n"
        "• Capture — “remember I met Sam from Acme”\n"
        "• Draft — “draft a reply to the recruiter” (I prepare a Gmail draft; you send)\n"
        "• Apply — “apply to the top opportunity” (tailored to your best-fit CV)\n"
        "• Prep — “prep me for my call with …”\n"
        "• Schedule — “send me a GitHub summary every Friday at 9am”\n"
        "• Calendar — “put a focus block tomorrow 3pm” (I just do it)\n"
        "• Jobs — “opportunities” · Ideas — “ideas” · Learn about you — “learn”\n"
        "• Organize the vault — “organize” · or send me any file/photo to learn from\n\n"
        "Commands: /budget /audit /skills /approvals /approve <id> /reject <id> "
        "/introspect /pause /resume")


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(_help_text())


async def cmd_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _submit_and_stream(update, "ask", " ".join(ctx.args))


async def cmd_audit(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _submit_and_stream(update, "vault_audit", "audit the vault")


async def cmd_budget(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    async with httpx.AsyncClient(headers=_headers()) as c:
        b = (await c.get(f"{API}/budget")).json()
    await update.message.reply_text(
        f"Agent SDK credit: ${b['spend']}/${b['credit']} used "
        f"({int(b['fraction']*100)}%) · ${b['remaining']} left · mode {b['mode']}")


async def cmd_approvals(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """List outbound actions waiting on approval."""
    if not _authorized(update):
        return
    async with httpx.AsyncClient(headers=_headers()) as c:
        items = (await c.get(f"{API}/approvals")).json()
    if not items:
        await update.message.reply_text("Nothing waiting for approval.")
        return
    lines = ["🔐 Waiting for your approval:"]
    for a in items:
        lines.append(f"· `{a['id']}` — {a.get('desc', a.get('tool', ''))[:120]}")
    lines.append("\nApprove with /approve <id>, or reject with /reject <id>.")
    await update.message.reply_text("\n".join(lines))


async def cmd_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not ctx.args:
        await update.message.reply_text("usage: /approve <id>  (see /approvals)")
        return
    aid = ctx.args[0]
    async with httpx.AsyncClient(headers=_headers()) as c:
        r = await c.post(f"{API}/approvals/{aid}/approve")
        if r.status_code == 200:
            await update.message.reply_text("⏳ executing the approved action… (you'll get a ✅)")
            return
        # Backward-compat: fall back to the old vault-write plan queue if this id is one of those.
        r2 = await c.post(f"{API}/writes/{aid}/apply")
    if r2.status_code == 200:
        await update.message.reply_text("⏳ applying… (you'll get a ✅ when it lands)")
    else:
        await update.message.reply_text(f"✗ nothing to approve with id {aid} (expired?)")


async def cmd_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not ctx.args:
        await update.message.reply_text("usage: /reject <id>  (see /approvals)")
        return
    async with httpx.AsyncClient(headers=_headers()) as c:
        r = await c.post(f"{API}/approvals/{ctx.args[0]}/reject")
    await update.message.reply_text("🗑 rejected." if r.status_code == 200
                                    else f"✗ nothing to reject with id {ctx.args[0]}")


async def cmd_help(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(_help_text())


async def cmd_pause(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    from ..memory import switch
    switch.set_paused(True)
    await update.message.reply_text("⏸ Paused. I'll stop running and spending — nothing "
                                    "proactive will fire either. Send /resume when you want me back.")


async def cmd_resume(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    from ..memory import switch
    switch.set_paused(False)
    await update.message.reply_text("▶️ Awake again. Back on watch.")


async def cmd_skills(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    async with httpx.AsyncClient(headers=_headers()) as c:
        sk = (await c.get(f"{API}/skills")).json()
    if not sk:
        await update.message.reply_text("No skills yet. Try: propose a skill")
    else:
        await update.message.reply_text("Skills:\n" + "\n".join(f"· {x['name']}" for x in sk))


async def _ingest(update, file_obj, filename):
    ba = await (await file_obj.get_file()).download_as_bytearray()
    from ..memory import db
    run_id = await db.create_run("ingest", filename, "triage")
    ingest_task.delay(run_id, base64.b64encode(bytes(ba)).decode(), filename, "telegram")
    await update.message.reply_text(f"📎 learning from {filename}…")


async def on_document(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    doc = update.message.document
    await _ingest(update, doc, doc.file_name or "document")


async def on_photo(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    photo = update.message.photo[-1]                     # largest size
    cap = (update.message.caption or "photo").replace(" ", "-")[:30]
    await _ingest(update, photo, f"{cap}.jpg")


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _submit_and_stream(update, "input", update.message.text)   # let the router decide


def build_application():
    """Build the PTB Application with handlers. Embedded into the API process (lifespan)."""
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("approvals", cmd_approvals))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def main():   # standalone fallback (not used when embedded in the API)
    build_application().run_polling()


if __name__ == "__main__":
    main()
