# Contributing

Keep provider behavior explicit and testable. New providers must document their official API, terms URL, license fields, domain allowlist, rate limits, and how missing evidence maps to `review` or `deny`.

Before opening a pull request:

```bash
uv run pytest
uv run ruff check .
```

Tests must use synthetic fixtures and must not commit API keys, downloaded provider files, private media, or local `.asset-scout/` state.

