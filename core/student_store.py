"""Repository for student session persistence."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from models.submissions import StudentSession, StudentSummary


def sanitize_student_name(name: str) -> str:
    """Convert student name to filesystem-safe format.
    
    Replaces spaces with underscores and removes special characters.
    """
    # Replace spaces with underscores
    sanitized = name.strip().replace(" ", "_")
    # Remove any characters that aren't alphanumeric, underscore, or hyphen
    sanitized = re.sub(r"[^\w\-]", "", sanitized)
    # Ensure not empty
    if not sanitized:
        raise ValueError("Student name cannot be empty or contain only special characters")
    return sanitized.lower()


def display_name_from_sanitized(sanitized: str) -> str:
    """Convert sanitized name back to display format.
    
    Replaces underscores with spaces and title-cases.
    """
    return sanitized.replace("_", " ").title()


class StudentRepository:
    """File-based repository for student sessions."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, student_name: str) -> Path:
        """Get the file path for a student's session."""
        sanitized = sanitize_student_name(student_name)
        return self.storage_dir / f"{sanitized}.json"

    def exists(self, student_name: str) -> bool:
        """Check if a student session exists."""
        return self._get_path(student_name).exists()

    def get(self, student_name: str) -> StudentSession | None:
        """Get a student's session, or None if not found."""
        path = self._get_path(student_name)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return StudentSession(**data)

    def save(self, session: StudentSession) -> StudentSession:
        """Save a student session."""
        path = self._get_path(session.name)
        data = session.model_dump(mode="json")
        # Ensure datetime is serialized properly
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        return session

    def delete(self, student_name: str) -> bool:
        """Delete a student session. Returns True if deleted, False if not found."""
        path = self._get_path(student_name)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> list[StudentSession]:
        """List all student sessions."""
        sessions = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                sessions.append(StudentSession(**data))
            except Exception:
                continue  # Skip invalid files
        return sessions

    def list_summaries(self, submission_counts: dict[str, int] | None = None) -> list[StudentSummary]:
        """List all students as summaries."""
        submission_counts = submission_counts or {}
        summaries = []
        for session in self.list_all():
            summaries.append(StudentSummary(
                name=session.name,
                display_name=session.display_name,
                created_at=session.created_at,
                project_name=session.project_name,
                has_active_session=True,
                submission_count=submission_counts.get(session.name, 0)
            ))
        return summaries

    def clear_all(self) -> int:
        """Delete all student sessions. Returns count of deleted sessions."""
        count = 0
        for path in self.storage_dir.glob("*.json"):
            path.unlink()
            count += 1
        return count


# Default instance using settings
def get_student_repository() -> StudentRepository:
    """Get the default student repository."""
    storage_dir = Path("./storage/students")
    return StudentRepository(storage_dir)
