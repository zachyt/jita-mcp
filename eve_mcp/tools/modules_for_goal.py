"""get_modules_for_goal — ranked module candidates for a fitting objective."""

from __future__ import annotations


def get_modules_for_goal(
    ship: str,
    goal: str,
    skills: dict[str, int] | None = None,
    constraints: dict | None = None,
) -> dict:
    """Returns ranked module candidates for a specific fitting objective on a specific
    ship. Effective stats are calculated using ship bonuses and character skills — not
    raw module stats — so rankings reflect real in-game performance. Ammo is automatically
    selected and factored in for weapon modules. Untrainable modules are filtered out.
    Goals: maximize_ehp, maximize_dps, maximize_em_damage, maximize_thermal_damage,
    maximize_kinetic_damage, maximize_explosive_damage, maximize_speed, maximize_range,
    budget_fit.
    """
    raise NotImplementedError
