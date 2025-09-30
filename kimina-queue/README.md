# Kimina Queue Service

Message queue service for managing `kimina-lean-server`. Provides automatic OOM detection and recovery by restarting the Lean server with reduced `MAX_REPLS` settings.

## Features

- **FIFO Request Queue**: Queues incoming requests and processes them sequentially
- **OOM Detection**: Automatically detects out-of-memory errors from the Lean server
- **Automatic Recovery**: Restarts the Lean server with 50% reduced `MAX_REPLS` on OOM
- **Transparent Proxy**: Proxies `/api/check` requests to the Lean server
- **Server Management**: API endpoints for manual server start/stop/restart
- **Statistics**: Monitor queue size, server status, and OOM count

## Architecture

```
Client → Queue Service (port 8010) → FIFO Queue → Worker → Lean Server (port 8000)
                                                      ↓
                                              OOM Detection
                                                      ↓
                                          Restart with reduced MAX_REPLS
                                                      ↓
                                        Restore default after completion
```

## Setup

### Local Development

1. **Navigate to the directory:**
   ```bash
   cd kimina-queue
   ```

2. **Create environment file:**
   ```bash
   cp .env.template .env
   # Edit .env with your settings
   ```

3. **Install dependencies:**
   ```bash
   uv sync
   ```

4. **Run the service:**
   ```bash
   # Note: Must run as a module with -m flag
   uv run python -m server

   # Or without uv (after installing dependencies):
   python -m server
   ```

### Docker

1. **Build and run with docker-compose:**
   ```bash
   docker compose up
   ```

2. **Build standalone:**
   ```bash
   docker build -t kimina-queue .
   ```

## Usage

### Check Lean Code

Send requests to the queue service instead of directly to the Lean server:

```bash
curl --request POST \
  --url http://localhost:8010/api/check \
  --header 'Content-Type: application/json' \
  --data '{
    "snippets": [{"id": "test", "code": "#check Nat"}]
  }' | jq
```

### Get Queue Statistics

```bash
curl http://localhost:8010/stats | jq
```

Response:
```json
{
  "queue_size": 5,
  "server_status": "running",
  "current_max_repls": 4,
  "default_max_repls": 8,
  "oom_count": 2
}
```

### Manual Server Management

**Restart with reduced MAX_REPLS:**
```bash
curl -X POST http://localhost:8010/api/restart?reduce_max_repls=true
```

**Restart with default MAX_REPLS:**
```bash
curl -X POST http://localhost:8010/api/restart-default
```

## Configuration

Environment variables (prefix: `QUEUE_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `QUEUE_HOST` | `0.0.0.0` | Host to bind the queue service |
| `QUEUE_PORT` | `8010` | Port to bind the queue service |
| `QUEUE_LOG_LEVEL` | `INFO` | Logging level |
| `LEAN_SERVER_URL` | `http://localhost:8000` | Lean server base URL |
| `LEAN_SERVER_ENV_PATH` | `/path/to/lean-server/.env` | Path to Lean server .env file |
| `LEAN_SERVER_API_KEY` | `None` | Optional API key for Lean server |
| `QUEUE_MAX_SIZE` | `1000` | Maximum queue size |
| `QUEUE_REQUEST_TIMEOUT` | `300.0` | Request timeout in seconds |

## How It Works

### OOM Detection and Recovery

1. Client sends request to queue service
2. Request is added to FIFO queue
3. Worker processes request and sends to Lean server
4. If Lean server returns 500 error with OOM indication:
   - Increment OOM counter
   - Read current `LEAN_SERVER_MAX_REPLS` from `.env`
   - Reduce by 50% (minimum 1)
   - Write new value to `.env`
   - Restart Lean server
   - Wait for server to be ready
   - Re-queue the failed request
5. After successful completion, optionally restore default `MAX_REPLS`

### Request Flow

- All requests are queued in FIFO order
- Worker task processes one request at a time
- If server is restarting, requests wait in queue
- Responses are returned to the original caller
- Timeouts are handled gracefully

## API Endpoints

### `POST /api/check`
Proxy endpoint for Lean code checking. Same interface as `kimina-lean-server`.

### `GET /health`
Health check endpoint. Returns `{"status": "ok"}`.

### `GET /stats`
Get queue statistics (see example above).

### `POST /api/restart`
Manually restart the Lean server. Query parameter:
- `reduce_max_repls` (bool): Reduce MAX_REPLS by 50% on restart

### `POST /api/restart-default`
Restart the Lean server with default MAX_REPLS value.

## Development

Run linting:
```bash
uv run ruff check .
uv run pyright .
```

Run tests:
```bash
uv run pytest
```

## License

Same as kimina-lean-server.