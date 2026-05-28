"""Score modules on a ship through pyfa's eos engine.

The hot path for get_modules_for_goal is "score N candidates against the same
(ship, skills) baseline." Per pyfa profiling notes, the dominant per-call cost
is `Character(initSkills=True)` — instantiating ~500 Skill objects. We build
the Character once per evaluator instance and reuse it across every score_*
call, rebuilding only the (cheap) Fit + candidate module each time.

Skills are passed as {skill_name: level}. None means All-0 (rookie pilot).
For All-V, pass {} (empty dict) and we'll use eos's cached `getCharacter("All 5")`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jita_mcp.db.eve import get_item_by_name
from jita_mcp.engine.eos_setup import setup

setup()
import eos.db  # noqa: E402
from eos.const import FittingModuleState  # noqa: E402
from eos.saveddata.character import Character  # noqa: E402
from eos.saveddata.fit import Fit  # noqa: E402
from eos.saveddata.module import Module  # noqa: E402
from eos.saveddata.ship import Ship as EosShip  # noqa: E402


@dataclass
class DamageStats:
    em: float
    thermal: float
    kinetic: float
    explosive: float
    total: float


class FitEvaluator:
    """Holds a (ship, character) baseline and scores individual modules against it.

    Construction is expensive (~tens of ms per skill loaded). score_module is
    cheap by comparison — a fresh Fit, one module, calculateModifiedAttributes,
    read DPS. Build one Evaluator per scoring batch.
    """

    def __init__(self, ship_name: str, skills: dict[str, int] | None = None) -> None:
        ship_item = get_item_by_name(ship_name)
        if ship_item is None or ship_item.category.name != "Ship":
            raise ValueError(f"unknown ship: {ship_name!r}")
        self._ship_item = ship_item
        self._character = self._build_character(skills or {})

    def _build_character(self, skills: dict[str, int]) -> Any:
        char = Character("evaluator", defaultLevel=0, initSkills=True)
        for skill_name, level in skills.items():
            skill_item = get_item_by_name(skill_name)
            if skill_item is None:
                # Unknown skill name -> raise rather than silently skip.
                raise ValueError(f"unknown skill: {skill_name!r}")
            char.getSkill(skill_item.ID).setLevel(level, ignoreRestrict=True)
        return char

    def score_module(
        self,
        module_name: str,
        ammo_name: str | None = None,
    ) -> DamageStats:
        """Build a fresh fit with one candidate module (+ optional ammo),
        recompute attributes, and return the resulting DPS by damage type."""
        module_item = get_item_by_name(module_name)
        if module_item is None:
            raise ValueError(f"unknown module: {module_name!r}")

        fit = Fit(ship=EosShip(self._ship_item))
        fit.character = self._character
        # Attach to the (in-memory) saveddata session so SQLAlchemy wires
        # backref ownership (mod.owner -> fit). Without this, getDps() crashes
        # accessing self.owner.factorReload.
        eos.db.saveddata_session.add(fit)

        mod = Module(module_item)
        mod.state = FittingModuleState.ACTIVE  # weapons need ACTIVE to deal damage
        if ammo_name is not None:
            ammo_item = get_item_by_name(ammo_name)
            if ammo_item is None:
                raise ValueError(f"unknown ammo: {ammo_name!r}")
            if not mod.isValidCharge(ammo_item):
                raise ValueError(f"{ammo_name!r} is not a valid charge for {module_name!r}")
            mod.charge = ammo_item
        fit.modules.append(mod)
        # Pyfa's mapper uses overlaps='owner' (not backref), so assigning to
        # fit.modules does NOT auto-populate mod.owner. getDps() crashes
        # without it, so wire it manually. (SQLAlchemy classical-mapping
        # relations aren't visible to pyright.)
        mod.owner = fit  # pyright: ignore[reportAttributeAccessIssue]

        fit.calculateModifiedAttributes()
        dps = fit.getTotalDps()
        return DamageStats(
            em=float(dps.em),
            thermal=float(dps.thermal),
            kinetic=float(dps.kinetic),
            explosive=float(dps.explosive),
            total=float(dps.total),
        )
