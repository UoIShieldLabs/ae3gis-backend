# GNS3 Scenario Service API

A FastAPI service for automating GNS3 network topology creation, script management, and execution.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- A running GNS3 server

## Setup

```bash
# Clone and enter the project
cd ae3gis-gns3-api

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your GNS3 server details
```

## Run

```bash
uv run uvicorn api.main:app --reload
```

Server runs at `http://127.0.0.1:8000`

## API Documentation

- **Swagger UI**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc
 -->

<!-- See [API_REFERENCE.md](API_REFERENCE.md) for complete documentation. -->


