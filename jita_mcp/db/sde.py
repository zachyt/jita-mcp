"""SDE: read-only access to the static data export SQLite database.

All SQL lives here so tools never have to touch the schema. If we ever swap
data sources (Pyfa-built DB, CCP YAML, …) only this module changes.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from jita_mcp.config import settings

# ---------------------------------------------------------------------------
# Dogma attribute IDs. Names match dgmAttributeTypes.attributeName. Pinned
# in one place so a future SDE renumbering is a localized change.
# ---------------------------------------------------------------------------

SHIP_CATEGORY_ID = 6

# Each dict maps SDE attribute ID -> our JSON response key. The dict literally
# is the translation table from EVE's schema to our output; the builder code
# below is one dict-comprehension per section.

FITTING_ATTRS = {48: "cpu", 11: "powergrid", 1132: "calibration"}
SLOT_ATTRS = {14: "high", 13: "med", 12: "low", 1137: "rig"}
HARDPOINT_ATTRS = {102: "turret", 101: "launcher"}
HP_ATTRS = {263: "shield", 265: "armor", 9: "hull"}

# Storage. `cargo` comes from invTypes.capacity (a column, not a dogma attr) —
# it's set separately in the builder. Everything else lives in dgmTypeAttributes.
# Drone bay + bandwidth are always emitted (so the LLM knows when drones aren't
# an option). Other bays are emitted only when the ship actually has one (>0).
CAPACITY_ATTRS = {
    283: "drone_bay",
    1271: "drone_bandwidth",
    908: "ship_maintenance_bay",
    912: "fleet_hangar",
    1086: "fuel_cargo",
    1549: "fuel_bay",
    1556: "mining_hold",
    1557: "gas_hold",
    1558: "mineral_hold",
    1559: "salvage_hold",
    1560: "ship_hold",
    1561: "small_ship_hold",
    1562: "medium_ship_hold",
    1563: "large_ship_hold",
    1564: "industrial_ship_hold",
    1573: "ammo_hold",
    1646: "command_center_hold",
    1653: "planetary_commodities_hold",
    1770: "material_bay",
    1233: "strontium_bay",
}
ALWAYS_EMIT_CAPACITY = {283, 1271}  # drone_bay, drone_bandwidth

# Resists are stored as damage *multipliers* (1.0 = 0% resist, 0.5 = 50% resist).
# We expose as percentages — see _dmg_mult_to_resist_pct.
SHIELD_RESISTS = {271: "em", 274: "thermal", 273: "kinetic", 272: "explosive"}
ARMOR_RESISTS = {267: "em", 270: "thermal", 269: "kinetic", 268: "explosive"}
STRUCTURE_RESISTS = {113: "em", 110: "thermal", 109: "kinetic", 111: "explosive"}

# Required-skill slots — each ship has up to 6 (skill_typeID_attr, level_attr)
# pairs. Skill typeIDs live at 182/183/184/1285/1289/1290; their matching
# levels at 277/278/279/1286/1287/1288.
REQUIRED_SKILL_PAIRS: list[tuple[int, int]] = [
    (182, 277),
    (183, 278),
    (184, 279),
    (1285, 1286),
    (1289, 1287),
    (1290, 1288),
]

# bonusText fields in invTraits contain EVE in-client links like
# <a href=showinfo:3321>Light Missile</a> — strip to plain text for the LLM.
_SHOWINFO_TAG_RE = re.compile(r'<a\s+href=["\']?showinfo:\d+["\']?>(.*?)</a>')


def _strip_showinfo(text: str) -> str:
    return _SHOWINFO_TAG_RE.sub(r"\1", text)


def _dmg_mult_to_resist_pct(mult: float | None) -> float:
    """Convert a dogma damage multiplier (1.0 = 0% resist) to a 0-100 percent."""
    if mult is None:
        return 0.0
    return round((1.0 - mult) * 100, 1)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Trait:
    skill: str | None  # None for role/misc bonuses (skillID = -1 in SDE)
    magnitude: float  # raw bonus value, in `unit`
    unit: str  # e.g. "%", "m", "" if unknown
    text: str  # bonusText with showinfo tags stripped
    kind: str  # "skill_bonus" or "role_bonus"


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
    bonuses: list[Trait]
    required_skills: list[RequiredSkill]


# ---------------------------------------------------------------------------
# SDE wrapper
# ---------------------------------------------------------------------------


class SDE:
    def __init__(self, path: Path) -> None:
        self.path = path
        uri = f"file:{path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    # ---- public API ------------------------------------------------------

    def get_ship_by_name(self, name: str) -> Ship | None:
        """Look up a published ship by exact case-insensitive name.

        Returns None if no ship matches. Does not attempt fuzzy matching — if
        the LLM submitted a wrong/misspelled name, "no match" is the correct
        signal so it can retry.
        """
        row = self._conn.execute(
            """
            SELECT t.typeID, t.typeName, t.capacity
            FROM invTypes t
            JOIN invGroups g ON t.groupID = g.groupID
            WHERE g.categoryID = ?
              AND t.published = 1
              AND LOWER(t.typeName) = LOWER(?)
            LIMIT 1
            """,
            (SHIP_CATEGORY_ID, name),
        ).fetchone()
        if row is None:
            return None

        type_id: int = row["typeID"]
        type_name: str = row["typeName"]
        cargo: float = float(row["capacity"] or 0.0)

        attrs = self._attributes_for(type_id)
        bonuses = self._traits_for(type_id)
        required = self._required_skills_for(attrs)
        capacities = self._capacities_for(attrs, cargo)

        return Ship(
            name=type_name,
            typeID=type_id,
            slots={k: int(attrs.get(aid, 0)) for aid, k in SLOT_ATTRS.items()},
            hardpoints={k: int(attrs.get(aid, 0)) for aid, k in HARDPOINT_ATTRS.items()},
            fitting={k: float(attrs.get(aid, 0.0)) for aid, k in FITTING_ATTRS.items()},
            base_hp={k: float(attrs.get(aid, 0.0)) for aid, k in HP_ATTRS.items()},
            base_resists={
                layer: {
                    dmg: _dmg_mult_to_resist_pct(attrs.get(aid)) for aid, dmg in resist_map.items()
                }
                for layer, resist_map in (
                    ("shield", SHIELD_RESISTS),
                    ("armor", ARMOR_RESISTS),
                    ("structure", STRUCTURE_RESISTS),
                )
            },
            capacities=capacities,
            bonuses=bonuses,
            required_skills=required,
        )

    # ---- internal helpers ------------------------------------------------

    def _attributes_for(self, type_id: int) -> dict[int, float]:
        """All dogma attributes for a type, as {attributeID: value}.

        SDE splits the value between valueInt and valueFloat depending on the
        attribute's storage class. COALESCE handles either form.
        """
        rows = self._conn.execute(
            """
            SELECT attributeID, COALESCE(valueFloat, valueInt) AS value
            FROM dgmTypeAttributes
            WHERE typeID = ?
            """,
            (type_id,),
        ).fetchall()
        return {row["attributeID"]: row["value"] for row in rows if row["value"] is not None}

    def _traits_for(self, type_id: int) -> list[Trait]:
        """Per-ship bonus rows from invTraits, joined to skill and unit names."""
        rows = self._conn.execute(
            """
            SELECT
              t.skillID,
              t.bonus,
              t.bonusText,
              s.typeName    AS skill_name,
              u.displayName AS unit_name
            FROM invTraits t
            LEFT JOIN invTypes s ON t.skillID = s.typeID
            LEFT JOIN eveUnits u ON t.unitID = u.unitID
            WHERE t.typeID = ?
            ORDER BY t.traitID
            """,
            (type_id,),
        ).fetchall()
        traits: list[Trait] = []
        for row in rows:
            skill_id: int | None = row["skillID"]
            is_skill_bonus = skill_id is not None and skill_id > 0
            traits.append(
                Trait(
                    skill=row["skill_name"] if is_skill_bonus else None,
                    magnitude=float(row["bonus"]) if row["bonus"] is not None else 0.0,
                    unit=row["unit_name"] or "",
                    text=_strip_showinfo(row["bonusText"] or ""),
                    kind="skill_bonus" if is_skill_bonus else "role_bonus",
                )
            )
        return traits

    def _capacities_for(self, attrs: dict[int, float], cargo: float) -> dict[str, float]:
        """Build the capacities dict: cargo always, drone bay + bandwidth always,
        specialized bays only when the ship actually has them (value > 0)."""
        out: dict[str, float] = {"cargo": cargo}
        for aid, name in CAPACITY_ATTRS.items():
            val = float(attrs.get(aid, 0.0))
            if aid in ALWAYS_EMIT_CAPACITY or val > 0:
                out[name] = val
        return out

    def _required_skills_for(self, attrs: dict[int, float]) -> list[RequiredSkill]:
        """Collect (skill_typeID, level) pairs from the ship's attributes,
        then resolve typeIDs -> skill names in one query."""
        pairs: list[tuple[int, int]] = []
        for skill_attr, level_attr in REQUIRED_SKILL_PAIRS:
            skill_id = attrs.get(skill_attr)
            level = attrs.get(level_attr)
            if skill_id and level:
                pairs.append((int(skill_id), int(level)))
        if not pairs:
            return []

        ids = [p[0] for p in pairs]
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT typeID, typeName FROM invTypes WHERE typeID IN ({placeholders})",
            ids,
        ).fetchall()
        name_by_id: dict[int, str] = {row["typeID"]: row["typeName"] for row in rows}
        return [
            RequiredSkill(skill=name_by_id.get(sid, f"typeID:{sid}"), level=lvl)
            for sid, lvl in pairs
        ]


# ---------------------------------------------------------------------------
# Module-level lazy singleton
# ---------------------------------------------------------------------------

_sde: SDE | None = None


def get_sde() -> SDE:
    global _sde
    if _sde is None:
        _sde = SDE(settings.sde_path)
    return _sde
