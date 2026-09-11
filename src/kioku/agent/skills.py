"""Self-authored skill library — the engine of 'gets better'.

Skills are DATA: markdown cards in `system/skills/`, each a reusable workflow the router can
apply. Kioku proposes new ones from repeated work (see propose_skill_task); you activate one
by moving its proposal from `inbox/skills/` into `system/skills/`. Capabilities grow without code.

Card format (frontmatter + body):
    ---
    name: weekly-acme-pulse
    when: acme pulse, how's acme, project health   # comma-separated triggers
    model: work
    ---
    <the instructions the agent should follow for this workflow>
"""
import pathlib
import re

import frontmatter

from ..memory import vault as V

SKILL_DIR = "system/skills"


def load() -> list[dict]:
    base = pathlib.Path(V.VAULT) / SKILL_DIR
    out: list[dict] = []
    if not base.exists():
        return out
    for f in sorted(base.glob("*.md")):
        try:
            post = frontmatter.load(f)
            out.append({
                "name": post.get("name", f.stem),
                "when": post.get("when", ""),
                "model": post.get("model", "work"),
                "intent": post.get("intent"),   # optional: the tool set this skill needs (e.g. draft)
                "body": post.content,
                "path": str(f.relative_to(pathlib.Path(V.VAULT))),
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def find_matching(text: str) -> dict | None:
    """Match a skill by its `when` triggers. A trigger is a substring by default; a trigger written
    `all:word1 word2` matches when ALL those words appear anywhere (order-free) — handy for phrasings
    like "manage the <anything> project"."""
    t = text.lower()
    for sk in load():
        for k in (x.strip().lower() for x in re.split(r"[,;]", sk.get("when", "")) if x.strip()):
            if k.startswith("all:"):
                words = [w for w in re.split(r"[ +]+", k[4:]) if w]
                if words and all(w in t for w in words):
                    return sk
            elif k in t:
                return sk
    return None


def render(skill: dict, text: str) -> str:
    return (f"Apply the '{skill['name']}' skill.\n\n"
            f"Skill instructions:\n{skill['body']}\n\nUser request: {text}")
