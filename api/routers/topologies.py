"""Routes for managing and deploying topologies (network infrastructure definitions)."""

from __future__ import annotations

import asyncio
from typing import Any, MutableMapping

import requests
from fastapi import APIRouter, Depends, HTTPException, Response, status

from core.config_store import ConfigStore
from core.gns3_client import GNS3Client, GNS3APIError
from core.nodes import find_node_by_name, resolve_console_target
from core.scenario_builder import ScenarioBuilder
from core.topology_store import TopologyNotFoundError, TopologyRepository
from core.script_pusher import ScriptPusher, ScriptSpec
from models.topology_types import (
    TopologyCreateRequest,
    TopologyDefinition,
    TopologyDeployRequest,
    TopologyDeployResponse,
    TopologyDetail,
    TopologySummary,
    TopologyUpdateRequest,
    ScriptExecutionSummary,
    DeleteNodesRequest,
    DeleteNodesResponse,
    DeployedNodeInfo,
    DeployedNodesResponse,
)
from models import APISettings

from ..dependencies import get_topology_repository, get_script_pusher, get_settings

router = APIRouter(prefix="/topologies", tags=["topologies"])


# -----------------------------------------------------------------------------
# Topology CRUD Endpoints
# -----------------------------------------------------------------------------


@router.post("/", response_model=TopologyDetail, status_code=status.HTTP_201_CREATED)
def create_topology(
    payload: TopologyCreateRequest,
    repository: TopologyRepository = Depends(get_topology_repository),
) -> TopologyDetail:
    """Create a new topology (instructor use)."""
    data = {
        "name": payload.name,
        "description": payload.description,
        "definition": payload.definition.model_dump(),
    }
    record = repository.create(data)
    return TopologyDetail.model_validate(record)


@router.get("/", response_model=list[TopologySummary])
def list_topologies(
    repository: TopologyRepository = Depends(get_topology_repository),
) -> list[TopologySummary]:
    """List all stored topologies."""
    records = repository.list_all()
    return [TopologySummary.model_validate(record) for record in records]


@router.get("/{topology_id}", response_model=TopologyDetail)
def get_topology(
    topology_id: str,
    repository: TopologyRepository = Depends(get_topology_repository),
) -> TopologyDetail:
    """Retrieve a topology by ID."""
    try:
        record = repository.get(topology_id)
    except TopologyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Topology not found") from exc
    return TopologyDetail.model_validate(record)


@router.patch("/{topology_id}", response_model=TopologyDetail)
def update_topology(
    topology_id: str,
    payload: TopologyUpdateRequest,
    repository: TopologyRepository = Depends(get_topology_repository),
) -> TopologyDetail:
    """Update a topology's metadata or definition (instructor use)."""
    updates = payload.to_update_dict()
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    try:
        record = repository.update(topology_id, updates)
    except TopologyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Topology not found") from exc
    return TopologyDetail.model_validate(record)


@router.delete("/{topology_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topology(
    topology_id: str,
    repository: TopologyRepository = Depends(get_topology_repository),
) -> Response:
    """Delete a topology by ID (instructor use)."""
    try:
        repository.delete(topology_id)
    except TopologyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Topology not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------------------------------------------------------
# Topology Deployment Endpoint
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
            run_after_upload=script.run_after_upload,
            executable=True,
            overwrite=True,
            run_timeout=script.timeout,
            shell=script.shell,
        )
        
        try:
            push_result = await pusher.push(node_name, host, port, spec)
            
            # Success depends on whether we're running or just uploading
            if script.run_after_upload:
                # Both upload and execution must succeed
                success = push_result.upload.success and (
                    push_result.execution.success if push_result.execution else False
                )
            else:
                # Only upload needs to succeed (no execution expected)
                success = push_result.upload.success
            
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
    definition: TopologyDefinition,
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


@router.post("/{topology_id}/deploy", response_model=TopologyDeployResponse)
async def deploy_topology(
    topology_id: str,
    payload: TopologyDeployRequest,
    repository: TopologyRepository = Depends(get_topology_repository),
    pusher: ScriptPusher = Depends(get_script_pusher),
    settings: APISettings = Depends(get_settings),
) -> TopologyDeployResponse:
    """
    Deploy a stored topology to a GNS3 server.
    
    If payload.definition is provided, it overrides the stored topology definition.
    
    This endpoint:
    1. Loads the topology definition (or uses provided definition)
    2. Creates all nodes and links in the GNS3 project
    3. Starts all nodes
    4. Executes embedded scripts in priority order (with delays between groups)
    """
    # Load topology
    try:
        record = repository.get(topology_id)
    except TopologyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Topology not found") from exc
    
    # Use provided definition or fall back to stored one
    if payload.definition:
        definition = payload.definition
    else:
        definition = TopologyDefinition.model_validate(record["definition"])
    topology_name = record["name"]
    
    return await _deploy_topology_impl(
        definition=definition,
        payload=payload,
        pusher=pusher,
        settings=settings,
        topology_id=topology_id,
        topology_name=topology_name,
    )


@router.post("/deploy", response_model=TopologyDeployResponse)
async def deploy_adhoc_topology(
    payload: TopologyDeployRequest,
    pusher: ScriptPusher = Depends(get_script_pusher),
    settings: APISettings = Depends(get_settings),
) -> TopologyDeployResponse:
    """
    Deploy an ad-hoc topology directly without storing it.
    
    Requires payload.definition to be provided.
    
    This endpoint:
    1. Uses the provided topology definition
    2. Creates all nodes and links in the GNS3 project
    3. Starts all nodes
    4. Executes embedded scripts in priority order (with delays between groups)
    """
    if not payload.definition:
        raise HTTPException(
            status_code=400,
            detail="definition is required for ad-hoc deployment"
        )
    
    return await _deploy_topology_impl(
        definition=payload.definition,
        payload=payload,
        pusher=pusher,
        settings=settings,
        topology_id=None,
        topology_name=None,
    )


