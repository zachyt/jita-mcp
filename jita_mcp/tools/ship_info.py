"""get_ship_info — slot layout, fitting room, base resists, bonuses, required skills.

Data goes through pyfa's eos (jita_mcp.db.eve). Fuzzwork SDE is reserved for
universe/region lookups in other tools.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from jita_mcp.db.eve import get_ship_by_name


def get_ship_info(ship_name: str) -> dict[str, Any]:
    """Look up a ship's slot layout, fitting room (CPU / powergrid / calibration),
    turret and launcher hardpoints, base HP, base resistances, storage capacities
    (cargo, drone bay, fuel bay, ship maintenance bay, etc.), ship-bonus text,
    and required skills.

    Call this before fitting a ship to confirm its capabilities and to understand
    which module categories benefit from ship bonuses. Do not rely on training
    knowledge for numeric values — they change with patches.

    Ship name is matched exact-case-insensitive. If no published ship matches,
    returns {"status": "no_match", "query": <name>} so you can retry.
    """
    ship = get_ship_by_name(ship_name)
    if ship is None:
        return {"status": "no_match", "query": ship_name}
    return dataclasses.asdict(ship)
