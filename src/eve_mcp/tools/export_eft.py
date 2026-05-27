"""export_eft — format a validated fit as an EFT string with required-skills list."""

from __future__ import annotations


def export_eft(
    ship: str,
    modules: list[str],
    fit_name: str | None = None,
) -> dict:
    """Call this once calculate_fit has returned valid: true. Returns a correctly formatted
    EFT string the user can paste directly into pyfa or EVE Online, plus a complete list
    of all skills and levels required to fly the fit. Do not call this until the fit is
    confirmed valid.
    """
    raise NotImplementedError
