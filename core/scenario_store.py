"""File-based persistence for scenario definitions."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


class ScenarioNotFoundError(LookupError):
    """Raised when a scenario record cannot be located."""


class ScenarioRepository:
    """Persist scenario records as individual JSON files."""

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, scenario_id: str) -> Path:
        return self._storage_dir / f"{scenario_id}.json"

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
            json.dump(payload, handle, indent=2, sort_keys=False)
            handle.write("\n")

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new scenario record."""
        scenario_id = str(uuid4())
        now = self._timestamp()
        payload = {
            "id": scenario_id,
            "name": data["name"],
            "description": data.get("description"),
            "definition": data["definition"],
            "created_at": now,
            "updated_at": now,
        }
        self._dump(self._path_for(scenario_id), payload)
        return dict(payload)

    def list_all(self) -> list[dict[str, Any]]:
        """List all scenarios, sorted by modification time (newest first)."""
        records = []
        for path in sorted(self._storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            records.append(self._load(path))
        return records

    def get(self, scenario_id: str) -> dict[str, Any]:
        """Retrieve a scenario by ID."""
        path = self._path_for(scenario_id)
        if not path.exists():
            raise ScenarioNotFoundError(scenario_id)
        return self._load(path)

    def update(self, scenario_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a scenario's metadata or definition."""
        path = self._path_for(scenario_id)
        if not path.exists():
            raise ScenarioNotFoundError(scenario_id)
        payload = self._load(path)
        for key in ("name", "description", "definition"):
            if key in updates:
                payload[key] = updates[key]
        payload["updated_at"] = self._timestamp()
        self._dump(path, payload)
        return payload

    def delete(self, scenario_id: str) -> None:
        """Delete a scenario by ID."""
        path = self._path_for(scenario_id)
        if not path.exists():
            raise ScenarioNotFoundError(scenario_id)
        path.unlink()
