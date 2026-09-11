"""Terminal interface: talk to Kioku from the shell.

    kioku ask "summarize my Acme notes"
    kioku audit
    kioku budget
    echo "long text" | kioku ask -      # read the prompt from stdin

Thin httpx client over the same API the Telegram bot and dashboard use.
"""
import json
import sys

import httpx

from .config import settings

API = settings.resolved_api_base


def _stream(kind: str, text: str, difficulty: str = "triage"):
    with httpx.Client(timeout=None) as c:
        run_id = c.post(f"{API}/tasks",
                        json={"kind": kind, "input": text, "difficulty": difficulty}).json()["run_id"]
        with c.stream("GET", f"{API}/tasks/{run_id}/stream") as s:
            for line in s.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "text":
                    print(ev["text"], end="", flush=True)
                elif ev.get("type") == "done":
                    print()
                    return
                elif ev.get("type") in ("preflight", "budget") and ev.get("mode") not in (None, "normal"):
                    print(f"[budget: {ev['mode']}]", file=sys.stderr)


def main():
    args = sys.argv[1:]
    if not args:
        print("usage: kioku <ask|audit|budget> [text]"); return
    cmd, rest = args[0], args[1:]
    if cmd == "budget":
        print(json.dumps(httpx.get(f"{API}/budget").json(), indent=2)); return
    if cmd == "audit":
        _stream("vault_audit", "audit the vault"); return
    if cmd == "import":
        sub = rest[0] if rest else "_import"
        print(httpx.post(f"{API}/bulk-ingest", params={"subdir": sub}).json()); return
    if cmd == "ask":
        text = sys.stdin.read() if rest[-1:] == ["-"] else " ".join(rest)
        _stream("ask", text)                      # force a direct answer
    else:
        _stream("input", " ".join(args))          # let the router decide


if __name__ == "__main__":
    main()
