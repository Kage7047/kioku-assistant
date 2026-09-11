"""Render Kioku's markdown-ish answers as Telegram-safe HTML.

Telegram HTML supports a small tag set (b, i, u, s, code, pre, a, blockquote) — no headers,
lists, or tables. We map: code fences → <pre>, `inline` → <code>, **bold** → <b>, markdown
links → <a>, ATX headers → bold lines, and bullets → •. Everything else is HTML-escaped so a
stray < or & never breaks a message. Call per already-chunked piece so tags never span a split.
"""
import html
import re

_CODE_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*$", re.M)
_BULLET = re.compile(r"^(\s*)[-*]\s+", re.M)
_MARK = "\x00"


def to_html(text: str) -> str:
    if not text:
        return ""
    stash: list[str] = []

    def _keep(tag: str, content: str) -> str:
        stash.append(f"<{tag}>{html.escape(content)}</{tag}>")
        return f"{_MARK}{len(stash) - 1}{_MARK}"

    # 1) pull code out first so nothing inside it gets reformatted
    text = _CODE_FENCE.sub(lambda m: _keep("pre", m.group(1).rstrip("\n")), text)
    text = _INLINE_CODE.sub(lambda m: _keep("code", m.group(1)), text)
    # 2) escape the rest
    text = html.escape(text)
    # 3) inline structure (operates on escaped text; brackets/parens survive escaping)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _HEADER.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BULLET.sub(lambda m: f"{m.group(1)}• ", text)
    # 4) restore code
    text = re.sub(rf"{_MARK}(\d+){_MARK}", lambda m: stash[int(m.group(1))], text)
    return text
