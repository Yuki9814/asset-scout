from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .models import AssetManifest, FrameMetric
from .storage import Catalog


class AnalysisError(RuntimeError):
    pass


def analyze_asset(manifest: AssetManifest, config_root: Path, catalog: Catalog, *, save_keyframes: bool = True) -> dict[str, Any]:
    path = Path(manifest.local_path)
    if not path.exists():
        raise AnalysisError(f"local asset is missing: {path}")
    if manifest.media_type.value == "image":
        metrics = _analyze_image(path, manifest, config_root)
        catalog.save_frames(manifest.asset_id, metrics)
        with Image.open(path) as image:
            width, height = image.size
            container = image.format.lower() if image.format else path.suffix.lower().lstrip(".")
        report = {"asset_id": manifest.asset_id, "media_type": "image", "frame_count": 1,
                  "keyframe_count": 1, "scene_count": 1, "backend": "pillow", "frames": [m.model_dump(mode="json") for m in metrics],
                  "technical": {"container": container, "width": width, "height": height, "frame_count": 1}}
    else:
        report = _analyze_video(path, manifest, config_root, catalog, save_keyframes=save_keyframes)
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    manifest.technical = {**manifest.technical, **technical, "sha256": manifest.sha256, "bytes": manifest.bytes}
    if technical.get("width") is not None:
        manifest.width = int(technical["width"])
    if technical.get("height") is not None:
        manifest.height = int(technical["height"])
    if technical.get("fps") is not None:
        manifest.fps = float(technical["fps"])
    if technical.get("duration") is not None:
        manifest.duration = float(technical["duration"])
    catalog.save_asset(manifest)
    analysis_path = config_root / ".asset-scout" / "manifests" / f"{manifest.asset_id.replace(':', '-')}-analysis.json"
    analysis_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _analyze_image(path: Path, manifest: AssetManifest, root: Path) -> list[FrameMetric]:
    with Image.open(path) as image:
        gray = np.asarray(image.convert("L").resize((64, 64)), dtype=np.float32) / 255.0
        preview = _save_preview(image, manifest.asset_id, 0, root) 
    return [FrameMetric(frame_index=0, timestamp=0.0, mean_luma=float(gray.mean()),
                        contrast=float(gray.std()), change_score=0.0, is_keyframe=True, preview_path=preview)]


def _analyze_video(path: Path, manifest: AssetManifest, root: Path, catalog: Catalog, *, save_keyframes: bool) -> dict[str, Any]:
    try:
        import av
    except ImportError as exc:
        raise AnalysisError("PyAV is required for video analysis; run `uv sync --extra media`") from exc

    batch: list[FrameMetric] = []
    keyframes: list[FrameMetric] = []
    previous: np.ndarray | None = None
    scene_count = 0
    keyframe_count = 0
    frame_count = 0
    fps = manifest.fps or 0.0
    container_name: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    container_duration: float | None = None
    with av.open(str(path)) as container:
        container_name = getattr(container.format, "name", None)
        stream = next((item for item in container.streams if item.type == "video"), None)
        if stream is None:
            raise AnalysisError("no video stream found")
        video_codec = getattr(stream.codec_context, "name", None)
        width, height = stream.width, stream.height
        audio_stream = next((item for item in container.streams if item.type == "audio"), None)
        audio_codec = getattr(audio_stream.codec_context, "name", None) if audio_stream else None
        if container.duration is not None:
            container_duration = float(container.duration / av.time_base)
        if not fps and stream.average_rate:
            fps = float(stream.average_rate)
        for index, frame in enumerate(container.decode(stream)):
            gray = frame.to_ndarray(format="gray")
            sampled = np.asarray(Image.fromarray(gray).resize((64, 64)), dtype=np.float32) / 255.0
            mean_luma = float(sampled.mean())
            contrast = float(sampled.std())
            change = 0.0 if previous is None else float(np.abs(sampled - previous).mean())
            is_keyframe = index == 0 or change >= 0.18
            if is_keyframe:
                scene_count += 1
                keyframe_count += 1
            preview_path = None
            if is_keyframe and save_keyframes and keyframe_count <= 120:
                preview_path = _save_preview(frame.to_image(), manifest.asset_id, index, root)
            metric = FrameMetric(frame_index=index, timestamp=float(frame.time if frame.time is not None else (index / fps if fps else index)),
                                 mean_luma=mean_luma, contrast=contrast, change_score=change,
                                 is_keyframe=is_keyframe, preview_path=preview_path)
            batch.append(metric)
            frame_count += 1
            if is_keyframe:
                keyframes.append(metric)
            if len(batch) >= 1000:
                catalog.save_frames(manifest.asset_id, batch)
                batch.clear()
            previous = sampled
    if batch:
        catalog.save_frames(manifest.asset_id, batch)
    duration = manifest.duration or container_duration
    return {"asset_id": manifest.asset_id, "media_type": "video", "frame_count": frame_count,
            "keyframe_count": keyframe_count, "scene_count": scene_count,
            "fps": fps or None, "backend": "pyav-frame-diff",
            "technical": {"container": container_name, "video_codec": video_codec, "audio_codec": audio_codec,
                           "width": width, "height": height, "fps": fps or None, "duration": duration,
                           "frame_count": frame_count},
            "keyframes": [m.model_dump(mode="json") for m in keyframes]}


def _save_preview(image: Image.Image, asset_id: str, frame_index: int, root: Path) -> str:
    preview_dir = root / ".asset-scout" / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    path = preview_dir / f"{asset_id.replace(':', '-')}-{frame_index:06d}.jpg"
    thumbnail = image.convert("RGB")
    thumbnail.thumbnail((960, 960))
    thumbnail.save(path, format="JPEG", quality=85, optimize=True)
    return str(path)
