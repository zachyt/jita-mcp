"""Engine-agnostic Fit interface.

The concrete implementation is wired up once we lock the engine decision (Pyfa's
bundled eos vs. forked standalone eos vs. custom). For now this defines the shape
tool code can program against.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FitStats:
    cpu_used: float
    cpu_total: float
    pg_used: float
    pg_total: float
    slots_used: dict[str, int]
    slots_total: dict[str, int]
    ehp: float
    ehp_breakdown: dict[str, float]
    dps: float
    damage_profile: dict[str, float]
    cap_stable: bool
    cap_depletes_at_seconds: float | None
    max_speed: float
    align_time: float


@dataclass
class FitError:
    type: str
    magnitude: float
    suggestion: str


@dataclass
class FitResult:
    valid: bool
    stats: FitStats
    errors: list[FitError] = field(default_factory=list)


def evaluate(
    ship_type_id: int,
    module_type_ids: list[int],
    skills: dict[int, int],
) -> FitResult:
    """Evaluate a fit. To be implemented once the engine is chosen."""
    raise NotImplementedError("engine not wired up yet")
