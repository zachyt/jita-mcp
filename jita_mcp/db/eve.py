"""Ship/module/dogma data via pyfa's eos engine (vendor/pyfa/eve.db).

All EVE *game mechanics* data goes through this module: ships, modules, ammo,
dogma attributes, traits, skill requirements. Universe data (regions,
systems, stations, markets) lives in Fuzzwork's SDE and is served by db/sde.py
when we need it.

eos exposes attributes by name (`item.attributes["cpuOutput"].value`) rather
than by ID, so the code reads as EVE concepts rather than dgma-attribute
table lookups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jita_mcp.engine.eos_setup import setup

setup()
import eos.db  # noqa: E402

# ---------------------------------------------------------------------------
# Attribute names. Pyfa exposes dogma attributes by their codeName (string),
# not by ID, so these are plain string keys into item.attributes.
# ---------------------------------------------------------------------------

SHIP_CATEGORY_NAME = "Ship"

FITTING_ATTRS = {"cpuOutput": "cpu", "powerOutput": "powergrid", "upgradeCapacity": "calibration"}
SLOT_ATTRS = {"hiSlots": "high", "medSlots": "med", "lowSlots": "low", "rigSlots": "rig"}
HARDPOINT_ATTRS = {"turretSlotsLeft": "turret", "launcherSlotsLeft": "launcher"}
HP_ATTRS = {"shieldCapacity": "shield", "armorHP": "armor", "hp": "hull"}

# Resists stored as damage *multipliers* (1.0 = 0% resist). _resist_pct converts.
SHIELD_RESIST_ATTRS = {
    "shieldEmDamageResonance": "em",
    "shieldThermalDamageResonance": "thermal",
    "shieldKineticDamageResonance": "kinetic",
    "shieldExplosiveDamageResonance": "explosive",
}
ARMOR_RESIST_ATTRS = {
    "armorEmDamageResonance": "em",
    "armorThermalDamageResonance": "thermal",
    "armorKineticDamageResonance": "kinetic",
    "armorExplosiveDamageResonance": "explosive",
}
STRUCTURE_RESIST_ATTRS = {
    "emDamageResonance": "em",
    "thermalDamageResonance": "thermal",
    "kineticDamageResonance": "kinetic",
    "explosiveDamageResonance": "explosive",
}

# capacity sub-bays. cargo + drone fields always emitted; the rest only when > 0.
CAPACITY_ATTRS = {
    "capacity": "cargo",
    "droneCapacity": "drone_bay",
    "droneBandwidth": "drone_bandwidth",
    "shipMaintenanceBayCapacity": "ship_maintenance_bay",
    "fleetHangarCapacity": "fleet_hangar",
    "specialFuelBayCapacity": "fuel_bay",
    "specialOreHoldCapacity": "ore_hold",
    "specialMineralHoldCapacity": "mineral_hold",
    "specialGasHoldCapacity": "gas_hold",
    "specialIceHoldCapacity": "ice_hold",
    "specialAsteroidHoldCapacity": "asteroid_hold",
    "specialSalvageHoldCapacity": "salvage_hold",
    "specialAmmoHoldCapacity": "ammo_hold",
    "specialCommandCenterHoldCapacity": "command_center_hold",
    "specialPlanetaryCommoditiesHoldCapacity": "planetary_commodities_hold",
    "specialMaterialBayCapacity": "material_bay",
    "specialBoosterHoldCapacity": "booster_hold",
    "specialSubsystemHoldCapacity": "subsystem_hold",
    "specialMobileDepotHoldCapacity": "mobile_depot_hold",
    "frigateEscapeBayCapacity": "frigate_escape_bay",
}
ALWAYS_EMIT_CAPACITY = {"capacity", "droneCapacity", "droneBandwidth"}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    """Strip HTML tags and normalise whitespace for the LLM."""
    if not html:
        return ""
    # `<br />` and friends become newlines so the structure survives stripping.
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = _TAG_RE.sub("", text)
    # Collapse 3+ newlines down to 2, trim trailing space per line.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _resist_pct(mult: float | None) -> float:
    """Damage multiplier (1.0 = 0% resist) -> 0-100 percent."""
    if mult is None:
        return 0.0
    return round((1.0 - mult) * 100, 1)


def _attr(item: Any, key: str, default: float = 0.0) -> float:
    """Read a named dogma attribute from an eos Item; default if absent."""
    a = item.attributes.get(key)
    return float(a.value) if a is not None else default


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RequiredSkill:
    skill: str
    level: int


@dataclass
class Ship:
    name: str
    typeID: int
    slots: dict[str, int]
    hardpoints: dict[str, int]
    fitting: dict[str, float]
    base_hp: dict[str, float]
    base_resists: dict[str, dict[str, float]]
    capacities: dict[str, float]
    bonuses: str  # rendered plain text
    required_skills: list[RequiredSkill]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_ship_by_name(name: str) -> Ship | None:
    """Look up a published ship by exact case-insensitive name.

    Returns None if no ship matches. No fuzzy matching by design — if the
    LLM submits a misspelling, "no match" is the correct signal to retry.
    """
    from eos.gamedata import Item

    # SQLAlchemy 1.4 classical mapping doesn't expose Column type info; pyright
    # can't see Item.typeName / Item.published as queryable. Cast locally.
    Q: Any = Item
    item = (
        eos.db.gamedata_session.query(Item)
        .filter(Q.typeName.ilike(name))
        .filter(Q.published == True)  # noqa: E712 — SQLAlchemy needs ==
        .first()
    )
    if item is None or item.category.name != SHIP_CATEGORY_NAME:
        return None

    return Ship(
        name=item.typeName,
        typeID=item.ID,
        slots={k: int(_attr(item, src)) for src, k in SLOT_ATTRS.items()},
        hardpoints={k: int(_attr(item, src)) for src, k in HARDPOINT_ATTRS.items()},
        fitting={k: _attr(item, src) for src, k in FITTING_ATTRS.items()},
        base_hp={k: _attr(item, src) for src, k in HP_ATTRS.items()},
        base_resists={
            layer: {
                dmg: _resist_pct(
                    item.attributes.get(src).value if item.attributes.get(src) else None
                )
                for src, dmg in attr_map.items()
            }
            for layer, attr_map in (
                ("shield", SHIELD_RESIST_ATTRS),
                ("armor", ARMOR_RESIST_ATTRS),
                ("structure", STRUCTURE_RESIST_ATTRS),
            )
        },
        capacities=_capacities(item),
        bonuses=_strip_tags(item.traits.traitText) if item.traits else "",
        required_skills=[
            RequiredSkill(skill=skill.typeName, level=lvl)
            for skill, lvl in item.requiredSkills.items()
        ],
    )


def _capacities(item: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for src, key in CAPACITY_ATTRS.items():
        val = _attr(item, src)
        if src in ALWAYS_EMIT_CAPACITY or val > 0:
            out[key] = val
    return out
