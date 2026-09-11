"""The 'gets better' seed. After a substantial run, write a short dated journal note into
the vault: what was asked, what was decided/done. It indexes into memory, so future-Kioku
recalls its own past work and reasoning — the compounding loop, on your terms.

Kept cheap and deterministic (no extra model call): it just records the exchange. A later
step can summarize/extract claims + skills from these during the nightly sweep.
"""
from datetime import date, datetime

from ..memory import vault as V

JOURNAL_INTENTS = {"code", "research", "plan", "draft", "automate"}   # skip trivial recalls


def maybe_journal(intent: str, prompt: str, result: str) -> str | None:
    if intent not in JOURNAL_INTENTS or not result or len(result) < 200:
        return None
    ts = datetime.now().strftime("%H%M")
    entry = (f"\n## {ts} · {intent}\n**Asked:** {prompt[:300]}\n\n"
             f"**Outcome:** {result[:600]}\n")
    path = f"journal/{date.today().isoformat()}.md"
    try:
        existing = V.read(path)
    except Exception:
        existing = f"# Journal — {date.today().isoformat()}\n"
    V.write(path, existing + entry, approved=True)   # journal/ is a system dir
    return path
