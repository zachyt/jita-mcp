"""calculate_fit — validate a complete fit and return all stats."""

from __future__ import annotations


def calculate_fit(
    ship: str,
    modules: list[str],
    skills: dict[str, int] | None = None,
) -> dict:
    """Runs a complete ship fit through the eos calculation engine and returns all stats
    plus validity. This is your ground truth — call it every time you propose or modify
    a fit. Do not estimate fit validity or stats from module values alone. If valid is
    false, read the errors array — each error includes the type, magnitude, and a specific
    suggestion for how to fix it. Iterate until valid is true and all user constraints
    are met, then call export_eft.
    """
    raise NotImplementedError
