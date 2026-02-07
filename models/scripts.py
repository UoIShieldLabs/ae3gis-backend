"""Pydantic models for script storage and push-and-run operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Script Storage Models (CRUD)
# -----------------------------------------------------------------------------


class ScriptCreateRequest(BaseModel):
    """Request body for creating/uploading a script."""

    name: str = Field(..., min_length=1, description="User-friendly name for the script.")
    description: str | None = Field(default=None, description="Optional description of what the script does.")
    content: str = Field(..., min_length=1, description="The script content (bash/shell code).")


class ScriptUpdateRequest(BaseModel):
    """Request body for updating a script."""

    name: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None)
    content: str | None = Field(default=None, min_length=1)

    def to_update_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.name is not None:
            payload["name"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        if self.content is not None:
            payload["content"] = self.content
        return payload


class ScriptSummary(BaseModel):
    """Lightweight representation for list responses (excludes content)."""

    id: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class ScriptDetail(BaseModel):
    """Full script record including content."""

    id: str
    name: str
    description: str | None = None
    content: str
    created_at: datetime
    updated_at: datetime


# -----------------------------------------------------------------------------
# Script Push Models (pushing scripts to GNS3 nodes)
# -----------------------------------------------------------------------------


class ScriptPushItem(BaseModel):
    """Item for pushing a stored script to a node."""

    node_name: str = Field(..., description="Name of the target node in GNS3.")
    script_id: str = Field(..., description="ID of the stored script to push.")
    remote_path: str = Field(..., description="Destination path on the node.")
    run_after_upload: bool = Field(default=False, description="Execute the script after upload.")
    executable: bool = Field(default=True, description="Set executable permission on the script.")
    overwrite: bool = Field(default=True, description="Overwrite if file exists on node.")
    run_timeout: float = Field(default=10.0, ge=0.0, description="Timeout for script execution.")
    shell: str = Field(default="sh", description="Shell used when executing the script after upload.")


class ScriptPushRequest(BaseModel):
    scripts: list[ScriptPushItem]
    gns3_server_ip: str = Field(..., description="GNS3 server IP address (for telnet console access).")
    concurrency: int = Field(default=5, ge=1, description="Maximum concurrent uploads.")


class ScriptUploadModel(BaseModel):
    node_name: str
    host: str
    port: int
    remote_path: str
    success: bool
    skipped: bool
    reason: str | None
    output: str
    error: str | None
    timestamp: float


class ScriptExecutionModel(BaseModel):
    node_name: str
    host: str
    port: int
    remote_path: str
    success: bool
    exit_code: int | None
    output: str
    error: str | None
    timestamp: float


class ScriptPushResultModel(BaseModel):
    upload: ScriptUploadModel
    execution: ScriptExecutionModel | None


class ScriptPushResponse(BaseModel):
    results: list[ScriptPushResultModel]


class ScriptRunItem(BaseModel):
    node_name: str
    remote_path: str
    shell: str = Field(default="sh", description="Shell used to execute the script.")
    timeout: float = Field(default=10.0, ge=0.0)


class ScriptRunRequest(BaseModel):
    runs: list[ScriptRunItem]
    gns3_server_ip: str = Field(..., description="GNS3 server IP address (for telnet console access).")
    concurrency: int = Field(default=5, ge=1)


class ScriptRunResponse(BaseModel):
    results: list[ScriptExecutionModel]
