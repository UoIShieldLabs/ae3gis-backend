"""Repository for submission persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from models.submissions import Submission, SubmissionSummary
from core.student_store import sanitize_student_name


class SubmissionRepository:
    """File-based repository for student submissions."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_student_dir(self, student_name: str) -> Path:
        """Get the directory for a student's submissions."""
        sanitized = sanitize_student_name(student_name)
        student_dir = self.storage_dir / sanitized
        student_dir.mkdir(parents=True, exist_ok=True)
        return student_dir

    def _get_submission_dir(self, student_name: str, submission_id: str) -> Path:
        """Get the directory for a specific submission."""
        return self._get_student_dir(student_name) / submission_id

    def create(
        self,
        student_name: str,
        display_name: str,
        project_name: str,
        it_logs: str,
        ot_logs: str
    ) -> Submission:
        """Create a new submission."""
        submission_id = str(uuid.uuid4())[:8]  # Short ID for readability
        submitted_at = datetime.utcnow()
        
        submission = Submission(
            id=submission_id,
            student_name=sanitize_student_name(student_name),
            display_name=display_name,
            submitted_at=submitted_at,
            project_name=project_name,
            it_logs=it_logs,
            ot_logs=ot_logs
        )
        
        # Create submission directory
        sub_dir = self._get_submission_dir(student_name, submission_id)
        sub_dir.mkdir(parents=True, exist_ok=True)
        
        # Save metadata
        metadata = {
            "id": submission.id,
            "student_name": submission.student_name,
            "display_name": submission.display_name,
            "submitted_at": submitted_at.isoformat(),
            "project_name": project_name,
        }
        with open(sub_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        # Save logs as separate files
        with open(sub_dir / "it_logs.txt", "w") as f:
            f.write(it_logs)
        with open(sub_dir / "ot_logs.txt", "w") as f:
            f.write(ot_logs)
        
        return submission

    def get(self, student_name: str, submission_id: str) -> Submission | None:
        """Get a specific submission."""
        sub_dir = self._get_submission_dir(student_name, submission_id)
        metadata_path = sub_dir / "metadata.json"
        
        if not metadata_path.exists():
            return None
        
        with open(metadata_path) as f:
            metadata = json.load(f)
        
        it_logs = ""
        ot_logs = ""
        it_path = sub_dir / "it_logs.txt"
        ot_path = sub_dir / "ot_logs.txt"
        
        if it_path.exists():
            with open(it_path) as f:
                it_logs = f.read()
        if ot_path.exists():
            with open(ot_path) as f:
                ot_logs = f.read()
        
        return Submission(
            id=metadata["id"],
            student_name=metadata["student_name"],
            display_name=metadata.get("display_name", metadata["student_name"]),
            submitted_at=datetime.fromisoformat(metadata["submitted_at"]),
            project_name=metadata["project_name"],
            it_logs=it_logs,
            ot_logs=ot_logs,
            ai_analysis=metadata.get("ai_analysis"),
            analyzed_at=datetime.fromisoformat(metadata["analyzed_at"]) if metadata.get("analyzed_at") else None,
            model_used=metadata.get("model_used"),
        )

    def save_analysis(
        self,
        student_name: str,
        submission_id: str,
        analysis: str,
        model_used: str,
    ) -> bool:
        """Save AI analysis to an existing submission.
        
        Returns True if successful, False if submission not found.
        """
        sub_dir = self._get_submission_dir(student_name, submission_id)
        metadata_path = sub_dir / "metadata.json"
        
        if not metadata_path.exists():
            return False
        
        with open(metadata_path) as f:
            metadata = json.load(f)
        
        # Update metadata with analysis
        metadata["ai_analysis"] = analysis
        metadata["analyzed_at"] = datetime.utcnow().isoformat()
        metadata["model_used"] = model_used
        
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        return True

    def list_for_student(self, student_name: str) -> list[SubmissionSummary]:
        """List all submissions for a student."""
        student_dir = self._get_student_dir(student_name)
        summaries = []
        
        for sub_dir in student_dir.iterdir():
            if not sub_dir.is_dir():
                continue
            metadata_path = sub_dir / "metadata.json"
            if not metadata_path.exists():
                continue
            
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
                
                it_lines = 0
                ot_lines = 0
                it_path = sub_dir / "it_logs.txt"
                ot_path = sub_dir / "ot_logs.txt"
                
                if it_path.exists():
                    with open(it_path) as f:
                        it_lines = len(f.readlines())
                if ot_path.exists():
                    with open(ot_path) as f:
                        ot_lines = len(f.readlines())
                
                summaries.append(SubmissionSummary(
                    id=metadata["id"],
                    student_name=metadata["student_name"],
                    display_name=metadata.get("display_name", metadata["student_name"]),
                    submitted_at=datetime.fromisoformat(metadata["submitted_at"]),
                    project_name=metadata["project_name"],
                    it_log_lines=it_lines,
                    ot_log_lines=ot_lines,
                    has_analysis=bool(metadata.get("ai_analysis")),
                ))
            except Exception:
                continue  # Skip invalid submissions
        
        # Sort by submission time, newest first
        summaries.sort(key=lambda s: s.submitted_at, reverse=True)
        return summaries

    def list_all(self) -> list[SubmissionSummary]:
        """List all submissions across all students."""
        all_summaries = []
        
        for student_dir in self.storage_dir.iterdir():
            if not student_dir.is_dir():
                continue
            # Use the directory name as student name
            student_name = student_dir.name
            summaries = self.list_for_student(student_name)
            all_summaries.extend(summaries)
        
        # Sort by submission time, newest first
        all_summaries.sort(key=lambda s: s.submitted_at, reverse=True)
        return all_summaries

    def count_by_student(self) -> dict[str, int]:
        """Get submission counts per student."""
        counts = {}
        for student_dir in self.storage_dir.iterdir():
            if not student_dir.is_dir():
                continue
            student_name = student_dir.name
            count = len(self.list_for_student(student_name))
            counts[student_name] = count
        return counts

    def delete(self, student_name: str, submission_id: str) -> bool:
        """Delete a specific submission."""
        sub_dir = self._get_submission_dir(student_name, submission_id)
        if not sub_dir.exists():
            return False
        
        # Remove all files in the submission directory
        for file in sub_dir.iterdir():
            file.unlink()
        sub_dir.rmdir()
        return True

    def delete_for_student(self, student_name: str) -> int:
        """Delete all submissions for a student."""
        student_dir = self._get_student_dir(student_name)
        count = 0
        
        for sub_dir in list(student_dir.iterdir()):
            if sub_dir.is_dir():
                for file in sub_dir.iterdir():
                    file.unlink()
                sub_dir.rmdir()
                count += 1
        
        return count

    def clear_all(self) -> int:
        """Delete all submissions for all students."""
        count = 0
        for student_dir in list(self.storage_dir.iterdir()):
            if student_dir.is_dir():
                count += self.delete_for_student(student_dir.name)
                # Try to remove the student directory if empty
                try:
                    student_dir.rmdir()
                except OSError:
                    pass  # Directory not empty
        return count


# Default instance using settings
def get_submission_repository() -> SubmissionRepository:
    """Get the default submission repository."""
    storage_dir = Path("./storage/submissions")
    return SubmissionRepository(storage_dir)
