from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from claude_code_thy.settings import FileHistorySettings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class FileSnapshot:
    file_path: str
    snapshot_path: str
    content_hash: str
    created_at: str = field(default_factory=_utc_now)


class FileHistoryStore:
    def __init__(self, workspace_root: Path, settings: FileHistorySettings) -> None:
        self.workspace_root = workspace_root
        self.settings = settings
        self.history_root = (workspace_root / settings.history_dir).resolve()
        if settings.enabled:
            self.history_root.mkdir(parents=True, exist_ok=True)

    def snapshot(self, file_path: Path, content: str) -> FileSnapshot | None:
        if not self.settings.enabled:
            return None

        relative = self._relative_label(file_path)
        target_dir = self.history_root / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        snapshot_path = target_dir / f"{_utc_now().replace(':', '-')}-{content_hash[:8]}.bak"
        snapshot_path.write_text(content, encoding="utf-8")

        snapshot = FileSnapshot(
            file_path=str(file_path),
            snapshot_path=str(snapshot_path),
            content_hash=content_hash,
        )
        self._write_manifest(target_dir, snapshot)
        self._trim(target_dir)
        return snapshot

    def _relative_label(self, file_path: Path) -> Path:
        try:
            relative = file_path.resolve().relative_to(self.workspace_root.resolve())
        except ValueError:
            relative = Path("_external") / file_path.name
        return relative

    def _write_manifest(self, target_dir: Path, snapshot: FileSnapshot) -> None:
        manifest_path = target_dir / "manifest.jsonl"
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(snapshot), ensure_ascii=False) + "\n")

    def _trim(self, target_dir: Path) -> None:
        snapshots = sorted(
            (path for path in target_dir.glob("*.bak") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in snapshots[self.settings.max_snapshots_per_file :]:
            stale.unlink(missing_ok=True)
