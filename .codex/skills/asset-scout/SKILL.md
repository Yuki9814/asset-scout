---
name: asset-scout
description: Use the local Asset Scout CLI/MCP workflow to discover, review, acquire, and analyze rights-aware image or video assets. Trigger when a user asks Codex to find usable media for an edited video.
---

# Asset Scout

Asset Scout is the local gatekeeper for remote media. Use it in this order:

1. Run `uv run asset-scout --json doctor` and initialize the project when needed.
2. Search only the configured provider whitelist. Read every candidate's `rights`, `source_url`, `gate`, and `risk` fields.
3. Build a local HTML preview before any acquisition. Treat `review` as a real human decision, and record a reason with `review approve`.
4. Acquire only an `allow` candidate. The resulting SHA-256 manifest is the source of truth for local processing.
5. Run `analysis run` for deterministic frame metrics, then request bounded ranges with `frames get` or use the MCP tools.
6. Add semantic or legal-risk hints through `submit_risk_hints`; do not infer a release, license, or person identity from a filename.

Never download arbitrary URLs, expose provider keys, bypass the gate, or claim that a search result is licensed without its evidence URL.

