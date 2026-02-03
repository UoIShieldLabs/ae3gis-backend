"""Routes for managing notebook-style scenarios (markdown + script steps)."""

from __future__ import annotations

import asyncio
from typing import Any, MutableMapping

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from core.gns3_client import GNS3Client, GNS3APIError
from core.new_scenario_store import ScenarioNotFoundError, ScenarioRepository
from core.script_pusher import ScriptPusher, ScriptSpec
from models.scenario import (
    ExecuteScriptRequest,
    ExecuteScriptResponse,
    NodeExecutionResult,
    ScenarioCreateRequest,
    ScenarioDetail,
    ScenarioSummary,
    ScenarioUpdateRequest,
)

from ..dependencies import get_new_scenario_repository, get_script_pusher

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


# -----------------------------------------------------------------------------
# Scenario CRUD Endpoints (for instructors)
# -----------------------------------------------------------------------------


@router.post("/", response_model=ScenarioDetail, status_code=status.HTTP_201_CREATED)
def create_scenario(
    payload: ScenarioCreateRequest,
    repository: ScenarioRepository = Depends(get_new_scenario_repository),
) -> ScenarioDetail:
    """
    Create a new notebook-style scenario.
    
    A scenario consists of ordered steps that can be:
    - **markdown**: Text content for instructions, documentation, or explanations
    - **script**: Shell scripts to execute on target nodes
    
    This endpoint is intended for instructors to create educational scenarios.
    """
    data = {
        "name": payload.name,
        "description": payload.description,
        "project_name": payload.project_name,
        "default_topology_id": payload.default_topology_id,
        "steps": [step.model_dump() for step in payload.steps],
        "tags": payload.tags,
    }
    record = repository.create(data)
    return ScenarioDetail.model_validate(record)


@router.get("/", response_model=list[ScenarioSummary])
def list_scenarios(
    tag: str | None = Query(default=None, description="Filter by tag"),
    repository: ScenarioRepository = Depends(get_new_scenario_repository),
) -> list[ScenarioSummary]:
    """
    List all stored scenarios.
    
    Optionally filter by tag. Returns summary information without full step content.
    """
    records = repository.list_all()
    
    # Filter by tag if provided
    if tag:
        records = [r for r in records if tag in r.get("tags", [])]
    
    return [ScenarioSummary.model_validate(record) for record in records]


