"""get_modules_by_attribute — modules ranked by a specific EVE dogma attribute."""

from __future__ import annotations


def get_modules_by_attribute(
    attribute: str,
    ship: str,
    skills: dict[str, int] | None = None,
    filters: dict | None = None,
) -> dict:
    """Returns modules ranked by a specific EVE attribute, with values calculated in the
    context of a specific ship and character skills. Use this when the user targets a
    specific mechanic rather than a broad goal — e.g. 'most EM damage', 'fastest lock
    time', 'best cap recharge'. Supported attributes: em_damage, thermal_damage,
    kinetic_damage, explosive_damage, velocity, signature_radius, lock_time,
    cap_recharge, shield_recharge, tracking_speed.
    """
    raise NotImplementedError
