"""export_eft — format a fit as the EFT string EVE / pyfa accepts.

Pure formatting + a recursive skill-chain walk. No engine, no fit calc.

EFT format (per slot, blank-line-separated, in fixed order):

    [Ship Name, Fit Name]
    high slot 1
    high slot 2
    ...

    med slot 1
    ...

    low slot 1
    ...

    rig 1
    ...
"""

from __future__ import annotations

from typing import Any

from jita_mcp.db.eve import get_item_by_name

# Slot effect name -> EFT section order index. Lower number = earlier in output.
_SLOT_ORDER = {
    "hiPower": 0,
    "medPower": 1,
    "loPower": 2,
    "rigSlot": 3,
    "subSystem": 4,
}


def export_eft(
    ship: str,
    modules: list[str],
    fit_name: str | None = None,
) -> dict[str, Any]:
    """Format a complete fit as an EFT string and list all skills required to fly it.

    Use after calculate_fit confirms the fit is valid. Returns:
      - eft: a multi-line string the user pastes into pyfa or EVE Online
      - required_skills: every skill needed at the level needed, deduplicated
        across the ship and every module (the recursive skill prerequisite
        chain is walked, so a skill that's a prereq for another also appears
        at the right level)

    Modules are listed in input order within each slot section. Pass duplicates
    for multiple of the same module (e.g. three rocket launchers = three
    "Rocket Launcher II" entries).
    """
    ship_item = get_item_by_name(ship)
    if ship_item is None or ship_item.category.name != "Ship":
        return {"status": "no_match", "query": ship}

    resolved: list[tuple[str, Any]] = []
    for name in modules:
        item = get_item_by_name(name)
        if item is None:
            return {"status": "unknown_module", "module": name}
        resolved.append((name, item))

    sections: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: [], 4: []}
    for name, item in resolved:
        slot_idx = _slot_index(item)
        if slot_idx is None:
            return {"status": "not_fittable", "module": name, "reason": "no slot effect on item"}
        sections[slot_idx].append(item.typeName)

    # EFT layout: header line, then sections separated by a single blank line.
    # NB: NO blank line between the header and the first non-empty section.
    label = fit_name or ship_item.typeName
    parts: list[str] = [f"[{ship_item.typeName}, {label}]"]
    first_section = True
    for idx in (0, 1, 2, 3, 4):
        if not sections[idx]:
            continue
        if not first_section:
            parts.append("")  # blank line BETWEEN slot sections
        parts.extend(sections[idx])
        first_section = False
    eft = "\n".join(parts)

    skills = _collect_required_skills([ship_item, *(item for _, item in resolved)])
    return {
        "status": "ok",
        "eft": eft,
        "required_skills": [{"skill": name, "level": level} for name, level in skills],
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _slot_index(item: Any) -> int | None:
    """Map an item to its EFT section index via its slot-marker effect."""
    for effect_name, idx in _SLOT_ORDER.items():
        if effect_name in item.effects:
            return idx
    return None


def _collect_required_skills(items: list[Any]) -> list[tuple[str, int]]:
    """Walk the recursive skill prerequisite tree for every item and return
    (skill_name, max_required_level) pairs, sorted by name.
    """
    levels: dict[int, int] = {}  # skill typeID -> max required level
    names: dict[int, str] = {}

    def visit(skill_item: Any, level: int) -> None:
        sid = skill_item.ID
        if level > levels.get(sid, 0):
            levels[sid] = level
            names[sid] = skill_item.typeName
            # Walk what THIS skill itself requires (always at the same level
            # it's required at — EVE's prereq rule).
            for prereq_skill, prereq_level in skill_item.requiredSkills.items():
                visit(prereq_skill, prereq_level)

    for item in items:
        for skill_item, level in item.requiredSkills.items():
            visit(skill_item, level)

    return sorted(((names[sid], lvl) for sid, lvl in levels.items()), key=lambda p: p[0])
