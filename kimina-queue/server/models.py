from enum import Enum
from typing import Any

from pydantic import BaseModel


class ServerStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    ERROR = "error"


class QueuedRequest(BaseModel):
    request_id: str
    endpoint: str
    payload: dict[str, Any]
    timestamp: float


class QueueStats(BaseModel):
    queue_size: int
    server_status: ServerStatus
    current_max_repls: int
    default_max_repls: int
    oom_count: int