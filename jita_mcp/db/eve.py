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
    # Mining ships (Venture, mining barges, exhumers, Orca, Rorqual). Note: the
    # attribute is `generalMiningHoldCapacity`, not `specialOreHoldCapacity` —
    # that name doesn't exist in pyfa's eve.db schema.
    "generalMiningHoldCapacity": "ore_hold",
    # Specialised hauler holds (Gallente mineral/ice haulers, Minmatar gas/ammo,
    # Caldari PI/CC, etc).
    "specialMineralHoldCapacity": "mineral_hold",
    "specialGasHoldCapacity": "gas_hold",
    "specialIceHoldCapacity": "ice_hold",
    "specialAmmoHoldCapacity": "ammo_hold",
    "specialCommandCenterHoldCapacity": "command_center_hold",
    "specialPlanetaryCommoditiesHoldCapacity": "planetary_commodities_hold",
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


def get_item_by_name(name: str) -> Any | None:
    """Look up any published Item by exact case-insensitive name.

    Returns the raw eos Item ORM object (or None) — the caller does whatever
    they need with it. Generic primitive; the typed wrappers below build on
    this for ships, modules, ammo, etc.
    """
    from eos.gamedata import Item

    # SQLAlchemy 1.4 classical mapping doesn't expose Column type info; pyright
    # can't see Item.typeName / Item.published as queryable. Cast locally.
    Q: Any = Item
    return (
        eos.db.gamedata_session.query(Item)
        .filter(Q.typeName.ilike(name))
        .filter(Q.published == True)  # noqa: E712 — SQLAlchemy needs ==
        .first()
    )


# Slot type -> effect name in item.effects that marks a module as belonging
# to that slot.
_SLOT_EFFECT_NAME = {
    "high": "hiPower",
    "med": "medPower",
    "low": "loPower",
    "rig": "rigSlot",
    "subsystem": "subSystem",
}

# damage_type -> dgmattribs.attributeName used to read that damage type on an ammo Item.
_DAMAGE_ATTR_NAME = {
    "em": "emDamage",
    "thermal": "thermalDamage",
    "kinetic": "kineticDamage",
    "explosive": "explosiveDamage",
}


def query_modules_in_groups(
    group_names: list[str],
    slot: str,
    exclude: list[int] | None = None,
    min_meta: int = 0,
    max_meta: int = 14,
) -> list[Any]:
    """Return published Item objects whose group name is in `group_names`,
    that have the slot-effect for the requested slot, within the meta-level
    range, excluding any typeIDs in `exclude`.

    Slot must be one of: high / med / low / rig / subsystem.
    """
    from eos.gamedata import Item

    if slot not in _SLOT_EFFECT_NAME:
        raise ValueError(f"slot must be one of {sorted(_SLOT_EFFECT_NAME)}, got {slot!r}")
    slot_effect_name = _SLOT_EFFECT_NAME[slot]
    exclude = exclude or []

    Q: Any = Item

    # First narrow by group + meta + published (cheap). Then filter by slot
    # effect in Python — joining dgmtypeeffects in SQL is uglier than
    # checking item.effects after a small candidate query.
    query = (
        eos.db.gamedata_session.query(Item)
        .join(Q.group)
        .filter(Q.published == True)  # noqa: E712
        .filter(
            Q.group.has(name=group_names[0]) if len(group_names) == 1 else _group_in(group_names)
        )
        .filter(Q.metaLevel >= min_meta)
        .filter(Q.metaLevel <= max_meta)
    )
    if exclude:
        query = query.filter(~Q.ID.in_(exclude))

    candidates = query.all()
    return [c for c in candidates if slot_effect_name in c.effects]


def _group_in(group_names: list[str]) -> Any:
    from eos.gamedata import Group, Item

    GQ: Any = Group
    IQ: Any = Item
    return IQ.group.has(GQ.name.in_(group_names))


def find_best_ammo(weapon_item: Any, damage_type: str | None = None) -> Any | None:
    """Pick the highest-damage ammo a weapon can accept, optionally filtered to a
    specific damage type. Returns the Item or None if the weapon doesn't take
    charges (or has no matching ammo).

    "Best" = max attribute value. EVE's faction-navy ammo (Caldari Navy …) has
    the highest raw damage of any T1-equivalent and reliably wins this scoring.
    Skills are not considered here — if the character can't actually use the
    ammo, the score_module call later will reflect zero DPS naturally.
    """
    from eos.gamedata import Item

    # Charge groups live on the weapon as chargeGroup1..5 attributes.
    cg_ids: list[int] = []
    for i in range(1, 6):
        attr = weapon_item.attributes.get(f"chargeGroup{i}")
        if attr is not None and attr.value:
            cg_ids.append(int(attr.value))
    if not cg_ids:
        return None

    # Many launchers also gate by chargeSize (1=small / 2=medium / 3=large / 4=xl).
    cs_attr = weapon_item.attributes.get("chargeSize")
    charge_size = int(cs_attr.value) if cs_attr is not None else None

    Q: Any = Item
    candidates = (
        eos.db.gamedata_session.query(Item)
        .filter(Q.groupID.in_(cg_ids))
        .filter(Q.published == True)  # noqa: E712
        .all()
    )
    if charge_size is not None:
        candidates = [
            c
            for c in candidates
            if c.attributes.get("chargeSize") is None
            or int(c.attributes["chargeSize"].value) == charge_size
        ]

    def score(c: Any) -> float:
        if damage_type:
            attr = c.attributes.get(_DAMAGE_ATTR_NAME[damage_type])
            return float(attr.value) if attr else 0.0
        return sum(
            float(c.attributes[a].value) if c.attributes.get(a) else 0.0
            for a in _DAMAGE_ATTR_NAME.values()
        )

    candidates = [c for c in candidates if score(c) > 0]
    candidates.sort(key=score, reverse=True)
    return candidates[0] if candidates else None


def get_ship_by_name(name: str) -> Ship | None:
    """Look up a published ship by exact case-insensitive name.

    Returns None if no ship matches. No fuzzy matching by design — if the
    LLM submits a misspelling, "no match" is the correct signal to retry.
    """
    item = get_item_by_name(name)
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
