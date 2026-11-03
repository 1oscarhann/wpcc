"""Username validation: shape rules plus a config-driven profanity filter."""

from __future__ import annotations

import re

from hearthforge.config.schemas import ProfanityCfg

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def normalize(name: str, leet: dict[str, str]) -> str:
    lowered = "".join(leet.get(ch, ch) for ch in name.lower())
    letters = "".join(ch for ch in lowered if ch.isalpha())
    return re.sub(r"(.)\1+", r"\1", letters)  # "fuuuck" → "fuck"


def is_profane(name: str, cfg: ProfanityCfg) -> bool:
    norm = normalize(name, cfg.leet)
    plain = "".join(ch for ch in name.lower() if ch.isalpha())
    for ok in cfg.allowed:
        norm = norm.replace(normalize(ok, cfg.leet), "")
        plain = plain.replace(ok, "")
    return any(normalize(bad, cfg.leet) in norm or bad in plain for bad in cfg.blocked)


def username_problem(name: str, cfg: ProfanityCfg, min_len: int, max_len: int) -> str | None:
    """Return a friendly reason the name is not allowed, or None."""
    if not (min_len <= len(name) <= max_len):
        return f"Usernames are {min_len}–{max_len} characters."
    if not USERNAME_RE.match(name):
        return "Use letters, numbers and underscores only."
    if name.startswith("_") or name.endswith("_") or "__" in name:
        return "Underscores can't be at the start, end or doubled."
    if name.lower() in cfg.reserved:
        return "That name is reserved."
    if is_profane(name, cfg):
        return "That name isn't allowed. Try something else."
    return None
