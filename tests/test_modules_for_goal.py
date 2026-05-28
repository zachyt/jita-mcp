"""Integration tests for the get_modules_for_goal tool (real eve.db)."""

from __future__ import annotations

import pytest
from jita_mcp.tools.modules_for_goal import get_modules_for_goal


@pytest.mark.sde
async def test_unknown_goal_returns_structured_response() -> None:
    res = await get_modules_for_goal(ship="Condor", goal="nonsense", slot="high")
    assert res["status"] == "unknown_goal"
    assert res["goal"] == "nonsense"


@pytest.mark.sde
async def test_unsupported_slot_returns_structured_response() -> None:
    # We don't register maximize_ehp on high slot — armor reps on high are absent
    res = await get_modules_for_goal(ship="Condor", goal="maximize_ehp", slot="high")
    assert res["status"] == "unsupported"
    assert res["slot"] == "high"


@pytest.mark.sde
async def test_unknown_ship_returns_error() -> None:
    res = await get_modules_for_goal(ship="Not A Ship", goal="maximize_dps", slot="high")
    assert res["status"] == "error"


@pytest.mark.sde
async def test_dps_high_slot_returns_frigate_appropriate_weapons() -> None:
    """The CPU/PG fit filter should drop XL torps from a Condor's options."""
    res = await get_modules_for_goal(
        ship="Condor",
        goal="maximize_kinetic_damage",
        slot="high",
        min_meta_level=5,
        top_n=10,
    )
    assert res["status"] == "ok"
    assert res["candidate_count"] > 0
    names = [c["name"] for c in res["candidates"]]
    # No XL or even Heavy class weapons should fit a frigate.
    assert not any("XL" in n for n in names), names
    assert not any("Heavy Assault" in n for n in names), names
    # Rocket Launcher II should be in there for a Condor.
    assert any("Rocket Launcher" in n for n in names), names


@pytest.mark.sde
async def test_battleship_excludes_small_turrets_by_default() -> None:
    """Megathron should never surface Small/Medium turrets in default mode."""
    res = await get_modules_for_goal(
        ship="Megathron",
        goal="maximize_dps",
        slot="high",
        min_meta_level=5,
        top_n=10,
    )
    names = [c["name"] for c in res["candidates"]]
    assert not any("Small" in n for n in names), names
    assert not any("Medium" in n for n in names), names


@pytest.mark.sde
async def test_raw_true_unfilters_size_check() -> None:
    """raw=True should include small/medium turrets even on a battleship."""
    default_res = await get_modules_for_goal(
        ship="Megathron",
        goal="maximize_dps",
        slot="high",
        min_meta_level=5,
        top_n=5,
    )
    raw_res = await get_modules_for_goal(
        ship="Megathron",
        goal="maximize_dps",
        slot="high",
        min_meta_level=5,
        top_n=5,
        raw=True,
    )
    # raw should see strictly more candidates (small + medium turrets unlocked).
    assert raw_res["candidate_count"] > default_res["candidate_count"]


@pytest.mark.sde
async def test_damage_mod_baseline_lift() -> None:
    """maximize_dps + slot=low + preserve=[launcher]*4 must surface BCS variants."""
    rocket_launcher_ii_type_id = 10631
    res = await get_modules_for_goal(
        ship="Condor",
        goal="maximize_kinetic_damage",
        slot="low",
        preserve=[rocket_launcher_ii_type_id] * 4,
        min_meta_level=5,
        top_n=5,
    )
    assert res["status"] == "ok"
    assert res["candidate_count"] > 0
    # Top result should be a Ballistic Control System (missile damage mod).
    top = res["candidates"][0]
    assert "Ballistic Control" in top["name"], top["name"]
    # And it should produce real DPS (baseline launchers contribute).
    assert top["effective_value"] > 50


@pytest.mark.sde
async def test_speed_med_slot_picks_prop_mod() -> None:
    res = await get_modules_for_goal(
        ship="Condor",
        goal="maximize_speed",
        slot="med",
        min_meta_level=0,
        top_n=5,
    )
    assert res["status"] == "ok"
    assert res["candidate_count"] > 0
    # Top speed candidate should be a microwarpdrive or afterburner.
    top = res["candidates"][0]
    assert top["group"] == "Propulsion Module"
    assert top["effective_value"] > 1000  # Condor base speed is ~400; prop mod 5x+
