"""File-based persistence for script definitions."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


class ScriptNotFoundError(LookupError):
    """Raised when a script record cannot be located."""


class ScriptRepository:
    """Persist script records as individual JSON files."""

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, script_id: str) -> Path:
        return self._storage_dir / f"{script_id}.json"

    @staticmethod
    def _timestamp() -> str:
        return datetime.utcnow().isoformat(timespec="seconds") + "Z"

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _dump(path: Path, payload: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new script record."""
        script_id = str(uuid4())
        now = self._timestamp()
        payload = {
            "id": script_id,
            "name": data["name"],
            "description": data.get("description"),
            "content": data["content"],
            "created_at": now,
            "updated_at": now,
        }
        self._dump(self._path_for(script_id), payload)
        return dict(payload)

    def list_all(self) -> list[dict[str, Any]]:
        """List all scripts, sorted by modification time (newest first)."""
        records = []
        for path in sorted(self._storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            records.append(self._load(path))
        return records

    def get(self, script_id: str) -> dict[str, Any]:
        """Retrieve a script by ID."""
        path = self._path_for(script_id)
        if not path.exists():
            raise ScriptNotFoundError(script_id)
        return self._load(path)

    def update(self, script_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a script's metadata or content."""
        path = self._path_for(script_id)
        if not path.exists():
            raise ScriptNotFoundError(script_id)
        payload = self._load(path)
        payload.update({k: v for k, v in updates.items() if k in {"name", "description", "content"}})
        payload["updated_at"] = self._timestamp()
        self._dump(path, payload)
        return payload

    def delete(self, script_id: str) -> None:
        """Delete a script by ID."""
        path = self._path_for(script_id)
        if not path.exists():
            raise ScriptNotFoundError(script_id)
        path.unlink()

    def get_content(self, script_id: str) -> str:
        """Retrieve only the script content by ID."""
        record = self.get(script_id)
        return record["content"]
