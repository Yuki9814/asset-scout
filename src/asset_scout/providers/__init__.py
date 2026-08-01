from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

import httpx

from ..config import accepted_terms
from ..models import Candidate, MediaType, RightsEvidence


class ProviderError(RuntimeError):
    pass


class Provider(ABC):
    name: str
    requires_key: bool = False

    def __init__(self, timeout: float = 20.0):
        self.client = httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "asset-scout/0.2"})

    def close(self) -> None:
        self.client.close()

    @abstractmethod
    def search(self, query: str, media_type: MediaType | None, limit: int) -> list[Candidate]:
        raise NotImplementedError


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    return str(value).strip() or None


def _media_type(mime: str | None, *, default: MediaType = MediaType.IMAGE) -> MediaType:
    return MediaType.VIDEO if mime and mime.startswith("video/") else default


class WikimediaProvider(Provider):
    name = "wikimedia"

    def search(self, query: str, media_type: MediaType | None, limit: int) -> list[Candidate]:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": str(min(limit, 50)),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata|sha1",
            "iiurlwidth": "640",
        }
        response = self.client.get("https://commons.wikimedia.org/w/api.php", params=params)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {}).values()
        results: list[Candidate] = []
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            mime = _text(info.get("mime")) or "application/octet-stream"
            detected = _media_type(mime)
            if media_type and detected != media_type:
                continue
            metadata = info.get("extmetadata") or {}
            license_id = _text(metadata.get("LicenseShortName")) or _text(metadata.get("UsageTerms"))
            license_url = _text(metadata.get("LicenseUrl"))
            title = str(page.get("title", "")).removeprefix("File:")
            evidence_url = f"https://commons.wikimedia.org/wiki/{quote(page.get('title', ''))}"
            author = _text(metadata.get("Artist"))
            tags = [part.strip() for part in (_text(metadata.get("Categories")) or "").split(",") if part.strip()]
            rights = _wikimedia_rights(license_id, license_url, evidence_url, metadata)
            remote_id = str(page.get("pageid") or page.get("title"))
            results.append(Candidate(
                candidate_id=f"wikimedia:{remote_id}", provider=self.name, remote_id=remote_id,
                media_type=detected, title=title, author=author, tags=tags,
                source_url=evidence_url, download_url=_text(info.get("url")), preview_url=_text(info.get("thumburl")),
                width=info.get("width"), height=info.get("height"), mime=mime,
                rights=rights, source_metadata={"page_title": page.get("title"), "sha1": info.get("sha1")},
            ))
        return results


def _wikimedia_rights(license_id: str | None, license_url: str | None, evidence_url: str, metadata: dict[str, Any]) -> RightsEvidence:
    normalized = (license_id or "").upper().replace(" ", "-")
    commercial = None
    derivatives = None
    share_alike = "SA" in normalized
    if normalized in {"CC0", "PUBLIC-DOMAIN", "PDM", "PD"} or "CC-BY" in normalized:
        commercial, derivatives = True, True
    elif "NON-COMMERCIAL" in normalized or "NC" in normalized:
        commercial, derivatives = False, True
    return RightsEvidence(
        provider="wikimedia", license_id=license_id, license_name=license_id, license_url=license_url,
        evidence_url=evidence_url, commercial_use=commercial, derivatives=derivatives,
        share_alike=share_alike, attribution_required=normalized not in {"CC0", "PUBLIC-DOMAIN", "PDM", "PD"},
        attribution_text=_text(metadata.get("Credit")) or _text(metadata.get("Artist")),
    )


class OpenverseProvider(Provider):
    name = "openverse"

    def search(self, query: str, media_type: MediaType | None, limit: int) -> list[Candidate]:
        if media_type == MediaType.VIDEO:
            return []
        response = self.client.get("https://api.openverse.org/v1/images/", params={"q": query, "page_size": min(limit, 50)})
        response.raise_for_status()
        results: list[Candidate] = []
        for item in response.json().get("results", []):
            remote_id = str(item.get("id") or item.get("foreign_landing_url") or item.get("url"))
            license_id = _text(item.get("license"))
            rights = RightsEvidence(
                provider=self.name, license_id=license_id, license_name=license_id,
                license_url=_text(item.get("license_url")), evidence_url=_text(item.get("foreign_landing_url")),
                commercial_use=_openverse_commercial(license_id), derivatives=_openverse_derivatives(license_id),
                attribution_required=license_id not in {"cc0", "pdm", "publicdomain"}, verified_source=False,
            )
            results.append(Candidate(
                candidate_id=f"openverse:{remote_id}", provider=self.name, remote_id=remote_id,
                media_type=MediaType.IMAGE, title=_text(item.get("title")) or remote_id,
                author=_text(item.get("creator")), tags=[str(x) for x in (item.get("tags") or []) if x],
                source_url=_text(item.get("foreign_landing_url")) or _text(item.get("url")) or "",
                download_url=_text(item.get("url")), preview_url=_text(item.get("thumbnail")),
                width=item.get("width"), height=item.get("height"), mime=_text(item.get("filetype")), rights=rights,
                source_metadata={"source": item.get("source"), "provider": item.get("provider")},
            ))
        return results


def _openverse_commercial(license_id: str | None) -> bool | None:
    if not license_id:
        return None
    return license_id.lower() not in {"by-nc", "by-nc-sa", "by-nc-nd", "nc"}


