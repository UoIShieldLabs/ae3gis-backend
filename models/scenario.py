"""Models for notebook-style scenarios with markdown and script steps."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class StepType(str, Enum):
    """Type of step in a scenario."""
    MARKDOWN = "markdown"
    SCRIPT = "script"


class MarkdownStep(BaseModel):
    """A markdown text step in the scenario."""

    type: Literal["markdown"] = Field(default="markdown", description="Step type identifier.")
    title: str | None = Field(default=None, description="Optional title for this step.")
    content: str = Field(..., min_length=1, description="Markdown content to display.")


class ScriptStep(BaseModel):
    """A script execution step in the scenario."""

    type: Literal["script"] = Field(default="script", description="Step type identifier.")
    title: str | None = Field(default=None, description="Optional title for this step.")
    script_name: str = Field(..., min_length=1, description="Human-readable name for the script.")
    script_content: str = Field(..., min_length=1, description="The script content (bash/shell code).")
    storage_path: str = Field(
        default="/tmp/script.sh",
        description="Path on the target node(s) where the script will be stored."
    )
    target_nodes: list[str] = Field(
        default_factory=list,
        description="List of node names to execute this script on. Empty means user must select."
    )
    shell: str = Field(default="sh", description="Shell used to execute the script.")
    timeout: float = Field(default=30.0, ge=0.0, description="Execution timeout in seconds.")
    run_after_upload: bool = Field(
        default=True,
        description="Whether to execute the script after uploading. Set to False to only upload without running (e.g., for config files, .st files, .py files)."
    )
    description: str | None = Field(default=None, description="Optional description of what this script does.")


# Union type for scenario steps
ScenarioStep = MarkdownStep | ScriptStep


class ScenarioCreateRequest(BaseModel):
    """Request body for creating a new notebook-style scenario."""

    name: str = Field(..., min_length=1, description="User-friendly name for the scenario.")
    description: str | None = Field(default=None, description="Optional description of the scenario.")
    project_name: str | None = Field(
        default=None,
        description="Default GNS3 project name to target. Can be changed when executing."
    )
    default_topology_id: str | None = Field(
        default=None,
        description="Optional ID of a recommended topology to deploy before running this scenario."
    )
    steps: list[ScenarioStep] = Field(
        default_factory=list,
        description="Ordered list of scenario steps (markdown text or scripts)."
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Optional tags for categorizing scenarios."
    )


class ScenarioUpdateRequest(BaseModel):
    """Request body for updating a scenario."""

    name: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None)
    project_name: str | None = Field(default=None)
    default_topology_id: str | None = Field(default=None)
    steps: list[ScenarioStep] | None = Field(default=None)
    tags: list[str] | None = Field(default=None)

    def to_update_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.name is not None:
            payload["name"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        if self.project_name is not None:
            payload["project_name"] = self.project_name
        if self.default_topology_id is not None:
            payload["default_topology_id"] = self.default_topology_id
        if self.steps is not None:
            payload["steps"] = [step.model_dump() for step in self.steps]
        if self.tags is not None:
            payload["tags"] = self.tags
        return payload


class ScenarioSummary(BaseModel):
    """Lightweight representation for list responses."""

    id: str
    name: str
    description: str | None = None
    project_name: str | None = None
    default_topology_id: str | None = Field(
        default=None,
        description="ID of the recommended topology to deploy before running this scenario."
    )
    step_count: int = Field(default=0, description="Number of steps in the scenario.")
    script_count: int = Field(default=0, description="Number of script steps.")
    markdown_count: int = Field(default=0, description="Number of markdown steps.")
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ScenarioDetail(BaseModel):
    """Full scenario record including all steps."""

    id: str
    name: str
    description: str | None = None
    project_name: str | None = None
    default_topology_id: str | None = Field(
        default=None,
        description="ID of the recommended topology to deploy before running this scenario."
    )
    steps: list[ScenarioStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# -----------------------------------------------------------------------------
# Script Execution Models (for ad-hoc script execution)
# -----------------------------------------------------------------------------


class ExecuteScriptRequest(BaseModel):
    """Request to execute a script on specific nodes."""

    gns3_server_ip: str = Field(..., description="GNS3 server IP address.")
    gns3_server_port: int = Field(default=80, description="GNS3 server port.")
    username: str = Field(default="gns3", description="GNS3 HTTP auth username.")
    password: str = Field(default="gns3", description="GNS3 HTTP auth password.")
    project_name: str = Field(..., description="GNS3 project name containing the nodes.")
    target_nodes: list[str] = Field(..., min_length=1, description="List of node names to execute on.")
    script_content: str = Field(..., min_length=1, description="The script content to execute.")
    storage_path: str = Field(default="/tmp/script.sh", description="Path to store the script on nodes.")
    shell: str = Field(default="sh", description="Shell to execute the script with.")
    timeout: float = Field(default=30.0, ge=0.0, description="Execution timeout in seconds.")
    run_after_upload: bool = Field(
        default=True,
        description="Whether to execute the script after uploading. Set to False to only upload without running (e.g., config files)."
    )


class NodeExecutionResult(BaseModel):
    """Result of script execution on a single node."""

    node_name: str
    success: bool
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None


class ExecuteScriptResponse(BaseModel):
    """Response from executing a script on nodes."""

    project_name: str
    script_storage_path: str
    total_nodes: int
    successful_nodes: int
    failed_nodes: int
    results: list[NodeExecutionResult]
