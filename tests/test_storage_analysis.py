from pathlib import Path

import av
import numpy as np
from PIL import Image

from asset_scout.analysis import analyze_asset
from asset_scout.config import ProjectConfig
from asset_scout.models import AssetManifest, GateDecision, GateStatus, MediaType, RightsEvidence
from asset_scout.storage import Catalog, content_sha256


def test_catalog_round_trip_and_image_analysis(tmp_path: Path):
    config = ProjectConfig(tmp_path)
    catalog = Catalog(config)
    image_path = tmp_path / "fixture.png"
    Image.fromarray(np.full((32, 48, 3), 128, dtype=np.uint8)).save(image_path)
    digest, size = content_sha256(image_path)
    manifest = AssetManifest(asset_id="asset:fixture", candidate_id="fixture:1", provider="fixture",
                             media_type=MediaType.IMAGE, local_path=str(image_path), sha256=digest, bytes=size,
                             mime="image/png", rights=RightsEvidence(provider="fixture", license_id="CC0",
                                                                        commercial_use=True, derivatives=True),
                             gate=GateDecision(status=GateStatus.ALLOW))
    catalog.save_asset(manifest)
    assert catalog.get_asset("asset:fixture")
    report = analyze_asset(manifest, tmp_path, catalog)
    assert report["frame_count"] == 1
    assert report["technical"]["container"] == "png"
    assert catalog.get_asset("asset:fixture").technical["sha256"] == digest
    assert catalog.get_frames("asset:fixture")[0].is_keyframe
    assert Path(report["frames"][0]["preview_path"]).exists()
    catalog.close()


def test_video_analysis_scans_every_frame(tmp_path: Path):
    video_path = tmp_path / "fixture.mp4"
    with av.open(str(video_path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=2)
        stream.width, stream.height = 32, 24
        stream.pix_fmt = "yuv420p"
        for value in (0, 30, 220, 240):
            frame = av.VideoFrame.from_ndarray(np.full((24, 32, 3), value, dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    config = ProjectConfig(tmp_path)
    catalog = Catalog(config)
    digest, size = content_sha256(video_path)
    manifest = AssetManifest(asset_id="asset:video", candidate_id="fixture:video", provider="fixture",
                             media_type=MediaType.VIDEO, local_path=str(video_path), sha256=digest, bytes=size,
                             mime="video/mp4", rights=RightsEvidence(provider="fixture", license_id="CC0",
                                                                        commercial_use=True, derivatives=True),
                             gate=GateDecision(status=GateStatus.ALLOW))
    catalog.save_asset(manifest)
    report = analyze_asset(manifest, tmp_path, catalog)
    assert report["frame_count"] == 4
    assert report["technical"]["frame_count"] == 4
    assert report["technical"]["video_codec"]
    assert len(catalog.get_frames("asset:video")) == 4
    assert report["keyframe_count"] >= 1
    catalog.close()
