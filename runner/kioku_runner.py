#!/usr/bin/env python3
"""Kioku local hand-off runner (Phase 3.5).

Runs on YOUR machine. Polls Kioku's API for heavy-coding hand-offs, executes each with your LOCAL
Claude Code (`claude -p …`) inside the target repo — a separate interactive Pro pool, at full
quality, with local-file access — and posts the result back. Kioku then files it to the vault and
pings you on Telegram. Nothing runs unless this script is running, so it never needs your PC to be
always-on.

Setup (env vars):
  KIOKU_API_URL   Base URL of your Kioku api service, e.g. https://<your-api-service>.up.railway.app
  KIOKU_TOKEN     The DASHBOARD_TOKEN you set on the api service (used as the bearer token).
  KIOKU_REPOS     Semicolon-separated name=path map the runner uses to resolve a hand-off's `repo`,
                  e.g.  kioku=/path/to/kioku;acme=/path/to/acme
                  A hand-off with an empty/unknown repo runs in KIOKU_DEFAULT_DIR (default: cwd).
  KIOKU_DEFAULT_DIR   Fallback working dir when a hand-off names no (known) repo.
  KIOKU_CLAUDE_BIN    Path to the claude CLI (default: "claude").
  KIOKU_CLAUDE_ARGS   Extra args for claude, space-separated (default: "--permission-mode acceptEdits").
                      Use bypassPermissions only if you trust fully-autonomous edits on these repos.
  KIOKU_POLL_SECONDS  Idle poll interval (default 30). KIOKU_TASK_TIMEOUT seconds per task (default 3600).

Run:  python kioku_runner.py     (Ctrl+C to stop)
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("KIOKU_API_URL", "").rstrip("/")
TOKEN = os.environ.get("KIOKU_TOKEN", "")
DEFAULT_DIR = os.environ.get("KIOKU_DEFAULT_DIR", os.getcwd())
CLAUDE_BIN = os.environ.get("KIOKU_CLAUDE_BIN", "claude")
CLAUDE_ARGS = os.environ.get("KIOKU_CLAUDE_ARGS", "--permission-mode acceptEdits").split()
POLL = int(os.environ.get("KIOKU_POLL_SECONDS", "30"))
TASK_TIMEOUT = int(os.environ.get("KIOKU_TASK_TIMEOUT", "3600"))
# Phase 4.5B — the ONLY task kinds this runner will execute. Anything else is refused. open_pr /
# run_local_shell are deliberately absent until the approval gate is wired.
DEV_ALLOW = {"code", "run_tests", "lint", "index_repo", "review_diff", "scaffold"}
TEST_CMD = os.environ.get("KIOKU_TEST_CMD", "pytest -q").split()
LINT_CMD = os.environ.get("KIOKU_LINT_CMD", "ruff check .").split()


def _repos() -> dict:
    out = {}
    for pair in os.environ.get("KIOKU_REPOS", "").split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, path = pair.split("=", 1)
            out[name.strip()] = os.path.expanduser(path.strip())
    return out


REPOS = _repos()


def _req(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw.strip() else {}


def _run_claude(task: str, context: str, cwd: str) -> tuple[str, str]:
    """Run one hand-off through the local Claude Code. Returns (status, result_text)."""
    prompt = task if not context else f"{task}\n\n---\nContext / constraints:\n{context}"
    cmd = [CLAUDE_BIN, "-p", prompt, *CLAUDE_ARGS]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TASK_TIMEOUT)
    except FileNotFoundError:
        return "error", f"claude CLI not found (KIOKU_CLAUDE_BIN={CLAUDE_BIN})."
    except subprocess.TimeoutExpired:
        return "error", f"timed out after {TASK_TIMEOUT}s."
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    # Best-effort: append a short summary of what changed in the repo.
    diff = ""
    try:
        d = subprocess.run(["git", "-C", cwd, "diff", "--stat"], capture_output=True, text=True, timeout=30)
        diff = (d.stdout or "").strip()
    except Exception:  # noqa: BLE001
        pass
    body = out or "(no stdout)"
    if diff:
        body += f"\n\n---\nGit changes in {cwd}:\n{diff}"
    if err:
        body += f"\n\n---\nstderr:\n{err[:2000]}"
    return ("done" if p.returncode == 0 else "error"), body


def _sh(cmd: list, cwd: str) -> tuple[str, str]:
    """Run a bounded command in the repo and capture output. Deterministic dev tasks use this."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TASK_TIMEOUT)
    except FileNotFoundError:
        return "error", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return "error", f"timed out after {TASK_TIMEOUT}s"
    out = (p.stdout or "").strip()
    if p.stderr and p.stderr.strip():
        out += ("\n\n[stderr]\n" + p.stderr.strip())
    return ("done" if p.returncode == 0 else "error"), (out[:8000] or "(no output)")


