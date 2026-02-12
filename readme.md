# AE3GIS GNS3 API

A FastAPI backend service for managing GNS3 network topologies and educational scenarios. This API enables automated deployment of network infrastructure and execution of scripts on virtual nodes.

## Features

- **Topology Management** – Create, store, and deploy network topologies to GNS3
- **Scenario Builder** – Build notebook-style educational scenarios with markdown instructions and executable scripts
- **Script Execution** – Upload and execute scripts on running GNS3 nodes via telnet
- **Node Management** – List, start, stop, and delete nodes in GNS3 projects
- **DHCP Assignment** – Automated IP address assignment for deployed nodes

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A running GNS3 server with API access enabled

## Installation

### Using uv (Recommended)

```bash
git clone <repository-url>
cd ae3gis-gns3-api

uv sync
```

### Using pip

```bash
git clone <repository-url>
cd ae3gis-gns3-api

python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root (optional):

```env
CONFIG_PATH=config/config.generated.json
SCRIPTS_BASE_DIR=scripts
GNS3_REQUEST_DELAY=0.2
```

> **Note:** GNS3 server connection details (IP, port, credentials) are provided per-request by the frontend, not stored in environment variables.

## Running the Server

### Development

```bash
uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Production

```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The server will be available at `http://localhost:8000`

## API Documentation

Once the server is running, access the interactive documentation:

| Documentation | URL |
|---------------|-----|
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/openapi.json |

For detailed endpoint documentation, see [API_REFERENCE.md](API_REFERENCE.md).

## Project Structure

```
ae3gis-gns3-api/
├── api/                    # FastAPI application
│   ├── main.py             # App factory and router registration
│   ├── dependencies.py     # Dependency injection
│   └── routers/            # API endpoint modules
├── core/                   # Business logic
│   ├── gns3_client.py      # GNS3 API client
│   ├── script_pusher.py    # Script upload/execution via telnet
│   ├── topology_store.py   # Topology persistence
│   └── ...
├── models/                 # Pydantic models
├── storage/                # JSON file storage
│   ├── topologies/         # Saved topology definitions
│   ├── scenarios/          # Saved scenarios
│   └── ...
├── config/                 # Configuration files
└── scripts/                # Sample scripts
```

## License

MIT