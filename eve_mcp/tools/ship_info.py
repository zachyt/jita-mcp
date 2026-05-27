"""get_ship_info — slot layout, fitting room, base resists, bonuses, required skills."""

from __future__ import annotations


def get_ship_info(ship_name: str) -> dict:
    """Look up a ship's slot layout, CPU, powergrid, base resistances, skill requirements
    to fly, and bonus structure from the EVE SDE. Call this before fitting a ship to confirm
    its capabilities and understand which module types benefit from ship bonuses. Do not
    rely on training knowledge for these values — they change with patches. Returns slot
    counts, fitting room, base HP and resists, per-level skill bonuses, and required skills.
    """
    raise NotImplementedError
