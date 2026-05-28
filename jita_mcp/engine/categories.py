"""Goal -> (slot -> module groups) mapping for get_modules_for_goal.

Group names are eos.db's invgroups.name (verified against the live DB).
Each (goal, slot) returns the list of module groups whose candidates we
score against the engine. Empty list = unsupported combination.

For damage-type goals (`maximize_*_damage`), the candidate set is the
same as `maximize_dps` for that slot — the goal drives ammo selection
and the ranking metric, not the category filter.
"""

from __future__ import annotations

# Real damage weapons. Excludes EWAR (Weapon Disruptor), specialty launchers
# (Bomb, Defender, Festival, Interdiction, Breacher Pod), probe launchers,
# super weapons (capital-only edge case), and weapon rigs.
_WEAPON_GROUPS: list[str] = [
    "Energy Weapon",
    "Hybrid Weapon",
    "Projectile Weapon",
    "Precursor Weapon",
    "Missile Launcher Rocket",
    "Missile Launcher Light",
    "Missile Launcher Heavy Assault",
    "Missile Launcher Heavy",
    "Missile Launcher Rapid Light",
    "Missile Launcher Rapid Heavy",
    "Missile Launcher Cruise",
    "Missile Launcher Torpedo",
    "Missile Launcher Rapid Torpedo",
    "Missile Launcher XL Cruise",
    "Missile Launcher XL Torpedo",
]

# Weapon-DPS-multiplier modules. Damage Control is intentionally NOT here —
# its DPS contribution (cap regen edge cases) is negligible; it belongs with
# tank. Drone Damage Amplifier intentionally omitted: v1 doesn't score drones.
_DAMAGE_MOD_GROUPS: list[str] = [
    "Ballistic Control System",  # missiles
    "Magnetic Field Stabilizer",  # hybrid
    "Gyrostabilizer",  # projectile
    "Heat Sink",  # laser
    "Entropic Radiation Sink",  # Triglavian
]

_LOW_TANK_GROUPS: list[str] = [
    "Armor Plate",
    "Armor Hardener",
    "Flex Armor Hardener",
    "Energized Armor Membrane",
    "Reinforced Bulkhead",
    "Damage Control",
]

_MED_TANK_GROUPS: list[str] = [
    "Shield Extender",
    "Shield Hardener",
    "Flex Shield Hardener",
]

_MED_SPEED_GROUPS: list[str] = ["Propulsion Module"]  # MWD + AB live in the same group
_LOW_SPEED_GROUPS: list[str] = [
    "Nanofiber Internal Structure",
    "Overdrive Injector System",
]


GOAL_GROUPS: dict[tuple[str, str], list[str]] = {
    # DPS — weapons (high) or damage mods (low)
    ("maximize_dps", "high"): _WEAPON_GROUPS,
    ("maximize_dps", "low"): _DAMAGE_MOD_GROUPS,
    # Damage-typed variants reuse the same candidate set; ammo selection
    # narrows by damage type and ranking takes the per-type DPS.
    ("maximize_em_damage", "high"): _WEAPON_GROUPS,
    ("maximize_thermal_damage", "high"): _WEAPON_GROUPS,
    ("maximize_kinetic_damage", "high"): _WEAPON_GROUPS,
    ("maximize_explosive_damage", "high"): _WEAPON_GROUPS,
    ("maximize_em_damage", "low"): _DAMAGE_MOD_GROUPS,
    ("maximize_thermal_damage", "low"): _DAMAGE_MOD_GROUPS,
    ("maximize_kinetic_damage", "low"): _DAMAGE_MOD_GROUPS,
    ("maximize_explosive_damage", "low"): _DAMAGE_MOD_GROUPS,
    # Tank
    ("maximize_ehp", "med"): _MED_TANK_GROUPS,
    ("maximize_ehp", "low"): _LOW_TANK_GROUPS,
    # Speed
    ("maximize_speed", "med"): _MED_SPEED_GROUPS,
    ("maximize_speed", "low"): _LOW_SPEED_GROUPS,
}


# Goals -> canonical damage-type key. For typed DPS goals we use the matching
# DamageStats field for ranking; for plain maximize_dps we use `.total`.
DAMAGE_TYPE_BY_GOAL: dict[str, str | None] = {
    "maximize_dps": None,
    "maximize_em_damage": "em",
    "maximize_thermal_damage": "thermal",
    "maximize_kinetic_damage": "kinetic",
    "maximize_explosive_damage": "explosive",
}


def groups_for(goal: str, slot: str) -> list[str]:
    """Return the module groups for (goal, slot) or [] if unsupported."""
    return GOAL_GROUPS.get((goal, slot), [])
