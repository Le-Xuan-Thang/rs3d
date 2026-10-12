"""Every user-facing text comes from rs3d/help/<lang>.toml and rs3d/guide/<lang>.md (English only in v1)."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=4)
def _load(lang: str) -> dict:
    return tomllib.loads(resources.files("rs3d").joinpath("help", f"{lang}.toml").read_text(encoding="utf-8"))


def label(key: str, lang: str = "en") -> str:
    """Short UI label, e.g. label('nav.status') -> 'Status'. Unknown keys show the key itself."""
    node = _load(lang).get("labels", {})
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return key
        node = node[part]
    return node if isinstance(node, str) else key


def help_text(help_id: str, lang: str = "en") -> tuple[str, str]:
    """(tooltip, detail markdown) for a (?) icon. 'ssh.auth' falls back to 'ssh' when missing."""
    entries = _load(lang).get("help", {})
    candidates = [help_id]
    while "." in candidates[-1]:
        candidates.append(candidates[-1].rsplit(".", 1)[0])
    for cid in candidates:
        node = entries
        for part in cid.split("."):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and "short" in node:
            return node["short"], node.get("detail", node["short"])
    return "", ""


def guide_markdown(lang: str = "en") -> str:
    return resources.files("rs3d").joinpath("guide", f"{lang}.md").read_text(encoding="utf-8")
