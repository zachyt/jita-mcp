"""get_modules_for_goal — ranked module candidates for a fitting objective.

Flow:
  1. Resolve (goal, slot) -> module groups via engine/categories.
  2. SQL pre-filter eve.db for published modules in those groups, in the
     meta-level range, with the matching slot effect, excluding the user's
     exclude list.
  3. Build a FitEvaluator with the ship + skills (default All-V).
  4. Translate the user's `preserve` list into baseline modules (auto-picking
     best ammo for the goal's damage type, if any). Set on the evaluator.
  5. Score each candidate. For weapon candidates, auto-pick ammo for the
     goal's damage type (or the highest-total damage if no type specified).
  6. Rank by the metric matching the goal (DPS-by-type / total DPS / EHP /
     max-speed). Return top N.

Unsupported (goal, slot) combinations return a structured "unsupported"
response rather than empty results.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from jita_mcp.db.eve import find_best_ammo, query_modules_in_groups
from jita_mcp.engine.categories import (
    _WEAPON_GROUPS,
    DAMAGE_TYPE_BY_GOAL,
    groups_for,
)
from jita_mcp.engine.evaluator import BaselineModule, FitEvaluator, FitMetrics
from jita_mcp.market import get_jita_sell_min

DEFAULT_TOP_N = 15

# Per-group: after this many consecutive over-CPU/PG/calibration candidates,
# stop scoring the rest of that group. 3 is enough margin for occasional
# out-of-order entries within a group (which rarely happens — modules in a
# group are nearly always monotonic in resource cost).
_PER_GROUP_MISS_ABORT = 3

_GOALS_DOC = (
    "maximize_dps, maximize_em_damage, maximize_thermal_damage, "
    "maximize_kinetic_damage, maximize_explosive_damage, maximize_ehp, maximize_speed"
)


async def get_modules_for_goal(
    ship: str,
    goal: str,
    slot: str,
    skills: dict[str, int] | None = None,
    implants: list[str] | None = None,
    exclude: list[int] | None = None,
    preserve: list[int] | None = None,
    min_meta_level: int = 0,
    max_meta_level: int = 14,
    top_n: int = DEFAULT_TOP_N,
    max_module_cost: int | None = None,
    raw: bool = False,
) -> dict[str, Any]:
    """Returns ranked module candidates for a fitting objective on a specific ship.

    Effective stats are computed with ship bonuses and character skills applied
    via pyfa's eos engine (not raw module values). For damage goals, ammo is
    automatically chosen to maximise the target damage type.

    Use `preserve` to pass typeIDs of modules already chosen for the fit —
    they're added to the baseline so damage mods score against real weapon
    DPS (otherwise BCS / MFS / Gyrostab etc. score 0).

    Defaults to All-V skills if `skills` is None. Pass `{}` for All-0; pass a
    dict like `{"Caldari Frigate": 4}` for a specific level (other skills
    still default to V).

    `implants` is an optional list of implant names (e.g.
    ["Inherent Implants 'Squire' Power Grid Management EG-601",
     "Eifyr and Co. 'Rogue' Surgical Strike SS-905"]). Implants boost ship
    CPU/PG, damage, speed, etc. and are factored into both the fit check
    and the effective stats. Defaults to no implants.

    `raw=True` disables the "ship-size sanity" filter that, for battleship-tier
    hulls, drops obviously-wrong-size turrets (Small Pulse Laser on a
    Megathron, etc.). Only set raw=True when the user is explicitly asking for
    an atypical / off-meta fit (e.g. "I want anti-frigate small guns on my
    battleship" or "show me everything"). The default false is right 99% of
    the time and is what makes the tool fast on big ships.

    `max_module_cost` (ISK) drops candidates whose Jita 4-4 sell-min exceeds
    the budget. Cost lookup hits ESI (cached, 5-min TTL). Default None = no
    cost filter, but each returned candidate still includes its jita_sell
    price for the LLM to use.

    Supported goals: maximize_dps, maximize_em_damage, maximize_thermal_damage,
    maximize_kinetic_damage, maximize_explosive_damage, maximize_ehp, maximize_speed.
    Supported slots: high, med, low.
    Unsupported (goal, slot) combinations return {"status": "unsupported", ...}.
    """
    if goal not in DAMAGE_TYPE_BY_GOAL and goal not in {"maximize_ehp", "maximize_speed"}:
        return {"status": "unknown_goal", "goal": goal, "supported": _GOALS_DOC}

    groups = groups_for(goal, slot)
    if not groups:
        return {
            "status": "unsupported",
            "goal": goal,
            "slot": slot,
            "reason": f"no module categories registered for ({goal}, slot={slot})",
        }

    damage_type = DAMAGE_TYPE_BY_GOAL.get(goal)
    skills_effective = _resolve_skills(skills)

    try:
        ev = FitEvaluator(ship, skills=skills_effective, implants=implants)
    except ValueError as e:
        return {"status": "error", "reason": str(e)}

    ev.set_baseline(_build_baseline(preserve or [], damage_type))

    candidates = query_modules_in_groups(
        groups,
        slot=slot,
        exclude=exclude,
        min_meta=min_meta_level,
        max_meta=max_meta_level,
    )
    candidates = _drop_wrong_hardpoint(candidates, ev)
    if not raw:
        candidates = _drop_too_small_turrets(candidates, ev)
    candidates = _drop_wildly_oversized(candidates, ev)
    candidates = _drop_untrainable(candidates, ev)

    # Group candidates and score cheap-first within each group. If the cheapest
    # of a group doesn't fit, its larger siblings won't either (usually) — skip
    # the rest of THAT group. This handles bombers cleanly: Torpedo Launcher
    # group's cheapest gets the role-bonus PG reduction and fits, unlocking
    # the rest of the group. Across-group sort is less important than within-
    # group; we walk in arbitrary group order.
    from itertools import groupby

    candidates.sort(key=lambda c: (c.group.name, _raw_resource_cost(c)))
    scored: list[dict[str, Any]] = []
    for _group_name, group_iter in groupby(candidates, key=lambda c: c.group.name):
        group_misses = 0
        for item in group_iter:
            ammo_name = _pick_ammo_name(item, damage_type)
            # For damage goals, a weapon that can't deal the target damage type
            # at all (e.g. laser asked for kinetic) returns ammo=None and would
            # always score 0. Skip the engine call entirely.
            if damage_type is not None and item.group.name in _WEAPON_GROUPS and ammo_name is None:
                continue
            try:
                metrics = ev.score_module(item.typeName, ammo_name)
            except ValueError:
                continue  # invalid charge etc. — skip silently
            if not metrics.fits:
                group_misses += 1
                if group_misses >= _PER_GROUP_MISS_ABORT:
                    break  # rest of THIS group almost certainly also won't fit
                continue
            group_misses = 0
            value = _goal_metric(metrics, goal, damage_type)
            if value <= 0:
                continue  # no contribution — drop
            scored.append(_format_candidate(item, ammo_name, metrics, value, goal))

    scored.sort(key=lambda c: c["effective_value"], reverse=True)

    # Price only the leaders. Fetch a buffer (3x top_n) so max_module_cost has
    # room to drop expensive candidates and still leave us a full top_n list.
    leaders = scored[: top_n * 3] if max_module_cost else scored[:top_n]
    prices = await get_jita_sell_min([c["typeID"] for c in leaders])
    for c in leaders:
        c["jita_sell"] = prices.get(c["typeID"])
    if max_module_cost is not None:
        # Strict: drop both over-budget AND no-price items. If the LLM gave us
        # a budget, "no Jita orders" effectively means "can't be bought at the
        # canonical hub at any quoted price" — surface only buyable picks.
        leaders = [
            c for c in leaders if c["jita_sell"] is not None and c["jita_sell"] <= max_module_cost
        ]

    return {
        "status": "ok",
        "ship": ship,
        "goal": goal,
        "slot": slot,
        "skills": "all_v" if skills is None else "custom",
        "candidate_count": len(scored),
        "candidates": leaders[:top_n],
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resolve_skills(skills: dict[str, int] | None) -> dict[str, int]:
    """Pass-through. None and an empty dict both yield the evaluator's
    default (All-V); a populated dict overrides specific skills, with
    unlisted skills still at the V default."""
    return skills or {}


def _build_baseline(preserve: list[int], damage_type: str | None) -> list[BaselineModule]:
    """Translate `preserve` typeIDs into BaselineModule entries, auto-picking
    ammo for any preserved weapon."""
    baseline: list[BaselineModule] = []
    for type_id in preserve:
        item = get_item_by_name_by_id(type_id)
        if item is None:
            continue
        ammo_id: int | None = None
        if item.group.name in _WEAPON_GROUPS:
            ammo = find_best_ammo(item, damage_type)
            ammo_id = ammo.ID if ammo else None
        baseline.append(BaselineModule(type_id=type_id, ammo_type_id=ammo_id))
    return baseline


def get_item_by_name_by_id(type_id: int) -> Any | None:
    """Tiny shim so this file doesn't import eos.db directly."""
    from jita_mcp.engine.eos_setup import setup

    setup()
    import eos.db

    return eos.db.getItem(type_id)


def _raw_resource_cost(item: Any) -> float:
    """Sort key: raw CPU + raw PG. Cheaper modules score first so we can
    early-abort once the heavier tail is consistently failing the fit check.
    """
    cpu = item.attributes.get("cpu")
    pg = item.attributes.get("power")
    return (float(cpu.value) if cpu else 0.0) + (float(pg.value) if pg else 0.0)


# Battleship-tier ships should never fit small or medium turrets (chargeSize
# 1 or 2). They CAN, technically — but no real fit ever does. Dropping them
# keeps the scoring tractable on battleships. Frigates / cruisers / BCs are
# left alone because edge cases (pirate frigates, T3 cruisers, etc) abound.
# Missile launchers don't have chargeSize, so they pass through untouched —
# important for the bomber+torpedo case.
_MIN_TURRET_CHARGE_SIZE_BY_SHIP_GROUP = {
    "Battleship": 3,
    "Marauder": 3,
    "Black Ops": 3,
    "Carrier": 4,
    "Dreadnought": 4,
    "Force Auxiliary": 4,
    "Supercarrier": 4,
    "Titan": 4,
}


def _drop_too_small_turrets(candidates: list[Any], ev: FitEvaluator) -> list[Any]:
    """Drop turret modules whose chargeSize is smaller than the ship's class
    should ever realistically fit (e.g. Small Pulse Laser on a Megathron).

    Only applies to ships in _MIN_TURRET_CHARGE_SIZE_BY_SHIP_GROUP; for other
    ships there are too many edge cases (Daredevil fitting medium guns, T2
    pirate ships, etc) to risk a false drop.
    """
    ship_group = ev._ship_item.group.name
    min_size = _MIN_TURRET_CHARGE_SIZE_BY_SHIP_GROUP.get(ship_group)
    if min_size is None:
        return candidates
    keep: list[Any] = []
    for item in candidates:
        cs_attr = item.attributes.get("chargeSize")
        if cs_attr is not None and float(cs_attr.value) < min_size:
            continue
        keep.append(item)
    return keep


def _drop_wrong_hardpoint(candidates: list[Any], ev: FitEvaluator) -> list[Any]:
    """Drop weapons whose hardpoint type the ship has zero of.

    EVE distinguishes turret weapons (energy / hybrid / projectile / precursor)
    from launchers (missiles). A weapon's `turretFitted` or `launcherFitted`
    effect tags it. A frigate like Condor has 3 launcher hardpoints and 0
    turret hardpoints — even with enough high slots, a Light Neutron Blaster
    physically cannot fit it.

    Filters at the hardpoint-type level only; modules that don't use either
    (rigs, modules without weapon-fitting effects) pass through untouched.
    """
    ship_attrs = ev._ship_item.attributes
    turret_attr = ship_attrs.get("turretSlotsLeft")
    launcher_attr = ship_attrs.get("launcherSlotsLeft")
    has_turret = float(turret_attr.value) > 0 if turret_attr is not None else False
    has_launcher = float(launcher_attr.value) > 0 if launcher_attr is not None else False

    keep: list[Any] = []
    for item in candidates:
        needs_turret = "turretFitted" in item.effects
        needs_launcher = "launcherFitted" in item.effects
        if needs_turret and not has_turret:
            continue
        if needs_launcher and not has_launcher:
            continue
        keep.append(item)
    return keep


def _drop_untrainable(candidates: list[Any], ev: FitEvaluator) -> list[Any]:
    """Drop modules whose required skills the character hasn't trained to the
    needed level. For All-V default characters this drops nothing; for users
    who passed actual skill levels it can shrink the candidate set dramatically.

    Always correct: we read the module's declared skill requirements and check
    them against the character — no heuristic.
    """
    char = ev._character
    keep: list[Any] = []
    for item in candidates:
        if all(
            char.getSkill(skill_item.ID).level >= required_level
            for skill_item, required_level in item.requiredSkills.items()
        ):
            keep.append(item)
    return keep


def _drop_wildly_oversized(candidates: list[Any], ev: FitEvaluator) -> list[Any]:
    """Pre-filter to skip the engine for obviously-impossible candidates.

    The engine's post-filter (FitMetrics.fits) is always correct, but running
    it on 600 weapon items at ~5ms each is slow. This cheap raw-attribute
    pre-pass drops items whose raw CPU/PG cost is multiples of what the ship
    could ever output, even with the most generous skill + role bonuses.

    Thresholds:
      raw_cpu > 10x ship raw cpuOutput  -> drop
      raw_pg  > 50x ship raw powerOutput -> drop

    The PG multiplier is deliberately loose because EVE has ships with extreme
    role bonuses (Stealth Bombers fit Torpedo Launchers via a 99% PG reduction;
    Stratios fits T2 large modules; mining barges fit oversized ore holds).
    50x is high enough to preserve all those cases (Manticore + Torpedo
    Launcher II is 540/38 = 14x). Capital and XL-class weapons exceed it
    easily.
    """
    ship_attrs = ev._ship_item.attributes
    ship_raw_cpu = float(ship_attrs["cpuOutput"].value)
    ship_raw_pg = float(ship_attrs["powerOutput"].value)
    cpu_limit = ship_raw_cpu * 10
    pg_limit = ship_raw_pg * 50

    keep: list[Any] = []
    for item in candidates:
        cpu_attr = item.attributes.get("cpu")
        pg_attr = item.attributes.get("power")
        raw_cpu = float(cpu_attr.value) if cpu_attr else 0.0
        raw_pg = float(pg_attr.value) if pg_attr else 0.0
        if raw_cpu > cpu_limit or raw_pg > pg_limit:
            continue
        keep.append(item)
    return keep


def _pick_ammo_name(item: Any, damage_type: str | None) -> str | None:
    """For weapon candidates, pick the best ammo for the goal; otherwise no ammo."""
    if item.group.name not in _WEAPON_GROUPS:
        return None
    ammo = find_best_ammo(item, damage_type)
    return ammo.typeName if ammo else None


def _goal_metric(metrics: FitMetrics, goal: str, damage_type: str | None) -> float:
    if goal == "maximize_ehp":
        return metrics.ehp_total
    if goal == "maximize_speed":
        return metrics.max_speed
    if damage_type is not None:
        return float(getattr(metrics.dps, damage_type))
    return metrics.dps.total


def _format_candidate(
    item: Any,
    ammo_name: str | None,
    metrics: FitMetrics,
    value: float,
    goal: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": item.typeName,
        "typeID": item.ID,
        "group": item.group.name,
        "meta_level": item.metaLevel,
        "effective_value": round(value, 2),
    }
    if ammo_name:
        out["ammo"] = ammo_name
    # Include damage breakdown when the goal is damage-related.
    if goal in DAMAGE_TYPE_BY_GOAL:
        out["dps_breakdown"] = dataclasses.asdict(metrics.dps)
    if goal == "maximize_ehp":
        out["ehp_by_layer"] = metrics.ehp
    return out
