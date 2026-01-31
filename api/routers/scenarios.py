"""Routes for managing and deploying scenarios."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, MutableMapping

import requests
from fastapi import APIRouter, Depends, HTTPException, Response, status

from core.config_store import ConfigStore
from core.gns3_client import GNS3Client, GNS3APIError
from core.nodes import find_node_by_name, resolve_console_target
from core.scenario_builder import ScenarioBuilder
from core.scenario_store import ScenarioNotFoundError, ScenarioRepository
from core.script_pusher import ScriptPusher, ScriptSpec
from models.scenario_types import (
    ScenarioCreateRequest,
    ScenarioDefinition,
    ScenarioDeployRequest,
    ScenarioDeployResponse,
    ScenarioDetail,
    ScenarioSummary,
    ScenarioUpdateRequest,
    ScriptExecutionSummary,
    DeleteNodesRequest,
    DeleteNodesResponse,
)
from models import APISettings

from ..dependencies import get_scenario_repository, get_script_pusher, get_settings

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


# -----------------------------------------------------------------------------
# Scenario CRUD Endpoints
# -----------------------------------------------------------------------------


@router.post("/", response_model=ScenarioDetail, status_code=status.HTTP_201_CREATED)
def create_scenario(
    payload: ScenarioCreateRequest,
    repository: ScenarioRepository = Depends(get_scenario_repository),
) -> ScenarioDetail:
    """Create a new scenario (instructor use)."""
    data = {
        "name": payload.name,
        "description": payload.description,
        "definition": payload.definition.model_dump(),
    }
    record = repository.create(data)
    return ScenarioDetail.model_validate(record)


@router.get("/", response_model=list[ScenarioSummary])
def list_scenarios(
    repository: ScenarioRepository = Depends(get_scenario_repository),
) -> list[ScenarioSummary]:
    """List all stored scenarios."""
    records = repository.list_all()
    return [ScenarioSummary.model_validate(record) for record in records]


@router.get("/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(
    scenario_id: str,
    repository: ScenarioRepository = Depends(get_scenario_repository),
) -> ScenarioDetail:
    """Retrieve a scenario by ID."""
    try:
        record = repository.get(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    return ScenarioDetail.model_validate(record)


@router.patch("/{scenario_id}", response_model=ScenarioDetail)
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdateRequest,
    repository: ScenarioRepository = Depends(get_scenario_repository),
) -> ScenarioDetail:
    """Update a scenario's metadata or definition (instructor use)."""
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
    repository: ScenarioRepository = Depends(get_scenario_repository),
) -> Response:
    """Delete a scenario by ID (instructor use)."""
    try:
        repository.delete(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------------------------------------------------------
# Scenario Deployment Endpoint
# -----------------------------------------------------------------------------

# Concurrency limit for parallel operations
MAX_CONCURRENT_SCRIPTS = 8


async def _execute_single_script(
    node_name: str,
    script: Any,
    config_record: MutableMapping[str, Any],
    gns3_server_ip: str,
    pusher: ScriptPusher,
    semaphore: asyncio.Semaphore,
) -> ScriptExecutionSummary:
    """Execute a single script on a node."""
    async with semaphore:
        # Find node in config to get console info
        node = find_node_by_name(config_record, node_name)
        if node is None:
            return ScriptExecutionSummary(
                node_name=node_name,
                script_name=script.name,
                priority=script.priority,
                remote_path=script.remote_path,
                success=False,
                error=f"Node '{node_name}' not found in config",
            )
        
        target = resolve_console_target(node, gns3_server_ip)
        if target is None:
            return ScriptExecutionSummary(
                node_name=node_name,
                script_name=script.name,
                priority=script.priority,
                remote_path=script.remote_path,
                success=False,
                error=f"Node '{node_name}' does not expose a telnet console",
            )
        
        host, port = target
        
        # Create spec with embedded content
        spec = ScriptSpec(
            remote_path=script.remote_path,
            content=script.content,
            run_after_upload=True,
            executable=True,
            overwrite=True,
            run_timeout=script.timeout,
            shell=script.shell,
        )
        
        try:
            push_result = await pusher.push(node_name, host, port, spec)
            success = push_result.upload.success and (
                push_result.execution.success if push_result.execution else False
            )
            error = None
            if not push_result.upload.success:
                error = push_result.upload.error or push_result.upload.reason
            elif push_result.execution and not push_result.execution.success:
                error = push_result.execution.error
            
            return ScriptExecutionSummary(
                node_name=node_name,
                script_name=script.name,
                priority=script.priority,
                remote_path=script.remote_path,
                success=success,
                error=error,
            )
        except Exception as exc:
            return ScriptExecutionSummary(
                node_name=node_name,
                script_name=script.name,
                priority=script.priority,
                remote_path=script.remote_path,
                success=False,
                error=str(exc),
            )


async def _execute_embedded_scripts(
    definition: ScenarioDefinition,
    config_record: MutableMapping[str, Any],
    gns3_server_ip: str,
    pusher: ScriptPusher,
    priority_delay: float,
) -> list[ScriptExecutionSummary]:
    """
    Execute all embedded scripts from nodes in priority order.
    
    Scripts with the same priority are executed concurrently (up to MAX_CONCURRENT_SCRIPTS).
    Different priority groups are executed sequentially, with an optional delay between groups.
    """
    # Collect all scripts with their node info
    script_tasks: list[tuple[int, str, Any]] = []
    
    for node in definition.nodes:
        for script in node.scripts:
            script_tasks.append((script.priority, node.name, script))
    
    if not script_tasks:
        return []
    
    # Sort by priority
    script_tasks.sort(key=lambda x: x[0])
    
    # Group by priority
    from itertools import groupby
    priority_groups: list[tuple[int, list[tuple[str, Any]]]] = []
    for priority, group in groupby(script_tasks, key=lambda x: x[0]):
        scripts_in_group = [(node_name, script) for _, node_name, script in group]
        priority_groups.append((priority, scripts_in_group))
    
    results: list[ScriptExecutionSummary] = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCRIPTS)
    previous_priority: int | None = None
    
    for priority, scripts_in_group in priority_groups:
        # Add delay when moving to a new priority group (skip for first group)
        if previous_priority is not None and priority_delay > 0:
            await asyncio.sleep(priority_delay)
        previous_priority = priority
        
        # Execute all scripts in this priority group concurrently
        tasks = [
            _execute_single_script(
                node_name, script, config_record, gns3_server_ip, pusher, semaphore
            )
            for node_name, script in scripts_in_group
        ]
        
        # Gather results (return_exceptions=True to continue on failures)
        group_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in group_results:
            if isinstance(result, Exception):
                # This shouldn't happen since we catch exceptions in _execute_single_script
                results.append(ScriptExecutionSummary(
                    node_name="unknown",
                    script_name="unknown",
                    priority=priority,
                    remote_path="",
                    success=False,
                    error=str(result),
                ))
            else:
                results.append(result)
    
    return results


