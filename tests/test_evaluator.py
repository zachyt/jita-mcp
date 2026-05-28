"""Smoke tests for the FitEvaluator wrapper around pyfa's eos engine."""

from __future__ import annotations

import pytest
from jita_mcp.engine.evaluator import FitEvaluator


@pytest.mark.sde
def test_evaluator_applies_ship_kinetic_bonus() -> None:
    """Condor gets +10% kinetic missile damage per level of Caldari Frigate.
    With CF V trained, Scourge (kinetic) should out-damage EM/Th/Exp ammo."""
    ev = FitEvaluator(
        "Condor",
        skills={
            "Caldari Frigate": 5,
            "Missile Launcher Operation": 5,
            "Rockets": 5,
            "Rocket Specialization": 4,
        },
    )
    by_dmg = {
        ammo: ev.score_module("Rocket Launcher II", ammo).dps
        for ammo in (
            "Caldari Navy Mjolnir Rocket",  # EM
            "Caldari Navy Inferno Rocket",  # Thermal
            "Caldari Navy Scourge Rocket",  # Kinetic
            "Caldari Navy Nova Rocket",  # Explosive
        )
    }
    scourge = by_dmg["Caldari Navy Scourge Rocket"]
    mjolnir = by_dmg["Caldari Navy Mjolnir Rocket"]
    # Kinetic should be ~50% higher than non-bonused damage types.
    assert scourge.total > mjolnir.total * 1.4
    # Damage profile is single-type per missile.
    assert scourge.kinetic == pytest.approx(scourge.total)
    assert mjolnir.em == pytest.approx(mjolnir.total)


@pytest.mark.sde
def test_evaluator_baseline_lift_for_damage_mod() -> None:
    """A BCS scored against a baseline of 4 rocket launchers must show DPS lift."""
    from jita_mcp.db.eve import get_item_by_name
    from jita_mcp.engine.evaluator import BaselineModule

    rocket = get_item_by_name("Rocket Launcher II")
    scourge = get_item_by_name("Caldari Navy Scourge Rocket")
    assert rocket is not None and scourge is not None

    ev = FitEvaluator(
        "Condor",
        skills={
            "Caldari Frigate": 5,
            "Missile Launcher Operation": 5,
            "Rockets": 5,
            "Rocket Specialization": 4,
        },
    )
    ev.set_baseline([BaselineModule(type_id=rocket.ID, ammo_type_id=scourge.ID)] * 4)

    bcs1 = ev.score_module("Ballistic Control System I").dps.total
    bcs2 = ev.score_module("Ballistic Control System II").dps.total
    # BCS II must out-DPS BCS I (more bonus), and both must exceed bare baseline.
    assert bcs2 > bcs1 > 0
    # Baseline alone (no BCS) — score a no-op module to measure: clear baseline
    # and score one launcher to estimate per-launcher contribution.
    ev.set_baseline([])
    single = ev.score_module("Rocket Launcher II", "Caldari Navy Scourge Rocket").dps.total
    # 4 launchers + BCS II should be > 4x a single launcher (the BCS multiplies).
    assert bcs2 > single * 4


@pytest.mark.sde
def test_evaluator_unknown_ship_raises() -> None:
    with pytest.raises(ValueError, match="unknown ship"):
        FitEvaluator("Not A Real Ship")


@pytest.mark.sde
def test_evaluator_unknown_module_raises() -> None:
    ev = FitEvaluator("Condor")
    with pytest.raises(ValueError, match="unknown module"):
        ev.score_module("Not A Real Module")


@pytest.mark.sde
def test_evaluator_invalid_charge_raises() -> None:
    ev = FitEvaluator("Condor")
    # Hybrid charge in a missile launcher: invalid.
    with pytest.raises(ValueError, match="not a valid charge"):
        ev.score_module("Rocket Launcher II", "Antimatter Charge S")