@router.get("/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(
    scenario_id: str,
    repository: ScenarioRepository = Depends(get_new_scenario_repository),
) -> ScenarioDetail:
    """
    Retrieve a scenario by ID with full step content.
    
    Students use this to load a scenario for viewing/executing.
    The response includes all steps with their complete content.
    """
    try:
        record = repository.get(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    return ScenarioDetail.model_validate(record)


@router.patch("/{scenario_id}", response_model=ScenarioDetail)
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdateRequest,
    repository: ScenarioRepository = Depends(get_new_scenario_repository),
) -> ScenarioDetail:
    """
    Update a scenario's metadata or steps (instructor use).
    
    Partial updates are supported - only provided fields will be updated.
    """
    updates = payload.to_update_dict()
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    try:
        record = repository.update(scenario_id, updates)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    return ScenarioDetail.model_validate(record)


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(
    scenario_id: str,
    repository: ScenarioRepository = Depends(get_new_scenario_repository),
) -> Response:
    """Delete a scenario by ID (instructor use)."""
    try:
        repository.delete(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------------------------------------------------------
# Script Execution Endpoint (for executing script steps)
# -----------------------------------------------------------------------------


async def _execute_on_node(
    node_name: str,
    node_info: MutableMapping[str, Any],
    script_content: str,
    storage_path: str,
    shell: str,
    timeout: float,
    server_ip: str,
    pusher: ScriptPusher,
    semaphore: asyncio.Semaphore,
) -> NodeExecutionResult:
    """Execute a script on a single node."""
    async with semaphore:
        # Get console info
        console_port = node_info.get("console")
        console_type = node_info.get("console_type", "telnet")
        
        if not console_port or console_type != "telnet":
            return NodeExecutionResult(
                node_name=node_name,
                success=False,
                error=f"Node '{node_name}' does not have a telnet console (type: {console_type})",
            )
        
        # GNS3 often returns "0.0.0.0" as console_host which means "all interfaces"
        # We need to use the actual GNS3 server IP to connect from outside
        console_host = node_info.get("console_host", "")
        if not console_host or console_host in ("0.0.0.0", "::"):
            host = server_ip
        else:
            host = console_host
        
        spec = ScriptSpec(
            remote_path=storage_path,
            content=script_content,
            run_after_upload=True,
            executable=True,
            overwrite=True,
            run_timeout=timeout,
            shell=shell,
        )
        
        try:
            result = await pusher.push(node_name, host, console_port, spec)
            
            success = result.upload.success
            output = result.upload.output
            error = result.upload.error or result.upload.reason
            exit_code = None
            
            if result.execution:
                success = success and result.execution.success
                output = result.execution.output or output
                if not result.execution.success:
                    error = result.execution.error
                exit_code = result.execution.exit_code
            
            return NodeExecutionResult(
                node_name=node_name,
                success=success,
                output=output,
                error=error if not success else None,
                exit_code=exit_code,
            )
        except Exception as exc:
            return NodeExecutionResult(
                node_name=node_name,
                success=False,
                error=str(exc),
            )


@router.post("/execute", response_model=ExecuteScriptResponse)
async def execute_script(
    payload: ExecuteScriptRequest,
    pusher: ScriptPusher = Depends(get_script_pusher),
) -> ExecuteScriptResponse:
    """
    Execute a script on one or more nodes in a GNS3 project.
    
    This endpoint:
    1. Connects to the GNS3 server
    2. Finds the specified nodes by name
    3. Uploads the script content to each node
    4. Executes the script on each node
    5. Returns the results for all nodes
    
    The script content is sent directly - this allows students or instructors
    to modify the script before execution without saving to storage.
    
    Use this endpoint for executing script steps from scenarios.
    """
    base_url = f"http://{payload.gns3_server_ip}:{payload.gns3_server_port}"
    
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    session.auth = (payload.username, payload.password)
    
    client = GNS3Client(base_url=base_url, session=session)
    
    try:
        # Find project ID
        project_id = await asyncio.to_thread(client.find_project_id, payload.project_name)
        
        # Get all nodes
        raw_nodes = await asyncio.to_thread(client.list_nodes, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GNS3APIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to GNS3 server: {exc}") from exc
    finally:
        session.close()
    
    # Build node name -> node info mapping
    node_map: dict[str, MutableMapping[str, Any]] = {
        node.get("name", ""): node for node in raw_nodes
    }
    
    # Validate all target nodes exist
    missing_nodes = [name for name in payload.target_nodes if name not in node_map]
    if missing_nodes:
        raise HTTPException(
            status_code=404,
            detail=f"Nodes not found: {', '.join(missing_nodes)}"
        )
    
    # Execute on all target nodes concurrently
    semaphore = asyncio.Semaphore(8)  # Limit concurrent connections
    tasks = [
        _execute_on_node(
            node_name=node_name,
            node_info=node_map[node_name],
            script_content=payload.script_content,
            storage_path=payload.storage_path,
            shell=payload.shell,
            timeout=payload.timeout,
            server_ip=payload.gns3_server_ip,
            pusher=pusher,
            semaphore=semaphore,
        )
        for node_name in payload.target_nodes
    ]
    
    results = await asyncio.gather(*tasks)
    
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful
    
    return ExecuteScriptResponse(
        project_name=payload.project_name,
        script_storage_path=payload.storage_path,
        total_nodes=len(results),
        successful_nodes=successful,
        failed_nodes=failed,
        results=list(results),
    )
