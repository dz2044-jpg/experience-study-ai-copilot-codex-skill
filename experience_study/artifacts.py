"""File-based workflow context, methodology log, and artifact manifest."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from experience_study.contracts import (
    AI_PACKET_FILENAME,
    ARTIFACT_MANIFEST_FILENAME,
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    METHODOLOGY_LOG_FILENAME,
    METHODOLOGY_LOG_SCHEMA_VERSION,
    PACKAGE_VERSION,
    PREPARED_DATASET_FILENAME,
    WORKFLOW_CONTEXT_FILENAME,
)


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_sha256(path: str | Path) -> str:
    """Return a file SHA256 digest."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_json_value(value: Any) -> Any:
    """Normalize values into stable JSON-compatible structures."""

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): normalize_json_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, set):
        return [normalize_json_value(item) for item in sorted(value, key=str)]
    return value


def stable_slug(columns: list[str] | tuple[str, ...]) -> str:
    """Return a deterministic artifact slug preserving column order."""

    parts: list[str] = []
    for column in columns:
        lowered = str(column).lower()
        slug = re.sub(r"[^a-z0-9]+", "_", lowered)
        slug = re.sub(r"_+", "_", slug).strip("_")
        if slug:
            parts.append(slug)
    return "_".join(parts) or "all"


