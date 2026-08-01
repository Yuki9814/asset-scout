from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import typer

from .application import AssetScout
from .models import MediaType, UsageProfile

app = typer.Typer(help="Local-first, rights-aware image and video asset discovery.", no_args_is_help=True)
project_app = typer.Typer(help="Create or inspect a project.")
candidate_app = typer.Typer(help="Inspect stored remote candidates.")
preview_app = typer.Typer(help="Build a local contact-sheet preview.")
rights_app = typer.Typer(help="Evaluate rights gates.")
review_app = typer.Typer(help="Record explicit human review decisions.")
asset_app = typer.Typer(help="Acquire and inspect local assets.")
analysis_app = typer.Typer(help="Analyze local media.")
frames_app = typer.Typer(help="Read frame metrics.")
library_app = typer.Typer(help="Search the local catalog.")
manifest_app = typer.Typer(help="Export project manifests.")
mcp_app = typer.Typer(help="Run the MCP server.")
integration_app = typer.Typer(help="Inspect external platform integration tools.")
source_app = typer.Typer(help="Register a known public platform source.")
for group, name in ((project_app, "project"), (candidate_app, "candidate"), (preview_app, "preview"),
                    (rights_app, "rights"), (review_app, "review"), (asset_app, "asset"),
                    (analysis_app, "analysis"), (frames_app, "frames"), (library_app, "library"),
                    (manifest_app, "manifest"), (mcp_app, "mcp"), (integration_app, "integration"),
                    (source_app, "source")):
    app.add_typer(group, name=name)


@app.callback()
def root_options(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit stable JSON suitable for Codex/MCP workflows."),
    root: str | None = typer.Option(None, "--root", help="Project directory (defaults to the current directory)."),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj.update({"json": json_output, "root": root})


def _emit(ctx: typer.Context, payload: Any) -> None:
    # JSON is intentionally the canonical output in v0.2; human-readable output remains valid JSON.
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _call(ctx: typer.Context, operation: Callable[[AssetScout], Any]) -> None:
    service = AssetScout(ctx.obj.get("root"))
    try:
        _emit(ctx, operation(service))
    except Exception as exc:  # noqa: BLE001 - CLI must return a stable error object
        _emit(ctx, {"ok": False, "error": type(exc).__name__, "message": str(exc)})
        raise typer.Exit(code=1)
    finally:
        service.close()


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check runtime, project state, provider keys, and optional media modules."""
    _call(ctx, lambda service: service.doctor())


@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(...),
    media_type: str | None = typer.Option(None, "--type", help="image or video"),
    provider: list[str] | None = typer.Option(None, "--provider", help="Restrict to one or more providers."),  # noqa: B008
    limit: int = typer.Option(20, min=1, max=100),
) -> None:
    selected = MediaType(media_type) if media_type else None
    _call(ctx, lambda service: service.search(query, selected, provider, limit))


@project_app.command("init")
def project_init(ctx: typer.Context, profile: str = typer.Option(UsageProfile.COMMERCIAL_EDITED_VIDEO.value, "--profile")) -> None:
    _call(ctx, lambda service: service.init_project(UsageProfile(profile)))


@candidate_app.command("show")
def candidate_show(ctx: typer.Context, candidate_id: str) -> None:
    _call(ctx, lambda service: service.candidate(candidate_id))


@preview_app.command("build")
def preview_build(ctx: typer.Context, candidate_id: str) -> None:
    _call(ctx, lambda service: service.preview(candidate_id))


@rights_app.command("check")
def rights_check(ctx: typer.Context, candidate_id: str) -> None:
    _call(ctx, lambda service: service.rights_check(candidate_id))


@review_app.command("approve")
def review_approve(
    ctx: typer.Context,
    candidate_id: str,
    basis: str | None = typer.Option(None, "--basis", help="owned, licensed, or permission"),
    evidence: str | None = typer.Option(None, "--evidence", help="Rights evidence reference"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    _call(ctx, lambda service: service.approve(candidate_id, reason, basis, evidence))


@asset_app.command("acquire")
def asset_acquire(ctx: typer.Context, candidate_id: str) -> None:
    _call(ctx, lambda service: service.acquire(candidate_id))


@analysis_app.command("run")
def analysis_run(ctx: typer.Context, asset_id: str, no_keyframes: bool = typer.Option(False, "--no-keyframes")) -> None:
    _call(ctx, lambda service: service.analyze(asset_id, not no_keyframes))


@frames_app.command("get")
def frames_get(ctx: typer.Context, asset_id: str, start: int = typer.Option(0), end: int | None = typer.Option(None)) -> None:
    _call(ctx, lambda service: service.get_frames(asset_id, start, end))


@library_app.command("search")
def library_search(ctx: typer.Context, query: str | None = typer.Argument(None), limit: int = typer.Option(50, min=1, max=500)) -> None:
    _call(ctx, lambda service: service.library_search(query, limit))


@manifest_app.command("export")
def manifest_export(ctx: typer.Context) -> None:
    _call(ctx, lambda service: service.export_manifest())


@integration_app.command("doctor")
def integration_doctor(ctx: typer.Context) -> None:
    """Report connector discovery, tool hashes, and the v0.2 auth policy."""
    _call(ctx, lambda service: service.integration_status())


@source_app.command("add")
def source_add(ctx: typer.Context, url: str = typer.Argument(..., help="One known public platform URL or share text")) -> None:
    """Inspect one public video and save it as a review candidate."""
    _call(ctx, lambda service: service.register_platform_source(url))


@mcp_app.command("serve")
def mcp_serve(ctx: typer.Context) -> None:
    from .mcp_server import run
    run(ctx.obj.get("root"))


def main() -> None:
    app()
