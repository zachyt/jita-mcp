"""Score modules on a ship through pyfa's eos engine.

The hot path for get_modules_for_goal is "score N candidates against the same
(ship, skills, baseline-fit) state." Per pyfa profiling notes, the dominant
per-call cost is `Character(initSkills=True)` — instantiating ~500 Skill
objects. We build the Character once per evaluator instance and reuse it
across every score_module call, rebuilding only the (cheap) Fit + candidate
module each time.

Baseline modules (the `preserve` parameter in the tool) are re-added to every
fit before the candidate. This lets damage mods be scored meaningfully: the
preserved weapons in the baseline give them weapon DPS to multiply.
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


@dataclass
class FitMetrics:
    """Per-fit metrics, all computed in one calculateModifiedAttributes pass.
    Callers pick whichever field matches the goal they're ranking by."""

    dps: DamageStats
    ehp: dict[str, float]  # {"shield", "armor", "hull"} — total EHP per layer
    ehp_total: float
    max_speed: float
    cpu_used: float  # post-skill module CPU consumption
    pg_used: float
    cpu_total: float  # post-skill ship CPU output (bonused)
    pg_total: float

    @property
    def fits(self) -> bool:
        return self.cpu_used <= self.cpu_total and self.pg_used <= self.pg_total


@dataclass
class BaselineModule:
    """A module to include in every fit before adding the candidate."""

    type_id: int
    ammo_type_id: int | None = None


class FitEvaluator:
    """Holds a (ship, character, baseline) state and scores individual modules.

    Construction is expensive (~tens of ms per skill loaded). The first score
    also pays a fit-construction cost. Subsequent scores reuse the same Fit
    object, swapping only the candidate slot via fit.modules.replace — much
    cheaper because pyfa's internal caches are warm.

    Build one Evaluator per scoring batch.
    """

    def __init__(
        self,
        ship_name: str,
        skills: dict[str, int] | None = None,
    ) -> None:
        ship_item = get_item_by_name(ship_name)
        if ship_item is None or ship_item.category.name != "Ship":
            raise ValueError(f"unknown ship: {ship_name!r}")
        self._ship_item = ship_item
        self._character = self._build_character(skills or {})
        self._baseline: list[BaselineModule] = []
        # Reused across score_module calls. Built on first call; rebuilt
        # whenever the baseline changes.
        self._fit: Any | None = None
        self._candidate_idx: int | None = None

    def set_baseline(self, baseline: list[BaselineModule]) -> None:
        """Modules (and optional ammo per module) included in every score_module
        call before the candidate. Pass an empty list to clear.

        Invalidates the cached Fit so the next score_module rebuilds with the
        new baseline.
        """
        self._baseline = list(baseline)
        self._fit = None
        self._candidate_idx = None

    def score_module(
        self,
        module_name: str,
        ammo_name: str | None = None,
    ) -> FitMetrics:
        """Score one candidate against the (ship, skills, baseline) state.

        First call builds the Fit. Subsequent calls swap only the candidate
        slot — much faster because pyfa's calc caches warm up after the first
        full pass.
        """
        module_item = get_item_by_name(module_name)
        if module_item is None:
            raise ValueError(f"unknown module: {module_name!r}")

        ammo_item = None
        if ammo_name is not None:
            ammo_item = get_item_by_name(ammo_name)
            if ammo_item is None:
                raise ValueError(f"unknown ammo: {ammo_name!r}")

        if self._fit is None:
            fit = self._fresh_fit()
            self._add_baseline(fit)
            self._add_candidate(fit, module_item, ammo_item, module_name)
            self._candidate_idx = len(fit.modules) - 1
            self._fit = fit
        else:
            fit = self._fit
            assert self._candidate_idx is not None
            new_mod = self._build_candidate_module(module_item, ammo_item, module_name)
            fit.modules.replace(self._candidate_idx, new_mod)
            new_mod.owner = fit  # pyright: ignore[reportAttributeAccessIssue]

        fit.calculateModifiedAttributes()
        return self._read_metrics(fit)

    # ---- internal helpers ------------------------------------------------

    def _build_character(self, skills: dict[str, int]) -> Any:
        # Default to All-V — the "what's possible" baseline the LLM uses when
        # the user hasn't shared their actual skills. Caller can override
        # specific skills by passing them in `skills`.
        char = Character("evaluator", defaultLevel=5, initSkills=True)
        for skill_name, level in skills.items():
            skill_item = get_item_by_name(skill_name)
            if skill_item is None:
                raise ValueError(f"unknown skill: {skill_name!r}")
            char.getSkill(skill_item.ID).setLevel(level, ignoreRestrict=True)
        return char

    def _fresh_fit(self) -> Any:
        fit = Fit(ship=EosShip(self._ship_item))
        fit.character = self._character
        # Attach to the (in-memory) saveddata session so SQLAlchemy wires
        # backref ownership (mod.owner -> fit). Without this, getDps()
        # crashes accessing self.owner.factorReload.
        eos.db.saveddata_session.add(fit)
        return fit

    def _add_baseline(self, fit: Any) -> None:
        for entry in self._baseline:
            item = eos.db.getItem(entry.type_id)
            if item is None:
                raise ValueError(f"baseline typeID {entry.type_id} not in eve.db")
            mod = Module(item)
            mod.state = FittingModuleState.ACTIVE
            if entry.ammo_type_id is not None:
                ammo = eos.db.getItem(entry.ammo_type_id)
                if ammo is not None and mod.isValidCharge(ammo):
                    mod.charge = ammo
            fit.modules.append(mod)
            # Pyfa's mapper uses overlaps='owner' (not backref); set manually.
            mod.owner = fit  # pyright: ignore[reportAttributeAccessIssue]

    def _add_candidate(
        self,
        fit: Any,
        module_item: Any,
        ammo_item: Any | None,
        candidate_name: str,
    ) -> None:
        """Append the candidate module to the fit (used on the very first score)."""
        mod = self._build_candidate_module(module_item, ammo_item, candidate_name)
        fit.modules.append(mod)
        mod.owner = fit  # pyright: ignore[reportAttributeAccessIssue]

    def _build_candidate_module(
        self,
        module_item: Any,
        ammo_item: Any | None,
        candidate_name: str,
    ) -> Any:
        """Construct a Module with state + ammo set, but don't attach it to a fit yet."""
        mod = Module(module_item)
        mod.state = FittingModuleState.ACTIVE  # weapons need ACTIVE to do damage
        if ammo_item is not None:
            if not mod.isValidCharge(ammo_item):
                raise ValueError(
                    f"{ammo_item.typeName!r} is not a valid charge for {candidate_name!r}"
                )
            mod.charge = ammo_item
        return mod

    def _read_metrics(self, fit: Any) -> FitMetrics:
        dps_t = fit.getTotalDps()
        ehp = dict(fit.ehp)
        return FitMetrics(
            dps=DamageStats(
                em=float(dps_t.em),
                thermal=float(dps_t.thermal),
                kinetic=float(dps_t.kinetic),
                explosive=float(dps_t.explosive),
                total=float(dps_t.total),
            ),
            ehp={k: float(v) for k, v in ehp.items()},
            ehp_total=float(sum(ehp.values())),
            max_speed=float(fit.maxSpeed),
            cpu_used=float(getattr(fit, "cpuUsed", 0)),
            pg_used=float(getattr(fit, "pgUsed", 0)),
            cpu_total=float(fit.ship.getModifiedItemAttr("cpuOutput") or 0),
            pg_total=float(fit.ship.getModifiedItemAttr("powerOutput") or 0),
        )
