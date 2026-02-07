"""Application factory for the FastAPI service."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from .dependencies import get_settings
from .routers import dhcp as dhcp_router
from .routers import gns3 as gns3_router
from .routers import instructor as instructor_router
from .routers import logging as logging_router
from .routers import topologies as topologies_router
from .routers import scenarios_new as scenarios_router
from .routers import scripts as scripts_router
from models import APISettings


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = APISettings()  # type: ignore[call-arg]

    app = FastAPI(title="GNS3 Topology & Scenario Service", version="0.3.0")
    app.state.settings = settings
    app.dependency_overrides[get_settings] = lambda: settings

    # Topology endpoints (infrastructure definitions)
    app.include_router(topologies_router.router)
    # Scenario endpoints (notebook-style instructions)
    app.include_router(scenarios_router.router)
    # GNS3 proxy endpoints
    app.include_router(gns3_router.router)
    # DHCP assignment
    app.include_router(dhcp_router.router)
    # Script management
    app.include_router(scripts_router.router)
    # Logging/submission
    app.include_router(logging_router.router)
    # Instructor tools
    app.include_router(instructor_router.router)

    # No startup dependency on GNS3 - all connection details come from frontend

    @app.get("/health", tags=["meta"])
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
