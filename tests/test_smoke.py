"""Sanity checks that the package imports and tools register."""

from __future__ import annotations


def test_package_imports() -> None:
    import jita_mcp

    assert jita_mcp.__version__


def test_server_imports() -> None:
    from jita_mcp.server import mcp

    assert mcp.name == "jita-mcp"


def test_tools_unimplemented_raise() -> None:
    from jita_mcp.tools import ship_info

    try:
        ship_info.get_ship_info("Condor")
    except NotImplementedError:
        return
    raise AssertionError("expected NotImplementedError until tool is wired up")
