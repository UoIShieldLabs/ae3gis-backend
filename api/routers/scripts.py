"""Routes for managing and executing scripts on topology nodes."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, MutableMapping

from fastapi import APIRouter, Depends, HTTPException, Response, status

from core.config_store import ConfigStore
from core.nodes import find_node_by_name, resolve_console_target
from core.script_pusher import ScriptExecutionResult, ScriptPusher, ScriptSpec, ScriptTask
from core.script_store import ScriptNotFoundError, ScriptRepository
from models import (
    ScriptCreateRequest,
    ScriptDetail,
    ScriptExecutionModel,
    ScriptPushItem,
    ScriptPushRequest,
    ScriptPushResponse,
    ScriptPushResultModel,
    ScriptRunItem,
    ScriptRunRequest,
    ScriptRunResponse,
    ScriptSummary,
    ScriptUpdateRequest,
    ScriptUploadModel,
)

from ..dependencies import get_config_store, get_script_pusher, get_script_repository

router = APIRouter(prefix="/scripts", tags=["scripts"])


# -----------------------------------------------------------------------------
# Script CRUD Endpoints
# -----------------------------------------------------------------------------


@router.post("/", response_model=ScriptDetail, status_code=status.HTTP_201_CREATED)
def create_script(
    payload: ScriptCreateRequest,
    repository: ScriptRepository = Depends(get_script_repository),
) -> ScriptDetail:
    """Upload and store a new script."""
    record = repository.create(payload.model_dump())
    return ScriptDetail.model_validate(record)


@router.get("/", response_model=list[ScriptSummary])
def list_scripts(
    repository: ScriptRepository = Depends(get_script_repository),
) -> list[ScriptSummary]:
    """List all stored scripts (without content)."""
    records = repository.list_all()
    return [ScriptSummary.model_validate(record) for record in records]


@router.get("/{script_id}", response_model=ScriptDetail)
def get_script(
    script_id: str,
    repository: ScriptRepository = Depends(get_script_repository),
) -> ScriptDetail:
    """Retrieve a script by ID (includes content)."""
    try:
        record = repository.get(script_id)
    except ScriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Script not found") from exc
    return ScriptDetail.model_validate(record)


@router.patch("/{script_id}", response_model=ScriptDetail)
def update_script(
    script_id: str,
    payload: ScriptUpdateRequest,
    repository: ScriptRepository = Depends(get_script_repository),
) -> ScriptDetail:
    """Update a script's metadata or content."""
    updates = payload.to_update_dict()
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    try:
        record = repository.update(script_id, updates)
    except ScriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Script not found") from exc
    return ScriptDetail.model_validate(record)


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_script(
    script_id: str,
    repository: ScriptRepository = Depends(get_script_repository),
) -> Response:
    """Delete a script by ID."""
    try:
        repository.delete(script_id)
    except ScriptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Script not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------------------------------------------------------
# Script Push/Run Endpoints (push stored scripts to GNS3 nodes)
# -----------------------------------------------------------------------------


def _ensure_node(config: MutableMapping[str, Any], node_name: str) -> MutableMapping[str, Any]:
    node = find_node_by_name(config, node_name)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found in config")
    return node


def _ensure_console(node: MutableMapping[str, Any], node_name: str, gns3_server_ip: str | None) -> tuple[str, int]:
    target = resolve_console_target(node, gns3_server_ip)
    if target is None:
        raise HTTPException(status_code=400, detail=f"Node '{node_name}' does not expose a telnet console")
    return target


@router.post("/push", response_model=ScriptPushResponse)
async def push_scripts(
    payload: ScriptPushRequest,
    config_store: ConfigStore = Depends(get_config_store),
    pusher: ScriptPusher = Depends(get_script_pusher),
    script_repo: ScriptRepository = Depends(get_script_repository),
) -> ScriptPushResponse:
    """Push stored scripts to GNS3 nodes and optionally execute them."""
    if not payload.scripts:
        raise HTTPException(status_code=400, detail="No scripts provided")

    config = config_store.load()

    tasks: list[ScriptTask] = []
    for item in payload.scripts:
        node = _ensure_node(config, item.node_name)
        host, port = _ensure_console(node, item.node_name, payload.gns3_server_ip)
        
        # Fetch script content from storage
        try:
            content = script_repo.get_content(item.script_id)
        except ScriptNotFoundError as exc:
            raise HTTPException(
                status_code=404, 
                detail=f"Script '{item.script_id}' not found"
            ) from exc
        
        spec = ScriptSpec(
            remote_path=item.remote_path,
            content=content,
            run_after_upload=item.run_after_upload,
            executable=item.executable,
            overwrite=item.overwrite,
            run_timeout=item.run_timeout,
            shell=item.shell,
        )
        tasks.append(ScriptTask(node_name=item.node_name, host=host, port=port, spec=spec))

    results = await pusher.push_many(tasks, concurrency=payload.concurrency)

    response_items = [
        ScriptPushResultModel(
            upload=ScriptUploadModel(**asdict(result.upload)),
            execution=ScriptExecutionModel(**asdict(result.execution)) if result.execution else None,
        )
        for result in results
    ]
    return ScriptPushResponse(results=response_items)


async def _run_single(
    item: ScriptRunItem,
    config: MutableMapping[str, Any],
    gns3_server_ip: str | None,
    pusher: ScriptPusher,
    semaphore: asyncio.Semaphore,
) -> ScriptExecutionResult:
    node = _ensure_node(config, item.node_name)
    host, port = _ensure_console(node, item.node_name, gns3_server_ip)
    async with semaphore:
        return await pusher.run(
            item.node_name,
            host,
            port,
            item.remote_path,
            shell=item.shell,
            timeout=item.timeout,
        )


@router.post("/run", response_model=ScriptRunResponse)
async def run_scripts(
    payload: ScriptRunRequest,
    config_store: ConfigStore = Depends(get_config_store),
    pusher: ScriptPusher = Depends(get_script_pusher),
) -> ScriptRunResponse:
    """Execute scripts that are already uploaded on GNS3 nodes."""
    if not payload.runs:
        raise HTTPException(status_code=400, detail="No run requests provided")

    config = config_store.load()
    semaphore = asyncio.Semaphore(max(1, payload.concurrency))
    results = await asyncio.gather(
        *(
            _run_single(item, config, payload.gns3_server_ip, pusher, semaphore)
            for item in payload.runs
        )
    )
    return ScriptRunResponse(results=[ScriptExecutionModel(**asdict(res)) for res in results])
