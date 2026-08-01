# Security boundary

Asset Scout treats remote provider metadata, OCR, subtitles, and downloaded media as untrusted input.

The v0.1 boundary is:

- only HTTPS, provider/CDN allow-listed hosts, no credentials or explicit ports;
- no arbitrary URL downloads, page scraping, session/cookie extraction, or shell execution;
- redirect responses are rejected and must be revalidated by a provider adapter;
- content is streamed to a `.part` file, size-limited, SHA-256 hashed, and atomically moved into the local CAS;
- HTML previews escape remote text; secrets come from environment variables and are never included in JSON output;
- the MCP server exposes search, inspect, review hints, acquisition, analysis, frame reads, local search, and manifest export, but no deletion or rights-gate bypass tool.

Report a security issue privately to the repository maintainers before opening a public issue. Do not include API keys or downloaded private material in reports.

