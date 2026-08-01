from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .config import ProjectConfig
from .models import Candidate, MediaType
from .security import UnsafeURL, validate_remote_url

MAX_PLATFORM_BYTES = 2 * 1024 * 1024 * 1024
TOOL_OUTPUT_LIMIT = 1_000_000
TOOL_TIMEOUT_SECONDS = 120
DOUYIN_MEDIA_HOST_SUFFIXES = ("douyinvod.com", "douyin.com", "iesdouyin.com")
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'，。！？、；;\]\)）】]+|"
    r"(?:www\.)?bilibili\.com/[^\s<>\"'，。！？、；;\]\)）】]+|"
    r"b23\.tv/[^\s<>\"'，。！？、；;\]\)）】]+|"
    r"v\.douyin\.com/[^\s<>\"'，。！？、；;\]\)）】]+",
    re.IGNORECASE,
)


class PlatformError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ToolInfo:
    key: str
    command: str
    path: Path | None
    source: str | None
    sha256: str | None
    version: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "command": self.command,
            "available": self.path is not None,
            "path": str(self.path) if self.path else None,
            "source": self.source,
            "sha256": self.sha256,
            "version": self.version,
        }


def _safe_env() -> dict[str, str]:
    allowed = {"PATH", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.setdefault("PATH", os.defpath)
    environment.setdefault("LANG", "C.UTF-8")
    environment.setdefault("LC_ALL", "C.UTF-8")
    return environment


def _load_overrides(config: ProjectConfig) -> dict[str, Any]:
    path = config.integrations_file
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tool_version(path: Path, key: str) -> str | None:
    command = [str(path), "version"] if key == "douyin" else [str(path), "--help"]
    try:
        result = subprocess.run(
            command,
            env=_safe_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            shell=False,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip()
    if not output or len(output) > TOOL_OUTPUT_LIMIT:
        return None
    if key == "douyin":
        match = re.search(r"parse-video-py\s+([0-9][0-9A-Za-z.\-]*)", output)
        return match.group(1) if match else output.splitlines()[0][:120]
    return "available"


def resolve_tool(config: ProjectConfig, key: str) -> ToolInfo:
    if key == "bilibili":
        env_name, command = "ASSET_SCOUT_BVTEXT_BIN", "bvtext"
    elif key == "douyin":
        env_name, command = "ASSET_SCOUT_DOUYIN_RESOLVER", "parse-video-py"
    else:
        raise ValueError(f"unknown platform tool: {key}")

    path: Path | None = None
    source: str | None = None
    configured = os.environ.get(env_name, "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            path, source = candidate.resolve(), "environment"
    if path is None:
        discovered = shutil.which(command)
        if discovered:
            path, source = Path(discovered).resolve(), "PATH"
    if path is None:
        overrides = _load_overrides(config)
        raw = overrides.get(key)
        configured = raw.get("executable") if isinstance(raw, dict) else raw
        if isinstance(configured, str) and configured.strip():
            candidate = Path(configured).expanduser()
            if candidate.is_file() and os.access(candidate, os.X_OK):
                path, source = candidate.resolve(), "project-config"

    try:
        digest = _sha256_file(path) if path else None
    except OSError:
        digest = None
    version = _tool_version(path, key) if path else None
    return ToolInfo(key, command, path, source, digest, version)


def integration_status(config: ProjectConfig) -> dict[str, Any]:
    return {
        "bilibili": resolve_tool(config, "bilibili").as_dict(),
        "douyin": resolve_tool(config, "douyin").as_dict(),
        "policy": {
            "auth_mode": "none",
            "scope": "single-public-video",
            "browser_cookies": False,
        },
    }


def _extract_one_url(value: str) -> str:
    text = str(value or "").strip()
    matches = list(URL_PATTERN.finditer(text))
    if len(matches) > 1:
        raise PlatformError("unsupported_url", "only one platform URL may be supplied")
    if matches:
        return matches[0].group(0).rstrip("，。！？、；;,.）】)]>\"'")
    bvid = re.search(r"\bBV[a-zA-Z0-9]+\b", text)
    if bvid:
        return f"https://www.bilibili.com/video/{bvid.group(0)}"
    raise PlatformError("unsupported_url", "no supported platform URL was found")


def normalize_platform_source(value: str) -> dict[str, Any]:
    source = _extract_one_url(value)
    if "://" not in source:
        source = f"https://{source}"
    parsed = urlparse(source)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
        raise PlatformError("unsupported_url", "only HTTPS platform URLs without credentials or ports are accepted")
    host = parsed.hostname.lower().rstrip(".")
    if host == "b23.tv" or host == "bilibili.com" or host.endswith(".bilibili.com"):
        match = re.search(r"\bBV[a-zA-Z0-9]+\b", source)
        return {
            "platform": "bilibili",
            "source_url": source,
            "canonical_url": f"https://www.bilibili.com/video/{match.group(0)}" if match else source,
            "remote_id": match.group(0) if match else None,
        }
    if host in {"v.douyin.com", "www.douyin.com", "www.iesdouyin.com"}:
        match = re.search(r"/video/(\d+)", parsed.path)
        if host != "v.douyin.com" and not match:
            raise PlatformError("unsupported_url", "only one public Douyin video URL is supported")
        return {
            "platform": "douyin",
            "source_url": source,
            "canonical_url": f"https://www.douyin.com/video/{match.group(1)}" if match else source,
            "remote_id": match.group(1) if match else None,
        }
    raise PlatformError("unsupported_url", f"unsupported platform host: {host}")


def _run_json_tool(command: list[str], cwd: Path, *, result_path: Path | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=_safe_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            shell=False,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PlatformError("tool_timeout", "platform tool timed out", retryable=True) from exc
    except OSError as exc:
        raise PlatformError("tool_unavailable", f"could not start platform tool: {exc}") from exc
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if len(stdout) > TOOL_OUTPUT_LIMIT or len(stderr) > TOOL_OUTPUT_LIMIT:
        raise PlatformError("tool_output_limit", "platform tool output exceeded the safety limit")
    if completed.returncode != 0:
        detail = " ".join(stderr.split())[:500] or f"exit status {completed.returncode}"
        raise PlatformError("tool_failed", detail, retryable=True)
    if result_path is not None and result_path.exists():
        if result_path.stat().st_size > TOOL_OUTPUT_LIMIT:
            raise PlatformError("tool_output_limit", "platform tool result file exceeded the safety limit")
        raw = result_path.read_text(encoding="utf-8")
    else:
        raw = stdout.strip()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        try:
            payload = json.loads(lines[-1]) if lines else None
        except (json.JSONDecodeError, TypeError) as exc:
            raise PlatformError("invalid_tool_json", "platform tool returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise PlatformError("invalid_tool_json", "platform tool returned a JSON value, not an object")
    return payload


def _metadata_from_result(normalized: dict[str, Any], raw: dict[str, Any], tool: ToolInfo) -> dict[str, Any]:
    platform = normalized["platform"]
    if platform == "bilibili":
        canonical = str(raw.get("canonicalUrl") or normalized["canonical_url"])
        remote_id = str(raw.get("remoteId") or normalized.get("remote_id") or "") or None
        author = raw.get("author")
        title = str(raw.get("title") or remote_id or "bilibili-video")
        tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        duration = raw.get("duration")
        preview_url = raw.get("thumbnailUrl")
        restrictions = raw.get("restrictions") if isinstance(raw.get("restrictions"), dict) else {}
    else:
        canonical = normalized["canonical_url"]
        remote_id = normalized.get("remote_id")
        title = str(raw.get("title") or remote_id or "douyin-video")
        author_data = raw.get("author") if isinstance(raw.get("author"), dict) else {}
        author = author_data.get("name") or author_data.get("nickname")
        tags = [tag.lstrip("#") for tag in re.findall(r"#([^\s#]+)", title)]
        duration = None
        preview_url = raw.get("cover_url")
        restrictions = {}
        if not raw.get("video_url"):
            raise PlatformError("unsupported_media", "resolver returned no video URL")

    return {
        "platform": platform,
        "source_url": normalized["source_url"],
        "canonical_url": canonical,
        "remote_id": remote_id,
        "title": title,
        "author": str(author).strip() if author else None,
        "tags": [str(tag).strip().lstrip("#") for tag in tags if str(tag).strip()],
        "duration": duration,
        "preview_url": preview_url,
        "restrictions": restrictions,
        "tool": tool.as_dict(),
        "raw": {key: value for key, value in raw.items() if key not in {"video_url", "videoPath"}},
    }


def inspect_platform_source(source: str, config: ProjectConfig) -> dict[str, Any]:
    normalized = normalize_platform_source(source)
    config.ensure()
    key = normalized["platform"]
    tool = resolve_tool(config, "bilibili" if key == "bilibili" else "douyin")
    if tool.path is None:
        raise PlatformError("tool_unavailable", f"required {tool.command} executable was not found")

    with tempfile.TemporaryDirectory(prefix=f"inspect-{key}-", dir=config.state_dir) as temporary:
        cwd = Path(temporary)
        if key == "bilibili":
            result_path = cwd / "result.json"
            raw = _run_json_tool(
                [str(tool.path), "inspect", normalized["source_url"], "--result-json", str(result_path), "--json-events"],
                cwd,
                result_path=result_path,
            )
        else:
            raw = _run_json_tool([str(tool.path), "parse", normalized["source_url"], "--format", "json"], cwd)
    return _metadata_from_result(normalized, raw, tool)


def _copy_limited(source: Path, destination: Path, maximum: int = MAX_PLATFORM_BYTES) -> int:
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_file, destination.open("wb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise PlatformError("asset_too_large", "platform media exceeds the size limit")
            output_file.write(chunk)
    if total == 0:
        raise PlatformError("invalid_media", "platform media is empty")
    return total


def _safe_child(path: Path, root: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = root.expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        raise PlatformError("unsafe_tool_output", "platform tool returned a path outside its staging directory")
    return resolved


def _download_bilibili(candidate: Candidate, config: ProjectConfig, destination: Path) -> dict[str, Any]:
    tool = resolve_tool(config, "bilibili")
    if tool.path is None:
        raise PlatformError("tool_unavailable", "bvtext executable was not found")
    with tempfile.TemporaryDirectory(prefix="download-bilibili-", dir=config.state_dir) as temporary:
        cwd = Path(temporary)
        result_path = cwd / "result.json"
        raw = _run_json_tool(
            [
                str(tool.path),
                "download",
                candidate.acquisition.source_url,
                "--work-dir",
                str(cwd),
                "--result-json",
                str(result_path),
                "--json-events",
            ],
            cwd,
            result_path=result_path,
        )
        output = raw.get("videoPath")
        if not isinstance(output, str) or not output.strip():
            raise PlatformError("invalid_tool_result", "bvtext returned no videoPath")
        source_path = _safe_child(Path(output), cwd)
        _copy_limited(source_path, destination)
        return {
            "mime": "video/mp4",
            "lineage": {
                "connector": "bilibili-bvtext",
                "tool": tool.as_dict(),
                "auth_used": False,
                "canonical_url": raw.get("canonicalUrl") or candidate.acquisition.canonical_url,
                "remote_id": raw.get("remoteId") or candidate.acquisition.remote_id,
            },
        }


def _validate_douyin_media_url(url: str) -> str:
    try:
        validated = validate_remote_url(url)
    except UnsafeURL as exc:
        raise PlatformError("unsafe_media_url", str(exc)) from exc
    host = (urlparse(validated).hostname or "").lower().rstrip(".")
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in DOUYIN_MEDIA_HOST_SUFFIXES):
        raise PlatformError("unsafe_media_url", f"Douyin media host is not allow-listed: {host}")
    return validated


def _download_douyin(candidate: Candidate, config: ProjectConfig, destination: Path) -> dict[str, Any]:
    tool = resolve_tool(config, "douyin")
    if tool.path is None:
        raise PlatformError("tool_unavailable", "parse-video-py executable was not found")
    with tempfile.TemporaryDirectory(prefix="resolve-douyin-", dir=config.state_dir) as temporary:
        raw = _run_json_tool(
            [str(tool.path), "parse", candidate.acquisition.source_url, "--format", "json"],
            Path(temporary),
        )
    media_url = raw.get("video_url")
    if not isinstance(media_url, str) or not media_url.strip():
        raise PlatformError("unsupported_media", "resolver returned no video URL")

    current = _validate_douyin_media_url(media_url)
    mime = None
    with httpx.Client(
        timeout=60,
        follow_redirects=False,
        headers={"User-Agent": "asset-scout/0.2", "Referer": "https://www.douyin.com/"},
    ) as client:
        for _ in range(5):
            with client.stream("GET", current) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        raise PlatformError("unsafe_redirect", "media redirect did not include a location")
                    current = _validate_douyin_media_url(urljoin(current, location))
                    continue
                if response.status_code >= 300:
                    raise PlatformError("media_fetch_failed", f"media endpoint returned {response.status_code}", retryable=True)
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip() or None
                if mime and not (mime.startswith("video/") or mime in {"application/octet-stream", "binary/octet-stream"}):
                    raise PlatformError("mime_mismatch", f"resolver returned non-video MIME type: {mime}")
                total = 0
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_PLATFORM_BYTES:
                            raise PlatformError("asset_too_large", "platform media exceeds the size limit")
                        output.write(chunk)
                if total == 0:
                    raise PlatformError("invalid_media", "platform media is empty")
                break
        else:
            raise PlatformError("unsafe_redirect", "too many media redirects")

    return {
        "mime": mime,
        "lineage": {
            "connector": "douyin-parse-video",
            "tool": tool.as_dict(),
            "auth_used": False,
            "canonical_url": candidate.acquisition.canonical_url,
            "remote_id": candidate.acquisition.remote_id,
            "resolver_media_host": (urlparse(current).hostname or "").lower(),
        },
    }


def acquire_platform_candidate(candidate: Candidate, config: ProjectConfig, destination: Path) -> dict[str, Any]:
    if candidate.acquisition is None:
        raise PlatformError("missing_acquisition", "candidate has no platform acquisition specification")
    if candidate.media_type != MediaType.VIDEO:
        raise PlatformError("unsupported_media", "platform connector v0.2 supports video only")
    if candidate.acquisition.connector == "bilibili-bvtext":
        return _download_bilibili(candidate, config, destination)
    if candidate.acquisition.connector == "douyin-parse-video":
        return _download_douyin(candidate, config, destination)
    raise PlatformError("unknown_connector", f"unsupported platform connector: {candidate.acquisition.connector}")
