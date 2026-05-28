"""calculate_fit — validate a complete fit and return all stats."""

from __future__ import annotations

from typing import Any

from jita_mcp.db.eve import get_item_by_name
from jita_mcp.engine.evaluator import BaselineModule, FitEvaluator

_SLOT_NAME_BY_EFFECT = {
    "hiPower": "high",
    "medPower": "med",
    "loPower": "low",
    "rigSlot": "rig",
    "subSystem": "subsystem",
}
_SHIP_SLOT_ATTRS = {
    "high": "hiSlots",
    "med": "medSlots",
    "low": "lowSlots",
    "rig": "rigSlots",
    "subsystem": "maxSubSystems",
}


def calculate_fit(
    ship: str,
    modules: list[str],
    skills: dict[str, int] | None = None,
    implants: list[str] | None = None,
    drones: list[str] | None = None,
) -> dict[str, Any]:
    """Validate a complete ship fit. Returns all stats plus a list of any
    problems with it. Call this every time you propose or modify a fit; do
    not estimate validity or stats from module values alone.

    `modules` is a flat list of module names (repeat the name to fit multiples
    of the same module). For weapons, append the ammo name with a comma:
    "Rocket Launcher II, Caldari Navy Scourge Rocket". For modules without
    ammo, just the module name.

    `skills` defaults to All-V (the "what's possible" baseline). Pass a dict
    `{"Caldari Frigate": 4, ...}` to override specific skills.

    `implants` is an optional list of implant names (e.g.
    ["Inherent Implants 'Squire' Power Grid Management EG-601"]). Implants
    boost ship CPU/PG, damage, speed, etc. and are factored into validity
    and stats. Defaults to no implants.

    `drones` is an optional list of drone names (repeat for multiples, e.g.
    ["Hammerhead II", "Hammerhead II", "Hammerhead II", "Hammerhead II",
     "Hammerhead II"] for 5 Hammerheads). Drone DPS folds into the dps total,
    and validation flags drone_bay_overflow / drone_bandwidth_overflow if
    over budget.

    Returns:
      status: "ok" / error code
      valid: True only when zero errors
      ship: canonical ship name
      slots_used / slots_total: per-slot counts
      fitting_used / fitting_total: cpu, powergrid, calibration
      ehp / ehp_total
      dps with em / thermal / kinetic / explosive / total
      max_speed
      errors: list of {type, message} describing every problem

    Iterate until valid is true, then call export_eft.
    """
    ship_item = get_item_by_name(ship)
    if ship_item is None or ship_item.category.name != "Ship":
        return {"status": "no_match", "query": ship}

    parsed: list[tuple[str, str | None, Any, Any | None]] = []
    for entry in modules:
        name, ammo_name = _parse_entry(entry)
        mod_item = get_item_by_name(name)
        if mod_item is None:
            return {"status": "unknown_module", "module": name}
        ammo_item = None
        if ammo_name is not None:
            ammo_item = get_item_by_name(ammo_name)
            if ammo_item is None:
                return {"status": "unknown_ammo", "ammo": ammo_name, "module": name}
        parsed.append((name, ammo_name, mod_item, ammo_item))

    try:
        ev = FitEvaluator(ship, skills=skills or {}, implants=implants, drones=drones)
    except ValueError as e:
        return {"status": "error", "reason": str(e)}

    baseline = [
        BaselineModule(
            type_id=mod_item.ID,
            ammo_type_id=ammo_item.ID if ammo_item is not None else None,
        )
        for _, _, mod_item, ammo_item in parsed
    ]
    ev.set_baseline(baseline)
    metrics = ev.score_baseline()

    slots_used = _count_slots(mod_item for _, _, mod_item, _ in parsed)
    slots_total = _ship_slot_totals(ship_item)
    errors = _collect_errors(metrics, slots_used, slots_total, parsed, ev)

    return {
        "status": "ok",
        "valid": not errors,
        "ship": ship_item.typeName,
        "slots_used": slots_used,
        "slots_total": slots_total,
        "fitting_used": {
            "cpu": round(metrics.cpu_used, 2),
            "powergrid": round(metrics.pg_used, 2),
            "calibration": round(metrics.calibration_used, 2),
            "drone_bay": round(metrics.drone_bay_used, 2),
            "drone_bandwidth": round(metrics.drone_bandwidth_used, 2),
        },
        "fitting_total": {
            "cpu": round(metrics.cpu_total, 2),
            "powergrid": round(metrics.pg_total, 2),
            "calibration": round(metrics.calibration_total, 2),
            "drone_bay": round(metrics.drone_bay_total, 2),
            "drone_bandwidth": round(metrics.drone_bandwidth_total, 2),
        },
        # Bonused / effective capacities. cargo + drone bay always present;
        # specialised holds only when the ship has them. Reflects whatever
        # cargo-expander modules / rigs in the fit have done to the values.
        "capacities": {k: round(v, 2) for k, v in metrics.capacities.items()},
        "ehp": {k: round(v) for k, v in metrics.ehp.items()},
        "ehp_total": round(metrics.ehp_total),
        "resists": metrics.resists,
        "dps": {
            "em": round(metrics.dps.em, 2),
            "thermal": round(metrics.dps.thermal, 2),
            "kinetic": round(metrics.dps.kinetic, 2),
            "explosive": round(metrics.dps.explosive, 2),
            "total": round(metrics.dps.total, 2),
        },
        "capacitor": {
            "capacity": round(metrics.cap_capacity, 2),
            "stable": metrics.cap_stable,
            "state_pct": round(metrics.cap_state_pct, 2),
            "depletes_at_seconds": (
                round(metrics.cap_depletes_at_seconds, 2)
                if metrics.cap_depletes_at_seconds is not None
                else None
            ),
            "recharge_seconds": round(metrics.cap_recharge_seconds, 2),
        },
        "mobility": {
            "max_speed": round(metrics.max_speed),
            "align_time": round(metrics.align_time, 2),
            "agility": round(metrics.agility, 3),
            "mass": round(metrics.mass),
        },
        "sensor": {
            "scan_resolution": round(metrics.scan_resolution, 1),
            "signature_radius": round(metrics.signature_radius, 1),
        },
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_entry(entry: str) -> tuple[str, str | None]:
    """Split an EFT-style "Module, Ammo" entry. No comma -> ammo None."""
    if "," in entry:
        name, ammo = entry.split(",", 1)
        return name.strip(), ammo.strip()
    return entry.strip(), None


def _slot_name(item: Any) -> str | None:
    for effect_name, slot in _SLOT_NAME_BY_EFFECT.items():
        if effect_name in item.effects:
            return slot
    return None


def _count_slots(items: Any) -> dict[str, int]:
    counts: dict[str, int] = {"high": 0, "med": 0, "low": 0, "rig": 0, "subsystem": 0}
    for item in items:
        slot = _slot_name(item)
        if slot is not None:
            counts[slot] += 1
    return counts


def _ship_slot_totals(ship_item: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for slot, attr_name in _SHIP_SLOT_ATTRS.items():
        attr = ship_item.attributes.get(attr_name)
        out[slot] = int(attr.value) if attr is not None else 0
    return out


def _collect_errors(
    metrics: Any,
    slots_used: dict[str, int],
    slots_total: dict[str, int],
    parsed: list[tuple[str, str | None, Any, Any | None]],
    ev: FitEvaluator,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []

    if metrics.cpu_used > metrics.cpu_total:
        excess = round(metrics.cpu_used - metrics.cpu_total, 2)
        errors.append(
            {
                "type": "cpu_overflow",
                "excess": excess,
                "message": f"CPU over budget by {excess} (used {round(metrics.cpu_used, 2)}, "
                f"have {round(metrics.cpu_total, 2)})",
            }
        )

    if metrics.pg_used > metrics.pg_total:
        excess = round(metrics.pg_used - metrics.pg_total, 2)
        errors.append(
            {
                "type": "powergrid_overflow",
                "excess": excess,
                "message": f"Powergrid over budget by {excess} (used {round(metrics.pg_used, 2)}, "
                f"have {round(metrics.pg_total, 2)})",
            }
        )

    if metrics.calibration_used > metrics.calibration_total:
        excess = round(metrics.calibration_used - metrics.calibration_total, 2)
        errors.append(
            {
                "type": "calibration_overflow",
                "excess": excess,
                "message": f"Calibration over budget by {excess} "
                f"(used {round(metrics.calibration_used, 2)}, "
                f"have {round(metrics.calibration_total, 2)})",
            }
        )

    if metrics.drone_bay_used > metrics.drone_bay_total:
        excess = round(metrics.drone_bay_used - metrics.drone_bay_total, 2)
        errors.append(
            {
                "type": "drone_bay_overflow",
                "excess": excess,
                "message": f"Drone bay over by {excess} m³ "
                f"(used {round(metrics.drone_bay_used, 2)}, "
                f"have {round(metrics.drone_bay_total, 2)})",
            }
        )

    if metrics.drone_bandwidth_used > metrics.drone_bandwidth_total:
        excess = round(metrics.drone_bandwidth_used - metrics.drone_bandwidth_total, 2)
        errors.append(
            {
                "type": "drone_bandwidth_overflow",
                "excess": excess,
                "message": f"Drone bandwidth over by {excess} Mbit/s "
                f"(used {round(metrics.drone_bandwidth_used, 2)}, "
                f"have {round(metrics.drone_bandwidth_total, 2)})",
            }
        )

    for slot in ("high", "med", "low", "rig", "subsystem"):
        if slots_used[slot] > slots_total[slot]:
            errors.append(
                {
                    "type": f"{slot}_slot_overflow",
                    "excess": slots_used[slot] - slots_total[slot],
                    "message": f"{slot} slots over: fitted {slots_used[slot]}, have {slots_total[slot]}",
                }
            )

    # Missing skill prerequisites — check the character's level for each module's
    # declared required skills.
    char = ev._character
    seen_skill_errors: set[tuple[int, int]] = set()
    for name, _, mod_item, _ in parsed:
        for skill_item, required_level in mod_item.requiredSkills.items():
            current = char.getSkill(skill_item.ID).level
            if (
                current < required_level
                and (skill_item.ID, required_level) not in seen_skill_errors
            ):
                seen_skill_errors.add((skill_item.ID, required_level))
                errors.append(
                    {
                        "type": "missing_skill",
                        "module": name,
                        "skill": skill_item.typeName,
                        "required": required_level,
                        "have": current,
                        "message": (
                            f"{name} needs {skill_item.typeName} {required_level} "
                            f"(character has {current})"
                        ),
                    }
                )

    return errors
