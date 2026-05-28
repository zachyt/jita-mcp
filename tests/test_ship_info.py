"""End-to-end tests for the get_ship_info tool against the real SDE."""

from __future__ import annotations

import pytest
from jita_mcp.tools.ship_info import get_ship_info


@pytest.mark.sde
def test_get_ship_info_condor() -> None:
    res = get_ship_info("Condor")

    assert res["name"] == "Condor"
    assert res["typeID"] == 583
    assert res["slots"] == {"high": 4, "med": 4, "low": 2, "rig": 3}
    assert res["hardpoints"] == {"turret": 0, "launcher": 3}
    assert res["fitting"] == {"cpu": 185.0, "powergrid": 35.0, "calibration": 400.0}
    assert res["base_hp"] == {"shield": 400.0, "armor": 250.0, "hull": 250.0}
    assert res["base_resists"]["shield"] == {
        "em": 0.0,
        "thermal": 20.0,
        "kinetic": 40.0,
        "explosive": 50.0,
    }
    # Frigate: just cargo + zero drone fields, no specialised bays.
    assert res["capacities"] == {"cargo": 130.0, "drone_bay": 0.0, "drone_bandwidth": 0.0}
    assert {s["skill"] for s in res["required_skills"]} == {"Caldari Frigate"}


@pytest.mark.sde
def test_get_ship_info_case_insensitive() -> None:
    assert get_ship_info("condor")["typeID"] == 583
    assert get_ship_info("CONDOR")["typeID"] == 583


@pytest.mark.sde
def test_get_ship_info_traits_present() -> None:
    res = get_ship_info("Condor")
    bonuses = res["bonuses"]
    assert any(b["kind"] == "skill_bonus" and b["skill"] == "Caldari Frigate" for b in bonuses)
    assert any(b["kind"] == "role_bonus" and b["skill"] is None for b in bonuses)
    # bonusText should be stripped of <a href=showinfo:...> tags
    for b in bonuses:
        assert "<a " not in b["text"]


def test_get_ship_info_no_match() -> None:
    res = get_ship_info("Not A Real Ship Name 12345")
    assert res == {"status": "no_match", "query": "Not A Real Ship Name 12345"}
