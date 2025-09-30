from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8010
    log_level: str = "INFO"

    lean_server_url: str = "http://localhost:8000"
    lean_server_env_path: str = "/home/chivier/Projects/kimina-lean-server/.env"
    lean_server_api_key: str | None = None

    queue_max_size: int = 1000
    queue_request_timeout: float = 300.0

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="QUEUE_"
    )


settings = Settings()