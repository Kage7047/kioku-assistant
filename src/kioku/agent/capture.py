"""Universal capture — one inbox for everything. When the router says an input is 'capture'
(information to keep, not a question), this decides what KIND it is and files it into the
vault as a structured card. The vault is truth, so captures flow straight into memory and
get indexed for recall.
"""
import re
from datetime import datetime

from ..memory import vault as V

SUBTYPES = ("task", "person", "idea", "note")

_RX = [
    (re.compile(r"\b(todo|task|remind me to|need to|must)\b", re.I), "task"),
    (re.compile(r"\b(met|call with|contact|recruiter|his|her|they said)\b", re.I), "person"),
    (re.compile(r"\b(idea|what if|maybe we could|someday|concept)\b", re.I), "idea"),
]


def subtype(text: str) -> str:
    for rx, st in _RX:
        if rx.search(text):
            return st
    return "note"


def triage_capture(text: str) -> dict:
    st = subtype(text)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-") or "capture"
    card = (f"---\ntype: {st}\ncaptured: {datetime.now().isoformat(timespec='seconds')}\n"
            f"status: inbox\n---\n\n{text.strip()}\n")
    path = V.write(f"inbox/{ts}-{st}-{slug}.md", card)   # inbox is write-allowlisted
    return {"type": st, "path": path}
