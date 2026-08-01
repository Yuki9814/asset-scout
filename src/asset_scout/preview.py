from __future__ import annotations

import html
from pathlib import Path

from .config import ProjectConfig
from .models import Candidate


def build_candidate_preview(candidate: Candidate, config: ProjectConfig) -> Path:
    config.ensure()
    title = html.escape(candidate.title)
    source = html.escape(candidate.source_url, quote=True)
    download = html.escape(candidate.download_url or "", quote=True)
    preview = html.escape(candidate.preview_url or candidate.download_url or "", quote=True)
    tags = " ".join(html.escape(tag) for tag in candidate.tags)
    media = (
        f'<video controls preload="metadata" poster="{preview}" src="{download}"></video>'
        if candidate.media_type.value == "video" and download
        else f'<img loading="lazy" src="{preview}" alt="{title}">' if preview else "<p>No provider preview URL.</p>"
    )
    reasons = "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in (candidate.gate.reasons if candidate.gate else [])) + "</ul>"
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Asset Scout</title><style>body{{font:16px system-ui;max-width:960px;margin:2rem auto;padding:0 1rem;color:#202124}}img,video{{max-width:100%;max-height:70vh;background:#111}}.meta{{line-height:1.6}}code{{overflow-wrap:anywhere}}</style></head>
<body><h1>{title}</h1>{media}<div class="meta"><p>Provider: <code>{html.escape(candidate.provider)}</code><br>Type: {candidate.media_type.value}<br>Tags: {tags}</p>
<p>Gate: <strong>{html.escape(candidate.gate.status.value if candidate.gate else "unchecked")}</strong></p>{reasons}
<p><a href="{source}" rel="noreferrer">Open original source</a></p></div></body></html>"""
    path = config.previews_dir / f"candidate-{candidate.candidate_id.replace(':', '_').replace('/', '_')}.html"
    path.write_text(document, encoding="utf-8")
    return path

