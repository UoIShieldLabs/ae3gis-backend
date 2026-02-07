"""Routes for proxying GNS3 API requests."""

from __future__ import annotations

from typing import Any, MutableMapping

import requests
from fastapi import APIRouter, HTTPException, Query

from core.gns3_client import GNS3Client, GNS3APIError

router = APIRouter(prefix="/gns3", tags=["gns3"])


def _create_client(server_ip: str, server_port: int, username: str, password: str) -> tuple[GNS3Client, requests.Session]:
    """Create a GNS3 client with the given credentials."""
    base_url = f"http://{server_ip}:{server_port}"
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    session.auth = (username, password)
    return GNS3Client(base_url=base_url, session=session), session


@router.get("/projects")
def list_gns3_projects(
    server_ip: str = Query(..., description="GNS3 server IP address"),
    server_port: int = Query(default=80, description="GNS3 server port"),
    username: str = Query(default="gns3", description="GNS3 username"),
    password: str = Query(default="gns3", description="GNS3 password"),
) -> list[MutableMapping[str, Any]]:
    """
    List all projects on a GNS3 server.
    
    This proxies the request to the GNS3 server, so the frontend
    doesn't need to make direct requests to GNS3.
    """
    client, session = _create_client(server_ip, server_port, username, password)
    try:
        projects = client.list_projects()
        return projects
    except GNS3APIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to GNS3 server: {exc}") from exc
    finally:
        session.close()


@router.get("/projects/by-name/{project_name}")
def get_project_by_name(
    project_name: str,
    server_ip: str = Query(..., description="GNS3 server IP address"),
    server_port: int = Query(default=80, description="GNS3 server port"),
    username: str = Query(default="gns3", description="GNS3 username"),
    password: str = Query(default="gns3", description="GNS3 password"),
) -> MutableMapping[str, Any]:
    """
    Get a project by name from a GNS3 server.
    
    Returns the project object with project_id, name, status, etc.
    """
    client, session = _create_client(server_ip, server_port, username, password)
    try:
        projects = client.list_projects()
        for project in projects:
            if project.get("name") == project_name:
                return project
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    except GNS3APIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to GNS3 server: {exc}") from exc
    finally:
        session.close()
