# Asset Scout

Asset Scout is a local-first, rights-aware image and video discovery tool for AI-assisted editing. It searches a small whitelist of official provider APIs, records the source and license evidence, applies a deterministic usage gate, downloads only an allowed candidate into a content-addressed local store, and exposes frame metrics through a CLI and MCP server.

The first release is deliberately narrow: macOS ARM is the primary target, Linux is supported for CI, and the project does not scrape arbitrary pages, extract sessions/cookies, bypass provider gates, or treat an aggregator result as proof of a license.

## Quick start

```bash
uv sync --extra dev
uv run asset-scout project init --profile commercial-edited-video
uv run asset-scout --json doctor
uv run asset-scout --json search "night city" --type image --limit 10
uv run asset-scout --json library search night
```

The default profile is intended for edited videos that may be monetized. `allow` means the captured evidence is machine-verifiable for this profile. `review` requires an explicit local approval with a reason. `deny` cannot be downloaded in v0.1.

## Providers and keys

Wikimedia Commons and Openverse discovery work without a key. Openverse is an aggregator: its results remain `review` until the original source and terms are verified. Pexels and Pixabay require their own API key and an explicit terms acknowledgement in the environment:

```bash
export PEXELS_API_KEY="..."
export ASSET_SCOUT_ACCEPT_PEXELS_TERMS=1
export PIXABAY_API_KEY="..."
export ASSET_SCOUT_ACCEPT_PIXABAY_TERMS=1
```

Keys are never written to the catalog or manifests. The provider terms and the current source page are retained as evidence links; the tool is not legal advice.

## Workflow

```text
search -> candidate record -> rights gate -> local preview -> human review (if needed)
                                               -> allow -> HTTPS download -> SHA-256 CAS
                                                                       -> PyAV frame scan
                                                                       -> manifest / MCP
```

Useful commands:

```bash
uv run asset-scout --json candidate show wikimedia:123
uv run asset-scout --json preview build wikimedia:123
uv run asset-scout --json rights check wikimedia:123
uv run asset-scout --json review approve wikimedia:123 --reason "verified the license and source page"
uv run asset-scout --json asset acquire wikimedia:123
uv run asset-scout --json analysis run asset:0123456789abcdef
uv run asset-scout --json frames get asset:0123456789abcdef --start 0 --end 120
uv run asset-scout --json manifest export
uv run asset-scout mcp serve
```

Every-frame metrics are deterministic luma, contrast, and frame-difference values. Representative keyframes are written locally; expensive semantic labels are intentionally supplied later through the MCP `submit_risk_hints` tool rather than bundled model weights.

## Development

```bash
uv run pytest
uv run ruff check .
```

The repository is Apache-2.0 licensed. See [SECURITY.md](SECURITY.md) for the threat boundary and [CONTRIBUTING.md](CONTRIBUTING.md) for the review contract.