# Mirrors kioku.agent.tools.handoff.site_allowed — the runner is a standalone script.
def site_allowed(site: str, allowed: list[str]) -> bool:
    """Exact host or a subdomain of an allow-listed host. Accepts a bare host or a URL.
    Substring checks are unsafe: 'linkedin.com.evil.io' contains 'linkedin.com', and an empty
    site must never match anything."""
    from urllib.parse import urlsplit

    def host(s: str) -> str:
        s = (s or "").strip().lower()
        h = urlsplit(s if "//" in s else f"//{s}").hostname or ""
        return h.rstrip(".")

    h = host(site)
    if not h:
        return False
    for a in allowed:
        ah = host(a)
        if ah and (h == ah or h.endswith("." + ah)):
            return True
    return False


def _dispatch(rec: dict, cwd: str) -> tuple[str, str]:
    """Route a hand-off to its handler by kind. Runs ONLY registered kinds; refuses anything else."""
    kind = rec.get("kind", "code")
    task, ctx = rec.get("task", ""), rec.get("context", "")
    # Phase 4.7 computer-use — OFF unless explicitly enabled, allow-listed sites only, and the prompt
    # forces a confirm at any commit step. Supervise it: it drives YOUR real browser/sessions.
    if kind == "browser":
        if os.environ.get("KIOKU_BROWSER_ENABLED") != "1":
            return "error", "browser tasks are disabled on this runner (set KIOKU_BROWSER_ENABLED=1)."
        site = ctx.strip()
        allowed = [s.strip() for s in os.environ.get("KIOKU_BROWSER_ALLOWED_SITES", "").split(",") if s.strip()]
        if not allowed:
            return "error", "no KIOKU_BROWSER_ALLOWED_SITES set — refusing every browser task."
        if not site_allowed(site, allowed):
            return "error", f"site '{site}' is not in KIOKU_BROWSER_ALLOWED_SITES — refused."
        prompt = (f"On the site {site}, do this in the browser: {task}\n"
                  "Preview each step first. STOP and ask for explicit confirmation before ANY "
                  "irreversible commit (submit, pay, book, send). Never complete a money or legal step "
                  "without an explicit OK.")
        return _run_claude(prompt, "", DEFAULT_DIR)
    if kind not in DEV_ALLOW:
        return "error", f"runner refuses unregistered task kind '{kind}'."
    if kind == "run_tests":
        return _sh(TEST_CMD, cwd)
    if kind == "lint":
        return _sh(LINT_CMD, cwd)
    if kind == "index_repo":
        _, files = _sh(["git", "-C", cwd, "ls-files"], cwd)
        return "done", f"Repo: {cwd}\n\nTracked files:\n{files[:6000]}"
    if kind == "review_diff":
        _, diff = _sh(["git", "-C", cwd, "diff", "HEAD"], cwd)
        if not diff or diff == "(no output)":
            return "done", "No uncommitted diff to review."
        prompt = ("Review this git diff for correctness, security, and simplicity. Be concise; list "
                  "concrete issues only." + (f"\nFocus: {task}" if task else "") + "\n\n" + diff[:12000])
        return _run_claude(prompt, "", cwd)
    if kind == "scaffold":
        return _run_claude(f"Scaffold in this repo, following its existing house style: {task}", ctx, cwd)
    return _run_claude(task, ctx, cwd)          # 'code' — free-form


def _resolve_dir(repo: str) -> str:
    if repo and repo in REPOS:
        return REPOS[repo]
    return DEFAULT_DIR


def main() -> int:
    if not API or not TOKEN:
        print("Set KIOKU_API_URL and KIOKU_TOKEN first. See the header of this file.", file=sys.stderr)
        return 2
    print(f"Kioku runner up. Polling {API}/handoffs/claim every {POLL}s. Repos: {list(REPOS) or '(none)'}")
    while True:
        try:
            rec = _req("POST", "/handoffs/claim?runner=local")
        except urllib.error.URLError as e:
            print(f"[poll] api unreachable: {e}; retrying in {POLL}s")
            time.sleep(POLL)
            continue
        except Exception as e:  # noqa: BLE001
            print(f"[poll] error: {e}; retrying in {POLL}s")
            time.sleep(POLL)
            continue
        if not rec or not rec.get("id"):
            time.sleep(POLL)
            continue
        hid, repo = rec["id"], rec.get("repo", "")
        cwd = _resolve_dir(repo)
        print(f"[run] {hid} [{rec.get('kind','code')}] in {cwd} — {rec.get('task','')[:80]}")
        status, result = _dispatch(rec, cwd)
        try:
            _req("POST", f"/handoffs/{hid}/result", {"status": status, "result": result})
            print(f"[done] {hid} -> {status}")
        except Exception as e:  # noqa: BLE001
            print(f"[done] {hid} finished ({status}) but posting the result failed: {e}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped.")