async def _deploy_topology_impl(
    definition: TopologyDefinition,
    payload: TopologyDeployRequest,
    pusher: ScriptPusher,
    settings: APISettings,
    topology_id: str | None,
    topology_name: str | None,
) -> TopologyDeployResponse:
    """Shared implementation for deploying a topology."""
    # Build base URL from GNS3 server
    base_url = f"http://{payload.gns3_server_ip}:{payload.gns3_server_port}"
    
    # Prepare topology dict for builder (convert to legacy format)
    project_name = payload.project_name or definition.project_name
    if not project_name and not definition.project_id:
        raise HTTPException(
            status_code=400, 
            detail="Either project_name must be provided or defined in topology"
        )
    
    topology_dict: dict[str, Any] = {
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
        # Build topology (create nodes and links)
        result = await asyncio.to_thread(
            builder.build, 
            topology_dict, 
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
    
    return TopologyDeployResponse(
        topology_id=topology_id,
        topology_name=topology_name,
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


def _infer_layer(node_name: str) -> str:
    """
    Infer the layer/zone of a node based on its name.
    
    Common patterns:
    - IT: workstation, client, user, admin, corporate
    - DMZ: dmz, web, proxy, gateway, firewall
    - OT: plc, hmi, scada, rtu, ics, historian, engineering
    - Field: sensor, actuator, motor, valve, pump, field
    """
    name_lower = node_name.lower()
    
    # OT layer keywords
    ot_keywords = ['plc', 'hmi', 'scada', 'rtu', 'ics', 'historian', 'engineering', 
                   'dcs', 'mtconnect', 'opcua', 'modbus', 'controller']
    for kw in ot_keywords:
        if kw in name_lower:
            return "OT"
    
    # Field layer keywords
    field_keywords = ['sensor', 'actuator', 'motor', 'valve', 'pump', 'field',
                      'io', 'remote', 'terminal']
    for kw in field_keywords:
        if kw in name_lower:
            return "Field"
    
    # DMZ layer keywords
    dmz_keywords = ['dmz', 'web', 'proxy', 'gateway', 'firewall', 'fw', 'router',
                    'switch', 'openvswitch', 'ovs', 'nat', 'vpn']
    for kw in dmz_keywords:
        if kw in name_lower:
            return "DMZ"
    
    # IT layer keywords
    it_keywords = ['workstation', 'client', 'user', 'admin', 'corporate', 'office',
                   'desktop', 'laptop', 'pc', 'ubuntu', 'windows', 'kali', 'attacker',
                   'server', 'dhcp', 'dns', 'ad', 'domain']
    for kw in it_keywords:
        if kw in name_lower:
            return "IT"
    
    return "Unknown"


@router.get("/projects/{project_name}/nodes", response_model=DeployedNodesResponse)
async def list_project_nodes(
    project_name: str,
    server_ip: str,
    server_port: int = 80,
    username: str = "gns3",
    password: str = "gns3",
) -> DeployedNodesResponse:
    """
    List all deployed nodes in a GNS3 project, grouped by layer.
    
    This is useful for:
    - Selecting target nodes for script execution
    - Understanding the current topology state
    - Displaying node information in the frontend
    
    Nodes are automatically classified into layers (IT, DMZ, OT, Field, Unknown)
    based on their names.
    """
    base_url = f"http://{server_ip}:{server_port}"
    
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    session.auth = (username, password)
    
    client = GNS3Client(base_url=base_url, session=session)
    
    try:
        # Find project ID
        project_id = await asyncio.to_thread(client.find_project_id, project_name)
        
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
    
    # Convert to DeployedNodeInfo
    nodes: list[DeployedNodeInfo] = []
    nodes_by_layer: dict[str, list[DeployedNodeInfo]] = {
        "IT": [],
        "DMZ": [],
        "OT": [],
        "Field": [],
        "Unknown": [],
    }
    
    for raw_node in raw_nodes:
        node_name = raw_node.get("name", "")
        layer = _infer_layer(node_name)
        
        node_info = DeployedNodeInfo(
            node_id=raw_node.get("node_id", ""),
            name=node_name,
            status=raw_node.get("status", "unknown"),
            console=raw_node.get("console"),
            console_type=raw_node.get("console_type"),
            console_host=raw_node.get("console_host") or server_ip,
            node_type=raw_node.get("node_type"),
            template_id=raw_node.get("template_id"),
            layer=layer,
            x=raw_node.get("x", 0),
            y=raw_node.get("y", 0),
        )
        nodes.append(node_info)
        nodes_by_layer[layer].append(node_info)
    
    return DeployedNodesResponse(
        project_id=project_id,
        project_name=project_name,
        total_nodes=len(nodes),
        nodes=nodes,
        nodes_by_layer=nodes_by_layer,
    )


@router.delete("/projects/{project_id}/nodes", response_model=DeleteNodesResponse)
async def delete_project_nodes(
    project_id: str,
    payload: DeleteNodesRequest,
) -> DeleteNodesResponse:
    """
    Delete all nodes and links from a GNS3 project by project ID.
    
    This stops all nodes first, then deletes all links, then deletes all nodes.
    Useful for cleaning up a project before redeploying a topology.
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
    Useful for cleaning up a project before redeploying a topology.
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
