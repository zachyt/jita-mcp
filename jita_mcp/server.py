"""MCP server entry point. Registers tools and exposes a streamable-HTTP endpoint."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from jita_mcp.config import settings
from jita_mcp.tools import (
    calculate_fit,
    export_eft,
    modules_by_attribute,
    modules_for_goal,
    ship_info,
)

mcp = FastMCP(
    name="jita-mcp",
    instructions=(
        "EVE Online fitting tools. Use these for ship stats, module stats, fit "
        "validation, and prices. Do not estimate from training knowledge — EVE data "
        "changes with patches and only the values returned here are authoritative."
    ),
    stateless_http=True,
    json_response=True,
)

mcp.tool()(ship_info.get_ship_info)
mcp.tool()(modules_for_goal.get_modules_for_goal)
mcp.tool()(modules_by_attribute.get_modules_by_attribute)
mcp.tool()(calculate_fit.calculate_fit)
mcp.tool()(export_eft.export_eft)


app = mcp.streamable_http_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
