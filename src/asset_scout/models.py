from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class GateStatus(StrEnum):
    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


class UsageProfile(StrEnum):
    COMMERCIAL_EDITED_VIDEO = "commercial-edited-video"
    NONCOMMERCIAL = "noncommercial"


class AcquisitionKind(StrEnum):
    EXTERNAL_TOOL = "external-tool"
    RESOLVED_HTTP = "resolved-http"


class RightsBasis(StrEnum):
    OWNED = "owned"
    LICENSED = "licensed"
    PERMISSION = "permission"


class RiskFlags(BaseModel):
    model_config = ConfigDict(extra="allow")

    identifiable_person: bool = False
    minor: bool = False
    logo_or_trademark: bool = False
    watermark: bool = False
    sensitive_context: bool = False
    editorial_only: bool = False
    model_release: bool | None = None
    property_release: bool | None = None


class RightsEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str
    basis: RightsBasis | None = None
    evidence_ref: str | None = None
    license_id: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    evidence_url: str | None = None
    commercial_use: bool | None = None
    derivatives: bool | None = None
    share_alike: bool = False
    attribution_required: bool = False
    attribution_text: str | None = None
    audio_rights: str | None = None
    source_terms_ack: bool = False
    verified_source: bool = True
    retrieved_at: datetime = Field(default_factory=utc_now)


class AcquisitionSpec(BaseModel):
    kind: AcquisitionKind
    connector: str
    source_url: str
    canonical_url: str | None = None
    remote_id: str | None = None
    auth_mode: str = "none"
    resolver_version: str | None = None


class GateDecision(BaseModel):
    status: GateStatus
    reasons: list[str] = Field(default_factory=list)
    policy_version: str = "commercial-edited-video.v1"
    checked_at: datetime = Field(default_factory=utc_now)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str
    provider: str
    remote_id: str
    media_type: MediaType
    title: str
    description: str | None = None
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_url: str
    download_url: str | None = None
    preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    mime: str | None = None
    rights: RightsEvidence
    acquisition: AcquisitionSpec | None = None
    risk: RiskFlags = Field(default_factory=RiskFlags)
    gate: GateDecision | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=utc_now)


class FrameMetric(BaseModel):
    frame_index: int
    timestamp: float
    mean_luma: float
    contrast: float
    change_score: float
    is_keyframe: bool = False
    preview_path: str | None = None


class SemanticAnnotation(BaseModel):
    label: str
    value: Any
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str = "codex"
    note: str | None = None


class AssetManifest(BaseModel):
    schema_version: str = "asset-manifest.v1"
    asset_id: str
    candidate_id: str
    provider: str
    media_type: MediaType
    local_path: str
    sha256: str
    bytes: int
    mime: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    rights: RightsEvidence
    gate: GateDecision
    risk: RiskFlags = Field(default_factory=RiskFlags)
    technical: dict[str, Any] = Field(default_factory=dict)
    semantic: list[SemanticAnnotation] = Field(default_factory=list)
    lineage: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SearchRequest(BaseModel):
    query: str
    media_type: MediaType | None = None
    providers: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=100)