@dataclass(slots=True)
class WorkflowContext:
    """File-based state index for a workflow run."""

    output_dir: Path
    source_data_path: Path | None = None
    prepared_data_path: Path | None = None
    latest_ae_path: Path | None = None
    latest_ae_paths_by_way: dict[int, Path] = field(default_factory=dict)
    latest_packet_path: Path | None = None
    artifact_manifest_path: Path | None = None
    methodology_log_path: Path | None = None
    state_fingerprint: str | None = None

    @property
    def context_path(self) -> Path:
        return self.output_dir / WORKFLOW_CONTEXT_FILENAME

    @property
    def artifacts_dir(self) -> Path:
        return self.output_dir / "artifacts"

    @property
    def ae_dir(self) -> Path:
        return self.artifacts_dir / "ae"

    @property
    def audit_dir(self) -> Path:
        return self.artifacts_dir / "audit"

    @property
    def ai_dir(self) -> Path:
        return self.artifacts_dir / "ai"

    @property
    def default_prepared_path(self) -> Path:
        return self.artifacts_dir / PREPARED_DATASET_FILENAME

    @property
    def default_methodology_log_path(self) -> Path:
        return self.audit_dir / METHODOLOGY_LOG_FILENAME

    @property
    def default_artifact_manifest_path(self) -> Path:
        return self.audit_dir / ARTIFACT_MANIFEST_FILENAME

    @property
    def default_packet_path(self) -> Path:
        return self.ai_dir / AI_PACKET_FILENAME

    def ae_summary_path(self, group_by: list[str]) -> Path:
        return self.ae_dir / f"ae_summary_by_{stable_slug(group_by)}.csv"

    def latest_way_path(self, way: int) -> Path:
        return self.ae_dir / f"latest_{way}way.csv"

    @property
    def latest_ae_alias_path(self) -> Path:
        return self.ae_dir / "latest.csv"

    def ensure_dirs(self) -> None:
        for directory in (self.artifacts_dir, self.ae_dir, self.audit_dir, self.ai_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source_data_path": str(self.source_data_path) if self.source_data_path else None,
            "prepared_data_path": str(self.prepared_data_path) if self.prepared_data_path else None,
            "latest_ae_path": str(self.latest_ae_path) if self.latest_ae_path else None,
            "latest_ae_paths_by_way": {
                str(way): str(path) for way, path in sorted(self.latest_ae_paths_by_way.items())
            },
            "latest_packet_path": str(self.latest_packet_path) if self.latest_packet_path else None,
            "artifact_manifest_path": (
                str(self.artifact_manifest_path) if self.artifact_manifest_path else None
            ),
            "methodology_log_path": (
                str(self.methodology_log_path) if self.methodology_log_path else None
            ),
            "state_fingerprint": self.state_fingerprint,
        }

    def write(self) -> Path:
        self.ensure_dirs()
        self.context_path.write_text(
            json.dumps(self.to_json_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.context_path

    def readiness(self) -> dict[str, bool]:
        return {
            "source_data": bool(self.source_data_path and self.source_data_path.exists()),
            "prepared_data": bool(self.prepared_data_path and self.prepared_data_path.exists()),
            "latest_ae": bool(self.latest_ae_path and self.latest_ae_path.exists()),
            "latest_packet": bool(self.latest_packet_path and self.latest_packet_path.exists()),
            "artifact_manifest": bool(
                self.artifact_manifest_path and self.artifact_manifest_path.exists()
            ),
            "methodology_log": bool(self.methodology_log_path and self.methodology_log_path.exists()),
        }


@dataclass(slots=True)
class MethodologyEvent:
    """One deterministic methodology event."""

    step_name: str
    tool_name: str
    input_path: str | None
    output_path: str | None
    parameters: dict[str, Any]
    timestamp: str = field(default_factory=utc_timestamp)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_context(output_dir: str | Path) -> WorkflowContext:
    """Load workflow context, reconstructing from the manifest when needed."""

    root = Path(output_dir)
    context = WorkflowContext(output_dir=root)
    context_path = root / WORKFLOW_CONTEXT_FILENAME
    if context_path.exists():
        payload = json.loads(context_path.read_text(encoding="utf-8"))
        context.source_data_path = _optional_path(payload.get("source_data_path"))
        context.prepared_data_path = _optional_path(payload.get("prepared_data_path"))
        context.latest_ae_path = _optional_path(payload.get("latest_ae_path"))
        context.latest_packet_path = _optional_path(payload.get("latest_packet_path"))
        context.artifact_manifest_path = _optional_path(payload.get("artifact_manifest_path"))
        context.methodology_log_path = _optional_path(payload.get("methodology_log_path"))
        context.state_fingerprint = payload.get("state_fingerprint")
        paths_by_way = payload.get("latest_ae_paths_by_way") or {}
        context.latest_ae_paths_by_way = {
            int(way): Path(path) for way, path in paths_by_way.items() if path
        }
        return context

    return reconstruct_context_from_manifest(context)


def _optional_path(value: Any) -> Path | None:
    return Path(value) if value else None


def read_methodology_log(path: str | Path) -> dict[str, Any]:
    log_path = Path(path)
    if not log_path.exists():
        return {"schema_version": METHODOLOGY_LOG_SCHEMA_VERSION, "events": []}
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != METHODOLOGY_LOG_SCHEMA_VERSION:
        raise ValueError(f"Unsupported methodology log schema: {payload.get('schema_version')!r}")
    if not isinstance(payload.get("events"), list):
        raise ValueError("Methodology log must contain an events list.")
    return payload


def append_methodology_event(path: str | Path, event: MethodologyEvent) -> Path:
    log_path = Path(path)
    payload = read_methodology_log(log_path)
    payload["events"].append(event.to_dict())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return log_path


def read_artifact_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {
            "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
            "generated_at": utc_timestamp(),
            "entries": [],
        }
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ARTIFACT_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported artifact manifest schema: {payload.get('schema_version')!r}")
    if not isinstance(payload.get("entries"), list):
        raise ValueError("Artifact manifest must contain an entries list.")
    return payload


def write_artifact_manifest(path: str | Path, payload: dict[str, Any]) -> Path:
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload["generated_at"] = utc_timestamp()
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def upsert_artifact_entry(
    manifest_path: str | Path,
    *,
    artifact_type: str,
    path: str | Path,
    generating_tool: str,
    parameters: dict[str, Any],
    source_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = read_artifact_manifest(manifest_path)
    artifact_path = Path(path)
    normalized_path = str(artifact_path)
    existing = next(
        (
            entry
            for entry in payload["entries"]
            if entry.get("artifact_type") == artifact_type and entry.get("path") == normalized_path
        ),
        None,
    )
    now = utc_timestamp()
    entry = {
        "artifact_type": artifact_type,
        "path": normalized_path,
        "created_timestamp": existing.get("created_timestamp") if existing else now,
        "updated_timestamp": now,
        "content_hash": file_sha256(artifact_path),
        "source_artifacts": normalize_json_value(source_artifacts or []),
        "generating_tool": generating_tool,
        "parameters": normalize_json_value(parameters),
    }
    if existing:
        payload["entries"][payload["entries"].index(existing)] = entry
    else:
        payload["entries"].append(entry)
    payload["entries"] = sorted(
        payload["entries"],
        key=lambda item: (str(item.get("artifact_type")), str(item.get("path"))),
    )
    write_artifact_manifest(manifest_path, payload)
    return entry


def source_artifact(artifact_type: str, path: str | Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    artifact_path = Path(path)
    if not artifact_path.exists():
        return []
    return [
        {
            "artifact_type": artifact_type,
            "path": str(artifact_path),
            "content_hash": file_sha256(artifact_path),
        }
    ]


def build_state_fingerprint(
    *,
    source_hashes: dict[str, str | None],
    group_by: list[str],
    filters: list[dict[str, Any]],
    measure: str,
    min_claims: int,
    sort_by: str,
) -> tuple[str, dict[str, Any]]:
    payload = normalize_json_value(
        {
            "source_hashes": source_hashes,
            "group_by": group_by,
            "filters": filters,
            "measure": measure,
            "min_claims": min_claims,
            "sort_by": sort_by,
            "packet_schema_version": "ai_ae_packet.v1",
            "package_version": PACKAGE_VERSION,
        }
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def update_manifest_fingerprint(
    manifest_path: str | Path,
    *,
    fingerprint: str,
    fingerprint_inputs: dict[str, Any],
) -> None:
    payload = read_artifact_manifest(manifest_path)
    payload["state_fingerprint"] = fingerprint
    payload["fingerprint_inputs"] = normalize_json_value(fingerprint_inputs)
    write_artifact_manifest(manifest_path, payload)


def artifact_entry(manifest: dict[str, Any], artifact_type: str) -> dict[str, Any] | None:
    entries = [entry for entry in manifest.get("entries", []) if entry.get("artifact_type") == artifact_type]
    return entries[-1] if entries else None


def reconstruct_context_from_manifest(context: WorkflowContext) -> WorkflowContext:
    manifest_path = context.default_artifact_manifest_path
    if not manifest_path.exists():
        context.artifact_manifest_path = manifest_path if manifest_path.exists() else None
        context.methodology_log_path = (
            context.default_methodology_log_path
            if context.default_methodology_log_path.exists()
            else None
        )
        return context
    manifest = read_artifact_manifest(manifest_path)
    context.artifact_manifest_path = manifest_path
    context.methodology_log_path = (
        context.default_methodology_log_path
        if context.default_methodology_log_path.exists()
        else None
    )
    for artifact_type, attr in (
        ("source_dataset", "source_data_path"),
        ("prepared_dataset", "prepared_data_path"),
        ("latest_ae_summary", "latest_ae_path"),
        ("ai_ae_packet", "latest_packet_path"),
    ):
        entry = artifact_entry(manifest, artifact_type)
        if entry and entry.get("path"):
            setattr(context, attr, Path(entry["path"]))
    for entry in manifest.get("entries", []):
        if entry.get("artifact_type") != "latest_ae_summary_by_way":
            continue
        way = entry.get("parameters", {}).get("way")
        if way and entry.get("path"):
            context.latest_ae_paths_by_way[int(way)] = Path(entry["path"])
    context.state_fingerprint = manifest.get("state_fingerprint")
    return context
