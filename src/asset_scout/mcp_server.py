from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer

from .application import AssetScout
from .models import MediaType


def create_server(root: str | None = None) -> MCPServer:
    service = AssetScout(root)
    server = MCPServer(name="asset-scout", version="0.1.0", description="Rights-aware local media discovery")

    @server.tool(name="search_assets", description="Search whitelisted image/video providers and return gated candidates.", structured_output=True)
    def search_assets(query: str, media_type: str | None = None, providers: list[str] | None = None, limit: int = 20) -> dict[str, Any]:
        selected = MediaType(media_type) if media_type else None
        return service.search(query, selected, providers, limit)

    @server.tool(name="inspect_asset", description="Inspect one stored candidate or acquired asset.", structured_output=True)
    def inspect_asset(asset_id: str) -> dict[str, Any]:
        try:
            return service.candidate(asset_id)
        except KeyError:
            manifest = service.catalog.get_asset(asset_id)
            if not manifest:
                raise
            return manifest.model_dump(mode="json")

    @server.tool(name="submit_risk_hints", description="Attach AI or human risk hints to a candidate and re-run the gate.", structured_output=True)
    def submit_risk_hints(candidate_id: str, hints: dict[str, Any]) -> dict[str, Any]:
        return service.submit_risk_hints(candidate_id, hints)

    @server.tool(name="acquire_asset", description="Download an allow-listed candidate into the local CAS.", structured_output=True)
    def acquire_asset(candidate_id: str) -> dict[str, Any]:
        return service.acquire(candidate_id)

    @server.tool(name="analyze_asset", description="Run deterministic media and every-frame metrics on a local asset.", structured_output=True)
    def analyze_asset(asset_id: str, save_keyframes: bool = True) -> dict[str, Any]:
        return service.analyze(asset_id, save_keyframes)

    @server.tool(name="get_frames", description="Read every-frame metrics or a bounded frame range.", structured_output=True)
    def get_frames(asset_id: str, start: int = 0, end: int | None = None) -> dict[str, Any]:
        return service.get_frames(asset_id, start, end)

    @server.tool(name="search_local_assets", description="Search the local candidate catalog.", structured_output=True)
    def search_local_assets(query: str | None = None, limit: int = 50) -> dict[str, Any]:
        return service.library_search(query, limit)

    @server.tool(name="export_project_manifest", description="Export the current local asset manifest.", structured_output=True)
    def export_project_manifest() -> dict[str, Any]:
        return service.export_manifest()

    return server


def run(root: str | None = None) -> None:
    asyncio.run(create_server(root).run_stdio_async())

