"""Typed models for scenario structure with embedded scripts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EmbeddedScript(BaseModel):
    """A script embedded directly in the scenario (not referenced by ID)."""

    name: str = Field(..., min_length=1, description="Human-readable name for the script.")
    content: str = Field(..., min_length=1, description="The script content (bash/shell code).")
    remote_path: str = Field(
        default="/tmp/script.sh",
        description="Destination path on the node where the script will be saved."
    )
    priority: int = Field(
        default=10,
        ge=1,
        description="Execution priority. Lower values run first (e.g., servers=1, clients=10)."
    )
    shell: str = Field(default="sh", description="Shell used to execute the script.")
    timeout: float = Field(default=30.0, ge=0.0, description="Execution timeout in seconds.")


class LinkEndpoint(BaseModel):
    """One endpoint of a network link."""

    name: str = Field(..., description="Node name (resolved to node_id during build).")
    adapter_number: int = Field(default=0, ge=0, description="Adapter/interface number on the node.")
    port_number: int = Field(default=0, ge=0, description="Port number on the adapter.")


class ScenarioLink(BaseModel):
    """A network link connecting two nodes."""

    nodes: tuple[LinkEndpoint, LinkEndpoint] = Field(
        ..., 
        description="The two endpoints of this link."
    )


class ScenarioNode(BaseModel):
    """A node in the scenario with optional embedded scripts."""

    name: str = Field(..., min_length=1, description="Unique name for this node in the scenario.")
    template_id: str | None = Field(
        default=None,
        description="Direct GNS3 template UUID. Use one of template_id/template_key/template_name."
    )
    template_key: str | None = Field(
        default=None,
        description="Key referencing the templates map in the scenario."
    )
    template_name: str | None = Field(
        default=None,
        description="Template name as it appears on the GNS3 server."
    )
    x: int = Field(default=0, description="X position in the GNS3 canvas.")
    y: int = Field(default=0, description="Y position in the GNS3 canvas.")
    layer: str | None = Field(
        default=None,
        description="Layer/zone this node belongs to (e.g., 'IT', 'DMZ', 'OT', 'Field'). For frontend visualization."
    )
    parent_name: str | None = Field(
        default=None,
        description="Name of parent node for hierarchy visualization. Null for top-level nodes."
    )
    scripts: list[EmbeddedScript] = Field(
        default_factory=list,
        description="Scripts to execute on this node after deployment, in priority order."
    )


class ScenarioDefinition(BaseModel):
    """The complete scenario definition including topology and scripts."""

    gns3_server_ip: str | None = Field(
        default=None,
        description="Default GNS3 server IP. Can be overridden during deployment."
    )
    project_name: str | None = Field(
        default=None,
        description="GNS3 project name. Required if project_id is not provided."
    )
    project_id: str | None = Field(
        default=None,
        description="GNS3 project UUID. Required if project_name is not provided."
    )
    templates: dict[str, str] = Field(
        default_factory=dict,
        description="Map of template keys to template UUIDs for easy reference."
    )
    nodes: list[ScenarioNode] = Field(
        default_factory=list,
        description="List of nodes to create in the scenario."
    )
    links: list[ScenarioLink] = Field(
        default_factory=list,
        description="List of links connecting nodes."
    )


# -----------------------------------------------------------------------------
# Scenario CRUD Models
# -----------------------------------------------------------------------------


class ScenarioCreateRequest(BaseModel):
    """Request body for creating a new scenario."""

    name: str = Field(..., min_length=1, description="User-friendly name for the scenario.")
    description: str | None = Field(default=None, description="Optional description of the scenario.")
    definition: ScenarioDefinition = Field(..., description="The complete scenario definition.")


class ScenarioUpdateRequest(BaseModel):
    """Request body for updating a scenario."""

    name: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None)
    definition: ScenarioDefinition | None = Field(default=None)

    def to_update_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.name is not None:
            payload["name"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        if self.definition is not None:
            payload["definition"] = self.definition.model_dump()
        return payload


class ScenarioSummary(BaseModel):
    """Lightweight representation for list responses."""

    id: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class ScenarioDetail(BaseModel):
    """Full scenario record including definition."""

    id: str
    name: str
    description: str | None = None
    definition: ScenarioDefinition
    created_at: datetime
    updated_at: datetime


# -----------------------------------------------------------------------------
# Scenario Deployment Models
# -----------------------------------------------------------------------------


class ScenarioDeployRequest(BaseModel):
    """Request body for deploying a scenario to a student's GNS3 server."""

    gns3_server_ip: str = Field(..., description="Student's GNS3 server IP address.")
    gns3_server_port: int = Field(default=80, description="GNS3 server port.")
    username: str = Field(default="gns3", description="GNS3 HTTP auth username.")
    password: str = Field(default="gns3", description="GNS3 HTTP auth password.")
    project_name: str | None = Field(
        default=None,
        description="Override project name. Defaults to scenario's project_name."
    )
    start_nodes: bool = Field(default=True, description="Start nodes after creation.")
    run_scripts: bool = Field(default=True, description="Execute embedded scripts after starting nodes.")
    priority_delay: float = Field(
        default=0.5,
        ge=0.0,
        description="Delay in seconds between different priority groups. Scripts within the same priority run concurrently."
    )
    definition: ScenarioDefinition | None = Field(
        default=None,
        description="Optional scenario definition. If provided, deploys this instead of stored scenario."
    )


class ScriptExecutionSummary(BaseModel):
    """Summary of a single script execution."""

    node_name: str
    script_name: str
    priority: int
    remote_path: str
    success: bool
    error: str | None = None


class ScenarioDeployResponse(BaseModel):
    """Response from deploying a scenario."""

    scenario_id: str | None = Field(default=None, description="Scenario ID if deployed from stored scenario.")
    scenario_name: str | None = Field(default=None, description="Scenario name if deployed from stored scenario.")
    project_id: str
    project_name: str | None
    gns3_server_ip: str
    nodes_created: int
    links_created: int
    scripts_executed: list[ScriptExecutionSummary]
    success: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings during deployment.")


class DeleteNodesRequest(BaseModel):
    """Request body for deleting all nodes in a GNS3 project."""

    gns3_server_ip: str = Field(..., description="GNS3 server IP address.")
    gns3_server_port: int = Field(default=80, description="GNS3 server port.")
    username: str = Field(default="gns3", description="GNS3 HTTP auth username.")
    password: str = Field(default="gns3", description="GNS3 HTTP auth password.")


class DeleteNodesResponse(BaseModel):
    """Response from deleting nodes in a GNS3 project."""

    project_id: str
    nodes_deleted: int
    links_deleted: int
    success: bool
    errors: list[str] = Field(default_factory=list)
