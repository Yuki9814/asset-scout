from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

from .config import ProjectConfig
from .models import AssetManifest, Candidate
from .security import UnsafeURL, validate_remote_url
from .storage import Catalog, cas_path, content_sha256

MAX_BYTES = {"image": 100 * 1024 * 1024, "video": 2 * 1024 * 1024 * 1024}
ALLOWED_HOSTS = {
    "wikimedia": {"commons.wikimedia.org", "upload.wikimedia.org"},
    "openverse": {"api.openverse.org", "openverse.org", "images.openverse.org"},
    "pexels": {"www.pexels.com", "images.pexels.com", "videos.pexels.com"},
    "pixabay": {"pixabay.com", "cdn.pixabay.com"},
}


class DownloadError(RuntimeError):
    pass


def acquire_candidate(candidate: Candidate, config: ProjectConfig, catalog: Catalog) -> AssetManifest:
    if not candidate.gate or candidate.gate.status.value != "allow":
        raise DownloadError("candidate is not allow-listed by the rights gate")
    if not candidate.download_url:
        raise DownloadError("candidate has no provider download URL")
    try:
        url = validate_remote_url(candidate.download_url, ALLOWED_HOSTS.get(candidate.provider, set()))
    except UnsafeURL as exc:
        raise DownloadError(str(exc)) from exc

    suffix = Path(urlparse(url).path).suffix[:10]
    temporary = config.state_dir / f"{uuid.uuid4().hex}.part"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    maximum = MAX_BYTES[candidate.media_type.value]
    try:
        with httpx.Client(timeout=60, follow_redirects=False, headers={"User-Agent": "asset-scout/0.1"}) as client, client.stream("GET", url) as response:
                if response.status_code >= 300:
                    raise DownloadError(f"provider returned non-success status {response.status_code}; redirects are not followed")
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > maximum:
                    raise DownloadError(f"remote asset exceeds {maximum} bytes")
                total = 0
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > maximum:
                            raise DownloadError(f"remote asset exceeds {maximum} bytes")
                        output.write(chunk)
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip() or mimetypes.guess_type(url)[0]
        _validate_media_file(temporary, candidate.media_type.value)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    sha256, size = content_sha256(temporary)
    existing = catalog.get_asset_by_sha256(sha256)
    if existing:
        temporary.unlink(missing_ok=True)
        return existing
    destination = cas_path(config, sha256)
    if not destination.exists():
        temporary.replace(destination)
    else:
        temporary.unlink(missing_ok=True)
    asset_id = f"asset:{sha256[:16]}"
    manifest = AssetManifest(
        asset_id=asset_id, candidate_id=candidate.candidate_id, provider=candidate.provider,
        media_type=candidate.media_type, local_path=str(destination), sha256=sha256, bytes=size,
        mime=mime or candidate.mime, width=candidate.width, height=candidate.height, duration=candidate.duration,
        fps=candidate.fps, rights=candidate.rights, gate=candidate.gate, risk=candidate.risk,
        lineage={"source_url": candidate.source_url, "download_url": candidate.download_url, "remote_id": candidate.remote_id, "suffix": suffix},
    )
    catalog.save_asset(manifest)
    manifest_path = config.manifests_dir / f"{asset_id.replace(':', '-')}.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def _validate_media_file(path: Path, media_type: str) -> None:
    if media_type == "image":
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            raise DownloadError("downloaded bytes are not a valid image") from exc
        return
    try:
        import av

        with av.open(str(path)) as container:
            if not any(stream.type == "video" for stream in container.streams):
                raise DownloadError("downloaded bytes contain no video stream")
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError("downloaded bytes are not a readable video") from exc
