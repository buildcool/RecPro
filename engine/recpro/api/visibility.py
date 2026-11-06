from __future__ import annotations

from ..context import Context


def private_hidden(c: Context) -> bool:
    """True when private (sensitive) items must be left out of normal views."""
    priv = c.services.get("private")
    if priv is None:
        return True
    return not priv.visible_everywhere()  # type: ignore[attr-defined]


def visible_sql(c: Context, alias: str = "m") -> str:
    a = f"{alias}." if alias else ""
    cond = f"{a}state='active'"
    if private_hidden(c):
        cond += f" AND {a}sens_state NOT IN ('private','review')"
    return cond


def check_pending(c: Context) -> bool:
    """True when the sensitivity check exists but hasn't run on everything yet."""
    priv = c.services.get("private")
    return bool(priv and priv.check_available())  # type: ignore[attr-defined]