@router.post("/{scenario_id}/deploy", response_model=ScenarioDeployResponse)
async def deploy_scenario(
    scenario_id: str,
    payload: ScenarioDeployRequest,
    repository: ScenarioRepository = Depends(get_scenario_repository),
    pusher: ScriptPusher = Depends(get_script_pusher),
    settings: APISettings = Depends(get_settings),
) -> ScenarioDeployResponse:
    """
    Deploy a stored scenario to a student's GNS3 server.
    
    If payload.definition is provided, it overrides the stored scenario definition.
    
    This endpoint:
    1. Loads the scenario definition (or uses provided definition)
    2. Creates all nodes and links in the student's GNS3 project
    3. Starts all nodes
    4. Executes embedded scripts in priority order (with delays between groups)
    """
    # Load scenario
    try:
        record = repository.get(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    
    # Use provided definition or fall back to stored one
    if payload.definition:
        definition = payload.definition
    else:
        definition = ScenarioDefinition.model_validate(record["definition"])
    scenario_name = record["name"]
    
    return await _deploy_scenario_impl(
        definition=definition,
        payload=payload,
        pusher=pusher,
        settings=settings,
        scenario_id=scenario_id,
        scenario_name=scenario_name,
    )


@router.post("/deploy", response_model=ScenarioDeployResponse)
async def deploy_adhoc_scenario(
    payload: ScenarioDeployRequest,
    pusher: ScriptPusher = Depends(get_script_pusher),
    settings: APISettings = Depends(get_settings),
) -> ScenarioDeployResponse:
    """
    Deploy an ad-hoc scenario directly without storing it.
    
    Requires payload.definition to be provided.
    
    This endpoint:
    1. Uses the provided scenario definition
    2. Creates all nodes and links in the student's GNS3 project
    3. Starts all nodes
    4. Executes embedded scripts in priority order (with delays between groups)
    """
    if not payload.definition:
        raise HTTPException(
            status_code=400,
            detail="definition is required for ad-hoc deployment"
        )
    
    return await _deploy_scenario_impl(
        definition=payload.definition,
        payload=payload,
        pusher=pusher,
        settings=settings,
        scenario_id=None,
        scenario_name=None,
    )


async def _deploy_scenario_impl(
    definition: ScenarioDefinition,
    payload: ScenarioDeployRequest,
    pusher: ScriptPusher,
    settings: APISettings,
    scenario_id: str | None,
    scenario_name: str | None,
) -> ScenarioDeployResponse:
    """Shared implementation for deploying a scenario."""
    # Build base URL from student's GNS3 server
    base_url = f"http://{payload.gns3_server_ip}:{payload.gns3_server_port}"
    
    # Prepare scenario dict for builder (convert to legacy format)
    project_name = payload.project_name or definition.project_name
    if not project_name and not definition.project_id:
        raise HTTPException(
            status_code=400, 
            detail="Either project_name must be provided or defined in scenario"
        )
    
    scenario_dict: dict[str, Any] = {
        "gns3_server_ip": payload.gns3_server_ip,
        "project_name": project_name,
        "project_id": definition.project_id,
        "templates": definition.templates,
        "nodes": [
            {
                "name": node.name,
                "template_id": node.template_id,
                "template_key": node.template_key,
                "template_name": node.template_name,
                "x": node.x,
                "y": node.y,
            }
            for node in definition.nodes
        ],
        "links": [
            {
                "nodes": [
                    {
                        "node_id": link.nodes[0].name,
                        "adapter_number": link.nodes[0].adapter_number,
                        "port_number": link.nodes[0].port_number,
                    },
                    {
                        "node_id": link.nodes[1].name,
                        "adapter_number": link.nodes[1].adapter_number,
                        "port_number": link.nodes[1].port_number,
                    },
                ]
            }
            for link in definition.links
        ],
    }
    
    # Create GNS3 client and builder
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    session.auth = (payload.username, payload.password)
    
    client = GNS3Client(base_url=base_url, session=session)
    builder = ScenarioBuilder(client, request_delay=settings.gns3_request_delay)
    
    errors: list[str] = []
    warnings: list[str] = []
    
    try:
        # Build scenario (create nodes and links)
        result = await asyncio.to_thread(
            builder.build, 
            scenario_dict, 
            start_nodes=payload.start_nodes
        )
        warnings.extend(result.warnings)
    except GNS3APIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (LookupError, ValueError, requests.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    
    # Write config for script execution
    store = ConfigStore.from_path(settings.config_path)
    store.write(result.config_record)
    
    # Execute scripts if requested
    scripts_executed: list[ScriptExecutionSummary] = []
    if payload.run_scripts and payload.start_nodes:
        # Initial delay for nodes to boot
        await asyncio.sleep(2.0)
        
        scripts_executed = await _execute_embedded_scripts(
            definition=definition,
            config_record=result.config_record,
            gns3_server_ip=payload.gns3_server_ip,
            pusher=pusher,
            priority_delay=payload.priority_delay,
        )
        
        # Collect errors from failed scripts
        for exec_result in scripts_executed:
            if not exec_result.success and exec_result.error:
                errors.append(f"{exec_result.node_name}/{exec_result.script_name}: {exec_result.error}")
    
    overall_success = len(errors) == 0 and len(result.nodes_created) > 0
    
    return ScenarioDeployResponse(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        project_id=result.project_id,
        project_name=result.project_name,
        gns3_server_ip=payload.gns3_server_ip,
        nodes_created=len(result.nodes_created),
        links_created=len(result.links_created),
        scripts_executed=scripts_executed,
        success=overall_success,
        errors=errors,
        warnings=warnings,
    )


# -----------------------------------------------------------------------------
# Project Node Management Endpoints
# -----------------------------------------------------------------------------


@router.delete("/projects/{project_id}/nodes", response_model=DeleteNodesResponse)
async def delete_project_nodes(
    project_id: str,
    payload: DeleteNodesRequest,
) -> DeleteNodesResponse:
    """
    Delete all nodes and links from a GNS3 project by project ID.
    
    This stops all nodes first, then deletes all links, then deletes all nodes.
    Useful for cleaning up a project before redeploying a scenario.
    """
    base_url = f"http://{payload.gns3_server_ip}:{payload.gns3_server_port}"
    
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    session.auth = (payload.username, payload.password)
    
    client = GNS3Client(base_url=base_url, session=session)
    
    try:
        nodes_deleted, links_deleted, errors = await asyncio.to_thread(
            client.delete_all_nodes, project_id
        )
    except GNS3APIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.HTTPError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    
    return DeleteNodesResponse(
        project_id=project_id,
        nodes_deleted=nodes_deleted,
        links_deleted=links_deleted,
        success=len(errors) == 0,
        errors=errors,
    )


@router.delete("/projects/by-name/{project_name}/nodes", response_model=DeleteNodesResponse)
async def delete_project_nodes_by_name(
    project_name: str,
    payload: DeleteNodesRequest,
) -> DeleteNodesResponse:
    """
    Delete all nodes and links from a GNS3 project by project name.
    
    This looks up the project ID by name, then stops all nodes,
    deletes all links, and deletes all nodes.
    Useful for cleaning up a project before redeploying a scenario.
    """
    base_url = f"http://{payload.gns3_server_ip}:{payload.gns3_server_port}"
    
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    session.auth = (payload.username, payload.password)
    
    client = GNS3Client(base_url=base_url, session=session)
    
    try:
        # Look up project ID by name
        project_id = await asyncio.to_thread(client.find_project_id, project_name)
        
        # Delete all nodes
        nodes_deleted, links_deleted, errors = await asyncio.to_thread(
            client.delete_all_nodes, project_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GNS3APIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.HTTPError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    
    return DeleteNodesResponse(
        project_id=project_id,
        nodes_deleted=nodes_deleted,
        links_deleted=links_deleted,
        success=len(errors) == 0,
        errors=errors,
    )
