"""Models for student logging sessions and submissions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SnitchNodeInfo(BaseModel):
    """Information about a deployed syslog-collector (snitch) node."""

    node_id: str = Field(..., description="GNS3 node UUID")
    name: str = Field(..., description="Node name in GNS3 (e.g., 'alice-IT-Collector')")
    ip_address: str = Field(..., description="Static IP assigned to this collector")
    port: int = Field(default=514, description="Syslog UDP port")
    connected_to_switch: str = Field(..., description="Name of the switch this collector is connected to")
    console_port: int | None = Field(default=None, description="Telnet console port for log retrieval")
    console_host: str | None = Field(default=None, description="Telnet console host")


class StudentSession(BaseModel):
    """An active logging session for a student."""

    name: str = Field(..., description="Student name (spaces replaced with underscores)")
    display_name: str = Field(..., description="Original student name with spaces")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    project_id: str = Field(..., description="GNS3 project ID")
    project_name: str = Field(..., description="GNS3 project name")
    gns3_server_ip: str = Field(..., description="GNS3 server IP used for this session")
    gns3_server_port: int = Field(default=80)
    snitch_nodes: list[SnitchNodeInfo] = Field(default_factory=list)
    injected_nodes: list[str] = Field(default_factory=list, description="Names of nodes where PROMPT_COMMAND was injected")


class SetupLoggingRequest(BaseModel):
    """Request to set up logging for a student."""

    project_id: str | None = Field(default=None, description="GNS3 project UUID (one of project_id or project_name required)")
    project_name: str | None = Field(default=None, description="GNS3 project name (one of project_id or project_name required)")
    gns3_server_ip: str = Field(..., description="GNS3 server IP address")
    gns3_server_port: int = Field(default=80, description="GNS3 server port")
    username: str = Field(default="admin", description="GNS3 username")
    password: str = Field(default="admin", description="GNS3 password")
    
    # Snitch configuration with defaults
    it_switch_name: str = Field(default="IT-Switch", description="Name of the IT switch to connect collector to")
    ot_switch_name: str = Field(default="OT-Switch", description="Name of the OT switch to connect collector to")
    syslog_template_name: str = Field(default="syslog-collector", description="GNS3 template name for syslog container")


class SetupLoggingResponse(BaseModel):
    """Response after setting up logging."""

    student_name: str = Field(..., description="Sanitized student name (underscores instead of spaces)")
    display_name: str = Field(..., description="Original student name")
    project_name: str
    snitch_nodes: list[SnitchNodeInfo] = Field(..., description="Deployed collector nodes with IPs and ports")
    injected_node_count: int = Field(..., description="Number of nodes where PROMPT_COMMAND was injected")
    injected_nodes: list[str] = Field(..., description="Names of nodes where PROMPT_COMMAND was injected")
    skipped_nodes: list[str] = Field(default_factory=list, description="Nodes skipped (switches, non-telnet, collectors)")
    errors: list[str] = Field(default_factory=list, description="Errors or warnings encountered during setup")
    message: str = Field(default="Logging setup complete")
    reused_existing: bool = Field(default=False, description="True if existing snitch nodes were reused")


class LogPreviewResponse(BaseModel):
    """Response containing current logs without saving."""

    student_name: str
    it_logs: str | None = Field(default=None, description="Logs from IT-side collector")
    ot_logs: str | None = Field(default=None, description="Logs from OT-side collector")
    errors: list[str] = Field(default_factory=list, description="Errors encountered during log retrieval")
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class SubmitLogsRequest(BaseModel):
    """Request to submit logs for grading."""

    gns3_server_ip: str = Field(..., description="GNS3 server IP address")
    gns3_server_port: int = Field(default=80, description="GNS3 server port")
    username: str = Field(default="admin", description="GNS3 username")
    password: str = Field(default="admin", description="GNS3 password")


class SubmitLogsResponse(BaseModel):
    """Response after submitting logs."""

    submission_id: str = Field(..., description="Unique submission identifier")
    student_name: str
    submitted_at: datetime
    project_name: str
    it_log_lines: int = Field(default=0, description="Number of lines in IT logs")
    ot_log_lines: int = Field(default=0, description="Number of lines in OT logs")
    errors: list[str] = Field(default_factory=list, description="Errors encountered during log retrieval")
    message: str = Field(default="Logs submitted successfully")


class Submission(BaseModel):
    """A saved log submission."""

    id: str = Field(..., description="Unique submission ID")
    student_name: str = Field(..., description="Sanitized student name")
    display_name: str = Field(..., description="Original student name")
    submitted_at: datetime
    project_name: str
    it_logs: str = Field(default="", description="IT-side collector logs")
    ot_logs: str = Field(default="", description="OT-side collector logs")
    ai_analysis: str | None = Field(default=None, description="AI-generated analysis of the logs")
    analyzed_at: datetime | None = Field(default=None, description="When AI analysis was performed")
    model_used: str | None = Field(default=None, description="OpenAI model used for analysis")


class SubmissionSummary(BaseModel):
    """Summary of a submission for listing."""

    id: str
    student_name: str
    display_name: str
    submitted_at: datetime
    project_name: str
    it_log_lines: int
    ot_log_lines: int
    has_analysis: bool = Field(default=False, description="Whether AI analysis has been performed")


class StudentSummary(BaseModel):
    """Summary of a student for listing."""

    name: str = Field(..., description="Sanitized student name")
    display_name: str = Field(..., description="Original student name")
    created_at: datetime
    project_name: str
    has_active_session: bool = Field(default=True)
    submission_count: int = Field(default=0)


class LoggingStatusResponse(BaseModel):
    """Response for checking logging status."""

    student_name: str
    display_name: str
    is_active: bool
    project_name: str | None = None
    snitch_nodes: list[SnitchNodeInfo] = Field(default_factory=list)
    injected_nodes: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class TeardownResponse(BaseModel):
    """Response after tearing down logging."""

    student_name: str
    removed_nodes: list[str] = Field(default_factory=list)
    message: str = Field(default="Logging teardown complete")


class AnalyzeLogsRequest(BaseModel):
    """Request to analyze student logs using AI."""
    
    gns3_server_ip: str | None = Field(
        default=None,
        description="GNS3 server IP (required if analyzing live logs)"
    )
    gns3_server_port: int = Field(default=80, description="GNS3 server port")
    username: str = Field(default="admin", description="GNS3 username")
    password: str = Field(default="admin", description="GNS3 password")


class AnalyzeLogsResponse(BaseModel):
    """Response containing AI-generated analysis of student logs."""
    
    student_name: str = Field(..., description="Sanitized student name")
    display_name: str = Field(..., description="Original student name")
    submission_id: str | None = Field(
        default=None,
        description="Submission ID if analyzing a saved submission"
    )
    source: str = Field(
        ...,
        description="Source of logs: 'submission' or 'live'"
    )
    summary: str = Field(..., description="AI-generated analysis of student actions")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = Field(..., description="OpenAI model used for analysis")
