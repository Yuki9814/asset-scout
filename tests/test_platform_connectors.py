from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import pytest

from asset_scout import application, platforms
from asset_scout.application import AssetScout
from asset_scout.config import ProjectConfig
from asset_scout.downloads import acquire_candidate
from asset_scout.models import (
    AcquisitionKind,
    AcquisitionSpec,
    Candidate,
    GateDecision,
    GateStatus,
    MediaType,
    RightsBasis,
    RightsEvidence,
)
from asset_scout.storage import Catalog


def test_platform_urls_accept_share_text_and_reject_multiple_or_non_https() -> None:
    normalized = platforms.normalize_platform_source("看看这个 BV1xy987，https://www.bilibili.com/video/BV1xy987?p=1")
    assert normalized["platform"] == "bilibili"
    assert normalized["remote_id"] == "BV1xy987"
    assert normalized["canonical_url"].endswith("/BV1xy987")

    douyin = platforms.normalize_platform_source("https://www.douyin.com/video/123456789")
    assert douyin["platform"] == "douyin"
    assert douyin["remote_id"] == "123456789"

    with pytest.raises(platforms.PlatformError, match="only one"):
        platforms.normalize_platform_source("https://www.bilibili.com/video/BV1a https://www.douyin.com/video/1")
    with pytest.raises(platforms.PlatformError, match="HTTPS"):
        platforms.normalize_platform_source("http://www.bilibili.com/video/BV1a")


def test_tool_json_parser_accepts_pretty_json_and_never_uses_shell(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return SimpleNamespace(returncode=0, stdout=json.dumps({"title": "fixture"}, indent=2), stderr="")

    monkeypatch.setattr(platforms.subprocess, "run", fake_run)
    payload = platforms._run_json_tool(["resolver", "parse", "https://example.invalid/?q=;echo"], tmp_path)
    assert payload == {"title": "fixture"}
    assert calls[0]["shell"] is False
    assert calls[0]["command"][-1] == "https://example.invalid/?q=;echo"


def test_metadata_drops_ephemeral_media_url() -> None:
    tool = platforms.ToolInfo("douyin", "parse-video-py", Path("/tmp/parser"), "PATH", "sha", "1.0")
    result = platforms._metadata_from_result(
        {
            "platform": "douyin",
            "source_url": "https://www.douyin.com/video/123",
            "canonical_url": "https://www.douyin.com/video/123",
            "remote_id": "123",
        },
        {"title": "#测试 clip", "video_url": "https://media.douyinvod.com/temporary.mp4", "cover_url": "https://cover.invalid/a.jpg"},
        tool,
    )
    assert result["remote_id"] == "123"
    assert "video_url" not in result["raw"]
    assert result["tags"] == ["测试"]


def test_media_url_validation_rejects_private_and_unapproved_hosts(monkeypatch) -> None:
    with pytest.raises(platforms.PlatformError, match="private"):
        platforms._validate_douyin_media_url("https://127.0.0.1/video.mp4")

    monkeypatch.setattr(platforms, "validate_remote_url", lambda url: url)
    with pytest.raises(platforms.PlatformError, match="not allow-listed"):
        platforms._validate_douyin_media_url("https://example.com/video.mp4")


def test_register_source_defaults_to_review_and_requires_rights_evidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        application,
        "inspect_platform_source",
        lambda source, config: {
            "platform": "bilibili",
            "source_url": source,
            "canonical_url": "https://www.bilibili.com/video/BVfixture",
            "remote_id": "BVfixture",
            "title": "Fixture video",
            "author": "Owner",
            "tags": ["fixture"],
            "duration": 1.0,
            "preview_url": None,
            "restrictions": {},
            "tool": {"name": "bvtext", "version": "1.0.0"},
            "raw": {"title": "Fixture video"},
        },
    )
    service = AssetScout(tmp_path)
    try:
        candidate = service.register_platform_source("https://www.bilibili.com/video/BVfixture")
        assert candidate["gate"]["status"] == "review"
        assert candidate["acquisition"]["auth_mode"] == "none"
        with pytest.raises(ValueError, match="--basis"):
            service.approve("bilibili:BVfixture", "not enough evidence")
        approved = service.approve("bilibili:BVfixture", "owned source", RightsBasis.OWNED, "asset-rights.txt")
        assert approved["status"] == "allow"
    finally:
        service.close()


def test_explicit_no_reprint_requires_permission_not_just_a_license() -> None:
    candidate = Candidate(
        candidate_id="bilibili:restricted",
        provider="bilibili-bvtext",
        remote_id="BVrestricted",
        media_type=MediaType.VIDEO,
        title="Restricted",
        source_url="https://www.bilibili.com/video/BVrestricted",
        rights=RightsEvidence(provider="bilibili"),
        acquisition=AcquisitionSpec(
            kind=AcquisitionKind.EXTERNAL_TOOL,
            connector="bilibili-bvtext",
            source_url="https://www.bilibili.com/video/BVrestricted",
            remote_id="BVrestricted",
        ),
        source_metadata={"restrictions": {"noReprint": True}},
    )
    decision = application.evaluate_candidate(candidate)
    assert decision.status == GateStatus.REVIEW

    licensed = candidate.model_copy(
        deep=True,
        update={"rights": candidate.rights.model_copy(update={"basis": RightsBasis.LICENSED})},
    )
    assert application.evaluate_candidate(licensed).status == GateStatus.DENY


def _write_fixture_video(path: Path) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=1)
        stream.width, stream.height = 16, 16
        stream.pix_fmt = "yuv420p"
        frame = av.VideoFrame.from_ndarray(np.zeros((16, 16, 3), dtype=np.uint8), format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_platform_acquisition_uses_staging_cas_and_deduplicates(monkeypatch, tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.mp4"
    _write_fixture_video(fixture)

    def fake_acquire(candidate, config, destination):
        destination.write_bytes(fixture.read_bytes())
        return {"mime": "video/mp4", "lineage": {"connector": candidate.acquisition.connector, "auth_used": False}}

    monkeypatch.setattr("asset_scout.downloads.acquire_platform_candidate", fake_acquire)
    config = ProjectConfig(tmp_path)
    catalog = Catalog(config)
    candidate = Candidate(
        candidate_id="bilibili:BVfixture",
        provider="bilibili-bvtext",
        remote_id="BVfixture",
        media_type=MediaType.VIDEO,
        title="Fixture",
        source_url="https://www.bilibili.com/video/BVfixture",
        rights=RightsEvidence(
            provider="bilibili",
            basis=RightsBasis.OWNED,
            evidence_ref="asset-rights.txt",
            commercial_use=True,
            derivatives=True,
            audio_rights="human-confirmed",
        ),
        acquisition=AcquisitionSpec(
            kind=AcquisitionKind.EXTERNAL_TOOL,
            connector="bilibili-bvtext",
            source_url="https://www.bilibili.com/video/BVfixture",
            canonical_url="https://www.bilibili.com/video/BVfixture",
            remote_id="BVfixture",
        ),
        gate=GateDecision(status=GateStatus.ALLOW),
        mime="video/mp4",
    )
    try:
        first = acquire_candidate(candidate, config, catalog)
        second = acquire_candidate(candidate, config, catalog)
        assert first.sha256 == second.sha256
        assert Path(first.local_path).exists()
        assert first.lineage["acquisition"]["auth_used"] is False
        assert not list(config.state_dir.glob("*.part"))
    finally:
        catalog.close()
