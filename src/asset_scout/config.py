from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .models import UsageProfile

APP_DIR = ".asset-scout"


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    profile: UsageProfile = UsageProfile.COMMERCIAL_EDITED_VIDEO

    @property
    def state_dir(self) -> Path:
        return self.root / APP_DIR

    @property
    def database_path(self) -> Path:
        return self.state_dir / "catalog.sqlite3"

    @property
    def blobs_dir(self) -> Path:
        return self.state_dir / "blobs"

    @property
    def previews_dir(self) -> Path:
        return self.state_dir / "previews"

    @property
    def manifests_dir(self) -> Path:
        return self.state_dir / "manifests"

    @property
    def project_file(self) -> Path:
        return self.state_dir / "project.json"

    def ensure(self) -> None:
        for directory in (self.state_dir, self.blobs_dir, self.previews_dir, self.manifests_dir):
            directory.mkdir(parents=True, exist_ok=True)


def project_config(root: str | Path | None = None) -> ProjectConfig:
    selected = Path(root or os.environ.get("ASSET_SCOUT_PROJECT", Path.cwd())).expanduser().resolve()
    profile = os.environ.get("ASSET_SCOUT_PROFILE", UsageProfile.COMMERCIAL_EDITED_VIDEO.value)
    try:
        usage_profile = UsageProfile(profile)
    except ValueError:
        usage_profile = UsageProfile.COMMERCIAL_EDITED_VIDEO
    return ProjectConfig(selected, usage_profile)


def provider_credentials() -> dict[str, bool]:
    return {
        "wikimedia": True,
        "openverse": True,
        "pexels": bool(os.environ.get("PEXELS_API_KEY")),
        "pixabay": bool(os.environ.get("PIXABAY_API_KEY")),
    }


def accepted_terms(provider: str) -> bool:
    key = f"ASSET_SCOUT_ACCEPT_{provider.upper()}_TERMS"
    return os.environ.get(key, "").strip().lower() in {"1", "true", "yes"}

