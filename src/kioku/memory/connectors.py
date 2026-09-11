"""Declarative connector registry. Reads connectors.yaml so adding/removing a source
(or retiring a dead one) is a config edit, not a code change."""
import pathlib

import yaml

from ..config import settings


def load() -> list[dict]:
    p = pathlib.Path(settings.connectors_path)
    if not p.exists():
        return []
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("connectors", [])


def enabled() -> list[dict]:
    return [c for c in load() if c.get("enabled")]
