# Asset Scout

Asset Scout is a local-first, rights-aware image and video discovery tool for AI-assisted editing. It searches a small whitelist of official provider APIs, records the source and license evidence, applies a deterministic usage gate, downloads only an allowed candidate into a content-addressed local store, and exposes frame metrics through a CLI and MCP server.

Asset Scout 0.2.0 adds conservative connectors for one known public Bilibili or Douyin video URL. It does not perform platform keyword search, read browser cookies, access private/login-only content, or treat a platform label such as “original” or “no watermark” as a commercial-use grant.

## Quick start

```bash
uv sync --extra dev
uv run asset-scout project init --profile commercial-edited-video
uv run asset-scout --json doctor
uv run asset-scout --json integration doctor
uv run asset-scout --json search "night city" --type image --limit 10
uv run asset-scout --json library search night
```

The default profile is intended for edited videos that may be monetized. `allow` means the captured evidence is machine-verifiable for this profile. `review` requires an explicit local approval with a reason. `deny` cannot be downloaded in v0.2.

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

## Public platform imports

The platform workflow is intentionally explicit:

```text
source add -> review approve --basis ... --evidence ... -> asset acquire
           -> local CAS -> analysis run -> frames get
```

```bash
uv run asset-scout --json source add "https://www.bilibili.com/video/BV..."
uv run asset-scout --json source add "https://www.douyin.com/video/123..."
uv run asset-scout --json review approve bilibili:BV... \
  --basis owned --evidence rights/record.txt --reason "verified ownership"
uv run asset-scout --json asset acquire bilibili:BV...
```

The Bilibili connector calls an externally installed `bvtext` executable. The Douyin connector calls an externally installed `parse-video-py` resolver pinned by the lock note in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Set `ASSET_SCOUT_BVTEXT_BIN` or `ASSET_SCOUT_DOUYIN_RESOLVER` when the executable is not on `PATH`; project-local overrides belong in the ignored `.asset-scout/integrations.json`. Neither tool, its source, nor its binary is copied into this repository.

Both connectors default candidates to `review`. Approval requires a human-entered rights basis and evidence reference; the connector never supplies that approval. Resolver media URLs are treated as short-lived, re-resolved at acquisition time, validated for HTTPS, redirects, private-address access, size, MIME, PyAV readability, and SHA-256 before entering the CAS.

## Development

```bash
uv run pytest
uv run ruff check .
```

The repository is Apache-2.0 licensed. See [SECURITY.md](SECURITY.md) for the threat boundary, [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for connector provenance, and [CONTRIBUTING.md](CONTRIBUTING.md) for the review contract.
