from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .config import ProjectConfig
from .models import AssetManifest, Candidate, FrameMetric, GateDecision, SemanticAnnotation, utc_now

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS candidates (
  candidate_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  media_type TEXT NOT NULL,
  title TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  gate_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_provider ON candidates(provider);
CREATE VIRTUAL TABLE IF NOT EXISTS candidates_fts USING fts5(candidate_id UNINDEXED, title, description, tags);
CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  local_path TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id)
);
CREATE TABLE IF NOT EXISTS frame_metrics (
  asset_id TEXT NOT NULL,
  frame_index INTEGER NOT NULL,
  timestamp REAL NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(asset_id, frame_index),
  FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);
CREATE TABLE IF NOT EXISTS annotations (
  asset_id TEXT NOT NULL,
  label TEXT NOT NULL,
  value_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(asset_id) REFERENCES assets(asset_id)
);
CREATE TABLE IF NOT EXISTS reviews (
  candidate_id TEXT PRIMARY KEY,
  decision TEXT NOT NULL,
  reason TEXT,
  reviewer TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class Catalog:
    def __init__(self, config: ProjectConfig):
        self.config = config
        self.config.ensure()
        self.connection = sqlite3.connect(self.config.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def save_candidate(self, candidate: Candidate) -> None:
        now = utc_now().isoformat()
        payload = candidate.model_dump(mode="json")
        gate = candidate.gate.model_dump(mode="json") if candidate.gate else None
        self.connection.execute(
            """INSERT INTO candidates(candidate_id, provider, media_type, title, payload_json, gate_json, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(candidate_id) DO UPDATE SET provider=excluded.provider, media_type=excluded.media_type,
                 title=excluded.title, payload_json=excluded.payload_json, gate_json=excluded.gate_json, updated_at=excluded.updated_at""",
            (candidate.candidate_id, candidate.provider, candidate.media_type.value, candidate.title,
             json.dumps(payload, ensure_ascii=False), json.dumps(gate, ensure_ascii=False) if gate else None, now, now),
        )
        tags = " ".join(candidate.tags)
        description = candidate.description or ""
        self.connection.execute("DELETE FROM candidates_fts WHERE candidate_id = ?", (candidate.candidate_id,))
        self.connection.execute(
            "INSERT INTO candidates_fts(candidate_id, title, description, tags) VALUES(?,?,?,?)",
            (candidate.candidate_id, candidate.title, description, tags),
        )
        self.connection.commit()

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        row = self.connection.execute("SELECT payload_json FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not row:
            return None
        return Candidate.model_validate(json.loads(row["payload_json"]))

    def list_candidates(self, query: str | None = None, limit: int = 50) -> list[Candidate]:
        if query:
            tokens = [re.sub(r"[^\w-]", "", token) for token in query.split()]
            tokens = [token for token in tokens if token]
            if not tokens:
                return []
            fts_query = " AND ".join(f'"{token.replace(chr(34), " ")}"' for token in tokens)
            rows = self.connection.execute(
                "SELECT c.payload_json FROM candidates c JOIN candidates_fts f ON c.candidate_id=f.candidate_id WHERE candidates_fts MATCH ? LIMIT ?",
                (fts_query, limit),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT payload_json FROM candidates ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [Candidate.model_validate(json.loads(row["payload_json"])) for row in rows]

    def save_asset(self, manifest: AssetManifest) -> None:
        self.connection.execute(
            """INSERT INTO assets(asset_id, candidate_id, sha256, local_path, payload_json, created_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(asset_id) DO UPDATE SET local_path=excluded.local_path, payload_json=excluded.payload_json""",
            (manifest.asset_id, manifest.candidate_id, manifest.sha256, manifest.local_path,
             json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False), manifest.created_at.isoformat()),
        )
        self.connection.commit()

    def get_asset(self, asset_id: str) -> AssetManifest | None:
        row = self.connection.execute("SELECT payload_json FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        return AssetManifest.model_validate(json.loads(row["payload_json"])) if row else None

    def get_asset_by_sha256(self, sha256: str) -> AssetManifest | None:
        row = self.connection.execute("SELECT payload_json FROM assets WHERE sha256 = ?", (sha256,)).fetchone()
        return AssetManifest.model_validate(json.loads(row["payload_json"])) if row else None

    def list_assets(self) -> list[AssetManifest]:
        rows = self.connection.execute("SELECT payload_json FROM assets ORDER BY created_at").fetchall()
        return [AssetManifest.model_validate(json.loads(row["payload_json"])) for row in rows]

    def save_frames(self, asset_id: str, frames: Iterable[FrameMetric]) -> None:
        self.connection.executemany(
            "INSERT OR REPLACE INTO frame_metrics(asset_id, frame_index, timestamp, payload_json) VALUES(?,?,?,?)",
            [(asset_id, frame.frame_index, frame.timestamp, json.dumps(frame.model_dump(mode="json"), ensure_ascii=False)) for frame in frames],
        )
        self.connection.commit()

    def get_frames(self, asset_id: str, start: int = 0, end: int | None = None) -> list[FrameMetric]:
        if end is None:
            rows = self.connection.execute(
                "SELECT payload_json FROM frame_metrics WHERE asset_id=? AND frame_index>=? ORDER BY frame_index",
                (asset_id, start),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload_json FROM frame_metrics WHERE asset_id=? AND frame_index BETWEEN ? AND ? ORDER BY frame_index",
                (asset_id, start, end),
            ).fetchall()
        return [FrameMetric.model_validate(json.loads(row["payload_json"])) for row in rows]

    def save_annotations(self, asset_id: str, annotations: Iterable[SemanticAnnotation]) -> None:
        now = utc_now().isoformat()
        self.connection.executemany(
            "INSERT INTO annotations(asset_id, label, value_json, payload_json, created_at) VALUES(?,?,?,?,?)",
            [(asset_id, item.label, json.dumps(item.value, ensure_ascii=False), json.dumps(item.model_dump(mode="json"), ensure_ascii=False), now) for item in annotations],
        )
        self.connection.commit()

    def record_review(self, candidate_id: str, decision: GateDecision, reason: str, reviewer: str = "local-user") -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO reviews(candidate_id, decision, reason, reviewer, created_at) VALUES(?,?,?,?,?)",
            (candidate_id, decision.status.value, reason, reviewer, utc_now().isoformat()),
        )
        self.connection.commit()


def content_sha256(path: Path, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def cas_path(config: ProjectConfig, sha256: str) -> Path:
    destination = config.blobs_dir / sha256[:2] / sha256
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination
