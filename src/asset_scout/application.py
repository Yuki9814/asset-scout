from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

from .analysis import analyze_asset
from .config import ProjectConfig, accepted_terms, project_config, provider_credentials
from .downloads import acquire_candidate
from .gating import evaluate_candidate
from .models import (
    Candidate,
    GateDecision,
    GateStatus,
    MediaType,
    RiskFlags,
    SemanticAnnotation,
    UsageProfile,
)
from .preview import build_candidate_preview
from .providers import build_providers
from .storage import Catalog


class AssetScout:
    def __init__(self, root: str | Path | None = None):
        self.config = project_config(root)
        self.catalog = Catalog(self.config)

    def close(self) -> None:
        self.catalog.close()

    def init_project(self, profile: UsageProfile | None = None) -> dict[str, Any]:
        if profile:
            self.config = ProjectConfig(self.config.root, profile)
            self.catalog.close()
            self.catalog = Catalog(self.config)
        self.config.ensure()
        payload = {"schema_version": "project.v1", "root": str(self.config.root), "profile": self.config.profile.value}
        self.config.project_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    def doctor(self) -> dict[str, Any]:
        checks: dict[str, Any] = {
            "version": "0.1.0", "python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "project_root": str(self.config.root),
            "profile": self.config.profile.value, "state_dir": str(self.config.state_dir),
            "providers": provider_credentials(),
            "terms_acknowledged": {name: accepted_terms(name) for name in ("pexels", "pixabay")},
        }
        checks["optional"] = {}
        for module in ("av", "scenedetect", "mcp"):
            try:
                __import__(module)
                checks["optional"][module] = True
            except ImportError:
                checks["optional"][module] = False
        checks["project_initialized"] = self.config.project_file.exists()
        return checks

    def search(self, query: str, media_type: MediaType | None = None, providers: list[str] | None = None, limit: int = 20) -> dict[str, Any]:
        candidates: list[Candidate] = []
        warnings: list[str] = []
        if providers:
            credentials = provider_credentials()
            known = set(credentials)
            for name in providers:
                if name not in known:
                    warnings.append(f"{name}: unknown provider")
                elif not credentials[name]:
                    warnings.append(f"{name}: credentials are not configured")
        provider_instances = build_providers(providers)
        for provider in provider_instances:
            remaining = limit - len(candidates)
            if remaining <= 0:
                provider.close()
                continue
            try:
                found = provider.search(query, media_type, min(remaining, 50))
                for candidate in found[:remaining]:
                    candidate.gate = evaluate_candidate(candidate, self.config.profile)
                    self.catalog.save_candidate(candidate)
                    candidates.append(candidate)
            except Exception as exc:  # noqa: BLE001 - a provider must not abort a multi-provider search
                warnings.append(f"{provider.name}: {type(exc).__name__}: {exc}")
            finally:
                provider.close()
        return {"query": query, "count": len(candidates), "warnings": warnings,
                "results": [candidate.model_dump(mode="json") for candidate in candidates]}

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.catalog.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        return candidate.model_dump(mode="json")

    def rights_check(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.catalog.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        candidate.gate = evaluate_candidate(candidate, self.config.profile)
        self.catalog.save_candidate(candidate)
        return candidate.gate.model_dump(mode="json")

    def approve(self, candidate_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("a review reason is required")
        candidate = self.catalog.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        if candidate.gate and candidate.gate.status == GateStatus.DENY:
            raise ValueError("hard-denied candidates cannot be approved in v0.1")
        candidate.gate = GateDecision(status=GateStatus.ALLOW, reasons=[f"human review approved: {reason}"], policy_version="human-review.v1")
        self.catalog.save_candidate(candidate)
        self.catalog.record_review(candidate_id, candidate.gate, reason)
        return candidate.gate.model_dump(mode="json")

    def submit_risk_hints(self, candidate_id: str, hints: dict[str, Any]) -> dict[str, Any]:
        candidate = self.catalog.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        candidate.risk = RiskFlags.model_validate({**candidate.risk.model_dump(), **hints})
        candidate.gate = evaluate_candidate(candidate, self.config.profile)
        self.catalog.save_candidate(candidate)
        return {"candidate_id": candidate_id, "risk": candidate.risk.model_dump(mode="json"),
                "gate": candidate.gate.model_dump(mode="json")}

    def preview(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.catalog.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        path = build_candidate_preview(candidate, self.config)
        return {"candidate_id": candidate_id, "path": str(path), "gate": candidate.gate.model_dump(mode="json") if candidate.gate else None}

    def acquire(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.catalog.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"candidate not found: {candidate_id}")
        manifest = acquire_candidate(candidate, self.config, self.catalog)
        return manifest.model_dump(mode="json")

    def analyze(self, asset_id: str, save_keyframes: bool = True) -> dict[str, Any]:
        manifest = self.catalog.get_asset(asset_id)
        if not manifest:
            raise KeyError(f"asset not found: {asset_id}")
        return analyze_asset(manifest, self.config.root, self.catalog, save_keyframes=save_keyframes)

    def get_frames(self, asset_id: str, start: int = 0, end: int | None = None) -> dict[str, Any]:
        if not self.catalog.get_asset(asset_id):
            raise KeyError(f"asset not found: {asset_id}")
        frames = self.catalog.get_frames(asset_id, start, end)
        return {"asset_id": asset_id, "count": len(frames), "frames": [frame.model_dump(mode="json") for frame in frames]}

    def annotate(self, asset_id: str, annotations: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.catalog.get_asset(asset_id):
            raise KeyError(f"asset not found: {asset_id}")
        parsed = [SemanticAnnotation.model_validate(item) for item in annotations]
        self.catalog.save_annotations(asset_id, parsed)
        return {"asset_id": asset_id, "saved": len(parsed), "annotations": [item.model_dump(mode="json") for item in parsed]}

    def library_search(self, query: str | None = None, limit: int = 50) -> dict[str, Any]:
        candidates = self.catalog.list_candidates(query, limit)
        return {"count": len(candidates), "results": [candidate.model_dump(mode="json") for candidate in candidates]}

    def export_manifest(self) -> dict[str, Any]:
        assets = self.catalog.list_assets()
        payload = {"schema_version": "project-manifest.v1", "profile": self.config.profile.value,
                   "project_root": str(self.config.root), "assets": [item.model_dump(mode="json") for item in assets]}
        destination = self.config.manifests_dir / "project-manifest.json"
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"path": str(destination), "asset_count": len(assets), "manifest": payload}
