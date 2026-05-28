"""Sanity checks that the package imports and the MCP server boots."""

from __future__ import annotations


def test_package_imports() -> None:
    import jita_mcp

    assert jita_mcp.__version__


def test_server_imports() -> None:
    from jita_mcp.server import mcp

    assert mcp.name == "jita-mcp"