def _openverse_derivatives(license_id: str | None) -> bool | None:
    if not license_id:
        return None
    return license_id.lower() not in {"by-nd", "by-nc-nd", "nd"}


class PexelsProvider(Provider):
    name = "pexels"
    requires_key = True

    def __init__(self, timeout: float = 20.0):
        super().__init__(timeout)
        self.key = os.environ.get("PEXELS_API_KEY")
        if not self.key:
            raise ProviderError("PEXELS_API_KEY is not configured")
        self.client.headers.update({"Authorization": self.key})

    def search(self, query: str, media_type: MediaType | None, limit: int) -> list[Candidate]:
        endpoint = "https://api.pexels.com/videos/search" if media_type == MediaType.VIDEO else "https://api.pexels.com/v1/search"
        response = self.client.get(endpoint, params={"query": query, "per_page": min(limit, 80)})
        response.raise_for_status()
        ack = accepted_terms(self.name)
        return [_pexels_candidate(item, media_type == MediaType.VIDEO, ack) for item in response.json().get("videos" if media_type == MediaType.VIDEO else "photos", [])]


def _pexels_candidate(item: dict[str, Any], video: bool, ack: bool) -> Candidate:
    if video:
        files = [f for f in item.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
        selected = min(files, key=lambda f: (f.get("width") or 10_000, f.get("height") or 10_000)) if files else {}
        width, height, download = selected.get("width"), selected.get("height"), selected.get("link")
        preview_source = (item.get("video_pictures") or [{}])[0]
        remote_id = str(item.get("id"))
        media = MediaType.VIDEO
    else:
        src = item.get("src") or {}
        download = src.get("original") or src.get("large2x")
        width, height, remote_id, media = item.get("width"), item.get("height"), str(item.get("id")), MediaType.IMAGE
        preview_source = {"src": src.get("medium") or src.get("large")}
    return Candidate(
        candidate_id=f"pexels:{remote_id}", provider="pexels", remote_id=remote_id, media_type=media,
        title=f"Pexels {remote_id}", description=item.get("alt"), author=_text(item.get("photographer")),
        source_url=_text(item.get("url")) or f"https://www.pexels.com/photo/{remote_id}/", download_url=download,
        preview_url=_text(preview_source.get("src")),
        width=width, height=height, duration=item.get("duration"), mime="video/mp4" if video else "image/jpeg",
        rights=RightsEvidence(provider="pexels", license_id="LicenseRef-Pexels", license_name="Pexels License",
                              evidence_url="https://help.pexels.com/hc/en-us/articles/900005880463-What-are-the-Terms-and-Conditions",
                              commercial_use=True, derivatives=True, source_terms_ack=ack),
    )


class PixabayProvider(Provider):
    name = "pixabay"
    requires_key = True

    def __init__(self, timeout: float = 20.0):
        super().__init__(timeout)
        self.key = os.environ.get("PIXABAY_API_KEY")
        if not self.key:
            raise ProviderError("PIXABAY_API_KEY is not configured")

    def search(self, query: str, media_type: MediaType | None, limit: int) -> list[Candidate]:
        endpoint = "https://pixabay.com/api/videos/" if media_type == MediaType.VIDEO else "https://pixabay.com/api/"
        params = {"key": self.key, "q": query, "per_page": min(limit, 200), "safesearch": "true"}
        response = self.client.get(endpoint, params=params)
        response.raise_for_status()
        ack = accepted_terms(self.name)
        return [_pixabay_candidate(item, media_type == MediaType.VIDEO, ack) for item in response.json().get("hits", [])]


def _pixabay_candidate(item: dict[str, Any], video: bool, ack: bool) -> Candidate:
    if video:
        video_data = item.get("videos") or {}
        selected = video_data.get("medium") or video_data.get("small") or next(iter(video_data.values()), {})
        download, width, height = selected.get("url"), selected.get("width"), selected.get("height")
        media, mime = MediaType.VIDEO, "video/mp4"
    else:
        download, width, height = item.get("largeImageURL") or item.get("webformatURL"), item.get("imageWidth"), item.get("imageHeight")
        media, mime = MediaType.IMAGE, "image/jpeg"
    remote_id = str(item.get("id"))
    return Candidate(
        candidate_id=f"pixabay:{remote_id}", provider="pixabay", remote_id=remote_id, media_type=media,
        title=f"Pixabay {remote_id}", author=_text(item.get("user")), tags=[x.strip() for x in str(item.get("tags", "")).split(",") if x.strip()],
        source_url=_text(item.get("pageURL")) or "https://pixabay.com/", download_url=download,
        preview_url=_text(item.get("previewURL")), width=width, height=height, duration=item.get("duration"), mime=mime,
        rights=RightsEvidence(provider="pixabay", license_id="LicenseRef-Pixabay", license_name="Pixabay Content License",
                              evidence_url="https://pixabay.com/service/license-summary/", commercial_use=True,
                              derivatives=True, source_terms_ack=ack),
    )


def build_providers(names: list[str] | None = None) -> list[Provider]:
    classes = {"wikimedia": WikimediaProvider, "openverse": OpenverseProvider, "pexels": PexelsProvider, "pixabay": PixabayProvider}
    selected = names or list(classes)
    providers: list[Provider] = []
    for name in selected:
        provider_cls = classes.get(name)
        if not provider_cls:
            continue
        try:
            providers.append(provider_cls())
        except ProviderError:
            continue
    return providers
