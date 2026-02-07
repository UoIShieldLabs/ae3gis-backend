"""Student logging endpoints for command collection and submission."""

from __future__ import annotations

import logging

import requests
from fastapi import APIRouter, HTTPException, status

from core.gns3_client import GNS3Client, GNS3APIError
from core.student_store import (
    StudentRepository,
    get_student_repository,
    sanitize_student_name,
    display_name_from_sanitized,
)
from core.submission_store import SubmissionRepository, get_submission_repository
from core.log_collector import (
    setup_logging_for_student,
    retrieve_all_logs,
    teardown_logging_for_student,
)
from models.submissions import (
    StudentSession,
    SetupLoggingRequest,
    SetupLoggingResponse,
    SubmitLogsRequest,
    SubmitLogsResponse,
    LogPreviewResponse,
    LoggingStatusResponse,
    TeardownResponse,
    SnitchNodeInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logging", tags=["Student Logging"])


def _create_gns3_client(
    server_ip: str,
    server_port: int = 80,
    username: str = "admin",
    password: str = "admin",
) -> GNS3Client:
    """Create a GNS3 client with the provided credentials."""
    session = requests.Session()
    session.auth = (username, password)
    base_url = f"http://{server_ip}:{server_port}"
    return GNS3Client(base_url=base_url, session=session)


def _get_project_id(client: GNS3Client, project_id: str | None, project_name: str | None) -> tuple[str, str]:
    """Resolve project ID and name.
    
    Returns (project_id, project_name).
    """
    if project_id:
        # Lookup project name
        for project in client.list_projects():
            if project.get("project_id") == project_id:
                return project_id, project.get("name", project_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID '{project_id}' not found",
        )
    elif project_name:
        pid = client.find_project_id(project_name)
        return pid, project_name
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either project_id or project_name must be provided",
        )


@router.post(
    "/{student_name}/setup",
    response_model=SetupLoggingResponse,
    status_code=status.HTTP_200_OK,
    summary="Set up logging for a student",
    description="""
Deploy syslog collector nodes and inject PROMPT_COMMAND into all eligible nodes.

This endpoint:
1. Creates IT-Collector and OT-Collector nodes (or reuses existing ones)
2. Connects them to their respective switches
3. Assigns static IPs to the collectors
4. Injects PROMPT_COMMAND into all telnet-capable nodes (excluding switches and collectors)

The student name will be sanitized (spaces replaced with underscores, lowercased).
If logging is already set up for this student, existing collectors will be reused.
""",
)
async def setup_logging(
    student_name: str,
    request: SetupLoggingRequest,
) -> SetupLoggingResponse:
    """Set up command logging for a student."""
    try:
        sanitized_name = sanitize_student_name(student_name)
        display_name = student_name.strip()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    # Check if student already has an active session
    student_repo = get_student_repository()
    existing_session = student_repo.get(sanitized_name)
    
    # Create GNS3 client
    client = _create_gns3_client(
        request.gns3_server_ip,
        request.gns3_server_port,
        request.username,
        request.password,
    )
    
    # Resolve project
    try:
        project_id, project_name = _get_project_id(
            client, request.project_id, request.project_name
        )
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except GNS3APIError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        )
    
    # Check if existing session is for a different project
    if existing_session and existing_session.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student '{display_name}' already has an active session for project "
                   f"'{existing_session.project_name}'. Teardown first or use the same project.",
        )
    
    # Setup logging
    try:
        result = await setup_logging_for_student(
            client=client,
            project_id=project_id,
            gns3_server_ip=request.gns3_server_ip,
            student_name=sanitized_name,
            it_switch_name=request.it_switch_name,
            ot_switch_name=request.ot_switch_name,
            syslog_template_name=request.syslog_template_name,
        )
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except GNS3APIError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Failed to setup logging")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to setup logging: {e}",
        )
    
    # Save or update student session
    session = StudentSession(
        name=sanitized_name,
        display_name=display_name,
        project_id=project_id,
        project_name=project_name,
        gns3_server_ip=request.gns3_server_ip,
        gns3_server_port=request.gns3_server_port,
        snitch_nodes=result.snitch_nodes,
        injected_nodes=result.injected_nodes,
    )
    student_repo.save(session)
    
    message = "Logging setup complete"
    if result.reused_existing:
        message = "Logging setup complete (reused existing collectors)"
    if result.errors:
        message += f" with {len(result.errors)} warning(s)"
    
    return SetupLoggingResponse(
        student_name=sanitized_name,
        display_name=display_name,
        project_name=project_name,
        snitch_nodes=result.snitch_nodes,
        injected_node_count=len(result.injected_nodes),
        injected_nodes=result.injected_nodes,
        skipped_nodes=result.skipped_nodes,
        errors=result.errors,
        message=message,
        reused_existing=result.reused_existing,
    )


