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
        ammo: ev.score_module("Rocket Launcher II", ammo)
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
