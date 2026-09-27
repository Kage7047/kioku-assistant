"""Ingest files & photos into the brain on the fly. Any interface (Telegram, dashboard
upload, email later) can hand bytes here; it captures an immutable copy, extracts text,
files a note into the vault, and indexes it — so a whiteboard photo or a PDF becomes memory.

Extraction is graceful: unsupported/unavailable extractors store the source + a stub note
rather than failing. Text/markdown work everywhere; pdf/docx need their libs; images need a
vision step (wired against your pinned SDK — falls back to 'stored, transcription pending').
"""
import hashlib
from datetime import datetime
from pathlib import Path

from . import capture  # noqa: F401  # reuse subtype for the note card
from ..memory import vault as V

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic"}
TEXT_EXT = {".md", ".txt", ".markdown", ".csv", ".log"}


def _ext(name: str) -> str:
    return Path(name).suffix.lower()


def extract_text(data: bytes, filename: str) -> tuple[str, str]:
    """Return (kind, text). kind ∈ {text, pdf, docx, image, binary}."""
    ext = _ext(filename)
    if ext in TEXT_EXT:
        return "text", data.decode("utf-8", "ignore")
    if ext == ".pdf":
        try:
            import io
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            return "pdf", "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception:  # noqa: BLE001
            return "pdf", ""
    if ext == ".docx":
        try:
            import io
            import docx
            d = docx.Document(io.BytesIO(data))
            return "docx", "\n".join(p.text for p in d.paragraphs)
        except Exception:  # noqa: BLE001
            return "docx", ""
    if ext in IMAGE_EXT:
        return "image", _vision_extract(data, filename)
    return "binary", ""


def _vision_extract(data: bytes, filename: str) -> str:
    """Transcribe/describe an image. Wire to your pinned SDK's image input; until then the
    image is stored and this returns a marker so nothing is lost."""
    try:
        # TODO: pass an image content block to the Agent SDK / vision model and return the text.
        raise NotImplementedError
    except Exception:  # noqa: BLE001
        return "[image stored; enable vision to transcribe]"


def ingest_bytes(data: bytes, filename: str, origin: str = "upload") -> dict:
    digest = hashlib.sha256(data).hexdigest()[:12]
    safe = "".join(c if c.isalnum() or c in ".-_" else "-" for c in filename)[:60] or "file"
    # immutable source copy (never rewritten) — the capture principle
    src_rel = f"sources/{digest}-{safe}"
    (Path(V.VAULT) / "sources").mkdir(parents=True, exist_ok=True)
    (Path(V.VAULT) / src_rel).write_bytes(data)

    kind, text = extract_text(data, filename)
    ts = datetime.now()
    body = text.strip() or "(no extractable text)"
    card = (f"---\ntype: source\nkind: {kind}\norigin: {origin}\nfile: {filename}\n"
            f"source: {src_rel}\ncaptured: {ts.isoformat(timespec='seconds')}\nstatus: inbox\n---\n\n"
            f"{body[:8000]}\n")
    stem = Path(safe).stem or "file"
    note_rel = V.write(f"inbox/{ts:%Y%m%d-%H%M%S}-{kind}-{stem}.md", card)
    return {"note": note_rel, "source": src_rel, "kind": kind, "chars": len(text)}
