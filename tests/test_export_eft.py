"""Tests for the export_eft tool."""

from __future__ import annotations

import pytest
from jita_mcp.tools.export_eft import export_eft


@pytest.mark.sde
def test_eft_format_basic() -> None:
    res = export_eft(
        ship="Condor",
        modules=[
            "Rocket Launcher II",
            "Rocket Launcher II",
            "Rocket Launcher II",
            "Medium Shield Extender II",
            "Medium Shield Extender II",
            "1MN Afterburner II",
            "Ballistic Control System II",
            "Damage Control II",
            "Small Core Defense Field Extender II",
            "Small Core Defense Field Extender II",
        ],
        fit_name="Kinetic Boat",
    )
    assert res["status"] == "ok"
    eft = res["eft"]
    # Header on first line, no blank line after it.
    assert eft.startswith("[Condor, Kinetic Boat]\nRocket Launcher II")
    # Sections separated by exactly one blank line.
    assert (
        "Rocket Launcher II\nRocket Launcher II\nRocket Launcher II\n\nMedium Shield Extender II"
        in eft
    )
    assert "1MN Afterburner II\n\nBallistic Control System II" in eft
    # Required skills surface the modules' direct + transitive prereqs.
    skill_names = {s["skill"] for s in res["required_skills"]}
    assert "Caldari Frigate" in skill_names  # ship prereq
    assert "Missile Launcher Operation" in skill_names  # launcher prereq
    assert "Rockets" in skill_names  # transitive via Rocket Specialization
    assert "Spaceship Command" in skill_names  # transitive via Caldari Frigate


@pytest.mark.sde
def test_eft_default_fit_name_uses_ship_name() -> None:
    res = export_eft(ship="Condor", modules=["Rocket Launcher II"])
    assert res["status"] == "ok"
    assert res["eft"].startswith("[Condor, Condor]\n")


@pytest.mark.sde
def test_eft_unknown_ship() -> None:
    res = export_eft(ship="Not A Ship", modules=[])
    assert res["status"] == "no_match"
    assert res["query"] == "Not A Ship"


@pytest.mark.sde
def test_eft_unknown_module() -> None:
    res = export_eft(ship="Condor", modules=["Definitely Not A Module"])
    assert res["status"] == "unknown_module"
    assert res["module"] == "Definitely Not A Module"


@pytest.mark.sde
def test_eft_section_ordering_high_med_low_rig() -> None:
    """Modules are emitted in slot order regardless of input order."""
    res = export_eft(
        ship="Condor",
        modules=[
            "Small Core Defense Field Extender II",  # rig — should land last
            "1MN Afterburner II",  # med
            "Ballistic Control System II",  # low
            "Rocket Launcher II",  # high
        ],
    )
    eft = res["eft"]
    high_pos = eft.index("Rocket Launcher II")
    med_pos = eft.index("1MN Afterburner II")
    low_pos = eft.index("Ballistic Control System II")
    rig_pos = eft.index("Small Core Defense Field Extender II")
    assert high_pos < med_pos < low_pos < rig_pos
