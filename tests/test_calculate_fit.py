"""Tests for the calculate_fit tool."""

from __future__ import annotations

import pytest
from jita_mcp.tools.calculate_fit import calculate_fit


@pytest.mark.sde
def test_valid_condor_fit() -> None:
    """A modest Condor fit that comfortably fits at All-V should validate clean."""
    res = calculate_fit(
        ship="Condor",
        modules=[
            "Rocket Launcher II, Caldari Navy Scourge Rocket",
            "Rocket Launcher II, Caldari Navy Scourge Rocket",
            "Rocket Launcher II, Caldari Navy Scourge Rocket",
            "Small Shield Extender II",
            "Small Shield Extender II",
            "1MN Afterburner II",
            "Ballistic Control System II",
            "Damage Control II",
        ],
    )
    assert res["status"] == "ok"
    assert res["valid"], res["errors"]
    assert res["slots_used"]["high"] == 3
    assert res["slots_used"]["med"] == 3
    assert res["slots_used"]["low"] == 2
    assert res["fitting_used"]["cpu"] <= res["fitting_total"]["cpu"]
    assert res["fitting_used"]["powergrid"] <= res["fitting_total"]["powergrid"]
    assert res["dps"]["kinetic"] > 0  # ship bonus applies
    assert res["ehp_total"] > 0
    assert res["max_speed"] > 400  # AB boosts above base ~400 m/s


@pytest.mark.sde
def test_overfit_cpu_and_pg_surfaces_errors() -> None:
    res = calculate_fit(
        ship="Condor",
        modules=["Rocket Launcher II"] * 4
        + ["Medium Shield Extender II"] * 4
        + ["Ballistic Control System II"] * 2,
        skills={"Caldari Frigate": 1, "Missile Launcher Operation": 1},
    )
    assert res["status"] == "ok"
    assert not res["valid"]
    error_types = {e["type"] for e in res["errors"]}
    assert "cpu_overflow" in error_types
    assert "powergrid_overflow" in error_types
    assert "missing_skill" in error_types


@pytest.mark.sde
def test_calibration_field_reported() -> None:
    """fitting_used/fitting_total now include calibration; verify it surfaces."""
    res = calculate_fit(ship="Condor", modules=["Small Core Defense Field Extender II"])
    assert res["status"] == "ok"
    assert "calibration" in res["fitting_used"]
    assert "calibration" in res["fitting_total"]
    assert res["fitting_total"]["calibration"] > 0
    assert res["fitting_used"]["calibration"] > 0


@pytest.mark.sde
def test_slot_overflow_high() -> None:
    """Fitting 5 high-slot modules on a Condor (4 high slots) flags overflow."""
    res = calculate_fit(
        ship="Condor",
        modules=[
            "Rocket Launcher II",
            "Rocket Launcher II",
            "Rocket Launcher II",
            "Rocket Launcher II",
            "Rocket Launcher II",  # 5th — overflow
        ],
    )
    assert res["status"] == "ok"
    assert any(e["type"] == "high_slot_overflow" for e in res["errors"])


@pytest.mark.sde
def test_unknown_ship() -> None:
    res = calculate_fit(ship="Not A Ship", modules=[])
    assert res["status"] == "no_match"


@pytest.mark.sde
def test_unknown_module() -> None:
    res = calculate_fit(ship="Condor", modules=["Not A Real Module"])
    assert res["status"] == "unknown_module"
    assert res["module"] == "Not A Real Module"


@pytest.mark.sde
def test_unknown_ammo() -> None:
    res = calculate_fit(
        ship="Condor",
        modules=["Rocket Launcher II, Not A Real Ammo"],
    )
    assert res["status"] == "unknown_ammo"


@pytest.mark.sde
def test_empty_fit_returns_bare_ship() -> None:
    """Edge case: no modules. Ship hull stats still come back; no errors."""
    res = calculate_fit(ship="Condor", modules=[])
    assert res["status"] == "ok"
    assert res["valid"]
    assert res["slots_used"] == {"high": 0, "med": 0, "low": 0, "rig": 0, "subsystem": 0}
    assert res["dps"]["total"] == 0
    assert res["ehp_total"] > 0  # hull always has HP