@router.get(
    "/{student_name}/status",
    response_model=LoggingStatusResponse,
    summary="Check logging status for a student",
    description="Check if logging is active for a student and get snitch node information.",
)
async def get_logging_status(student_name: str) -> LoggingStatusResponse:
    """Get the logging status for a student."""
    try:
        sanitized_name = sanitize_student_name(student_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    student_repo = get_student_repository()
    session = student_repo.get(sanitized_name)
    
    if not session:
        return LoggingStatusResponse(
            student_name=sanitized_name,
            display_name=display_name_from_sanitized(sanitized_name),
            is_active=False,
        )
    
    return LoggingStatusResponse(
        student_name=session.name,
        display_name=session.display_name,
        is_active=True,
        project_name=session.project_name,
        snitch_nodes=session.snitch_nodes,
        injected_nodes=session.injected_nodes,
        created_at=session.created_at,
    )


@router.get(
    "/{student_name}/preview",
    response_model=LogPreviewResponse,
    summary="Preview current logs",
    description="""
Retrieve current logs from the student's syslog collectors without saving.

Use this to preview logs before final submission.
""",
)
async def preview_logs(
    student_name: str,
    gns3_server_ip: str,
    gns3_server_port: int = 80,
    username: str = "admin",
    password: str = "admin",
) -> LogPreviewResponse:
    """Preview current logs without saving."""
    try:
        sanitized_name = sanitize_student_name(student_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    student_repo = get_student_repository()
    session = student_repo.get(sanitized_name)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active logging session for student '{student_name}'",
        )
    
    if not session.snitch_nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No syslog collectors found for this student",
        )
    
    client = _create_gns3_client(gns3_server_ip, gns3_server_port, username, password)
    
    try:
        logs, errors = await retrieve_all_logs(
            client=client,
            project_id=session.project_id,
            gns3_server_ip=gns3_server_ip,
            snitch_nodes=session.snitch_nodes,
        )
    except Exception as e:
        logger.exception("Failed to retrieve logs")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve logs: {e}",
        )
    
    return LogPreviewResponse(
        student_name=sanitized_name,
        it_logs=logs.get("it"),
        ot_logs=logs.get("ot"),
        errors=errors,
    )


@router.post(
    "/{student_name}/submit",
    response_model=SubmitLogsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit logs for grading",
    description="""
Retrieve logs from syslog collectors and save them as a submission.

This endpoint retrieves logs from both IT and OT collectors and saves them
to the backend storage. Students can submit multiple times.
""",
)
async def submit_logs(
    student_name: str,
    request: SubmitLogsRequest,
) -> SubmitLogsResponse:
    """Submit current logs for grading."""
    try:
        sanitized_name = sanitize_student_name(student_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    student_repo = get_student_repository()
    session = student_repo.get(sanitized_name)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active logging session for student '{student_name}'. Run setup first.",
        )
    
    if not session.snitch_nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No syslog collectors found for this student",
        )
    
    client = _create_gns3_client(
        request.gns3_server_ip,
        request.gns3_server_port,
        request.username,
        request.password,
    )
    
    # Retrieve logs
    try:
        logs, errors = await retrieve_all_logs(
            client=client,
            project_id=session.project_id,
            gns3_server_ip=request.gns3_server_ip,
            snitch_nodes=session.snitch_nodes,
        )
    except Exception as e:
        logger.exception("Failed to retrieve logs for submission")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve logs: {e}",
        )
    
    it_logs = logs.get("it", "")
    ot_logs = logs.get("ot", "")
    
    # Save submission
    submission_repo = get_submission_repository()
    submission = submission_repo.create(
        student_name=sanitized_name,
        display_name=session.display_name,
        project_name=session.project_name,
        it_logs=it_logs,
        ot_logs=ot_logs,
    )
    
    message = "Logs submitted successfully"
    if errors:
        message += f" with {len(errors)} warning(s)"
    
    return SubmitLogsResponse(
        submission_id=submission.id,
        student_name=sanitized_name,
        submitted_at=submission.submitted_at,
        project_name=session.project_name,
        it_log_lines=len(it_logs.splitlines()) if it_logs else 0,
        ot_log_lines=len(ot_logs.splitlines()) if ot_logs else 0,
        errors=errors,
        message=message,
    )


@router.delete(
    "/{student_name}/teardown",
    response_model=TeardownResponse,
    summary="Tear down logging for a student",
    description="""
Remove syslog collector nodes and clear the student's logging session.

This does NOT delete any existing submissions.
""",
)
async def teardown_logging(
    student_name: str,
    gns3_server_ip: str,
    gns3_server_port: int = 80,
    username: str = "admin",
    password: str = "admin",
) -> TeardownResponse:
    """Tear down logging infrastructure for a student."""
    try:
        sanitized_name = sanitize_student_name(student_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    student_repo = get_student_repository()
    session = student_repo.get(sanitized_name)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active logging session for student '{student_name}'",
        )
    
    client = _create_gns3_client(gns3_server_ip, gns3_server_port, username, password)
    
    # Delete collector nodes from GNS3
    removed_nodes = teardown_logging_for_student(
        client=client,
        project_id=session.project_id,
        gns3_server_ip=gns3_server_ip,
        student_name=sanitized_name,
    )
    
    # Delete student session
    student_repo.delete(sanitized_name)
    
    return TeardownResponse(
        student_name=sanitized_name,
        removed_nodes=removed_nodes,
        message="Logging teardown complete",
    )
