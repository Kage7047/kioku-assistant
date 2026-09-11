"""Fire-and-forget Telegram push for out-of-band alerts (budget thresholds, approvals, reports).

Uses the Bot API directly so background workers can ping you without an active chat. Messages are
rendered as Telegram HTML (bold/links/code) with a plain-text fallback so a parse error never eats a
message. `notify_file` sends a vault report/draft as a document — handy on mobile. No-op if the bot
token / user id are unset.
"""
import pathlib

import httpx

from ..config import settings
from .format import to_html


def _base() -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}"


def _enabled() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_allowed_user_id)


def notify(text: str) -> bool:
    if not _enabled():
        return False
    chat = settings.telegram_allowed_user_id
    try:
        r = httpx.post(f"{_base()}/sendMessage",
                       json={"chat_id": chat, "text": to_html(text), "parse_mode": "HTML",
                             "disable_web_page_preview": True}, timeout=10)
        if r.status_code != 200:            # HTML parse issue → resend plain so nothing is lost
            httpx.post(f"{_base()}/sendMessage", json={"chat_id": chat, "text": text}, timeout=10)
        return True
    except Exception:  # noqa: BLE001
        return False


def notify_file(path, caption: str = "") -> bool:
    """Send a vault file (report/draft) as a Telegram document. path may be vault-relative."""
    if not _enabled():
        return False
    try:
        from ..memory import vault as V
        p = pathlib.Path(path)
        if not p.is_absolute():
            p = pathlib.Path(V.VAULT) / path
        if not p.exists() or p.stat().st_size > 45_000_000:
            return False
        with open(p, "rb") as fh:
            httpx.post(f"{_base()}/sendDocument",
                       data={"chat_id": settings.telegram_allowed_user_id,
                             "caption": (caption or p.name)[:1000]},
                       files={"document": (p.name, fh)}, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        return False
