import asyncio
import re
from pathlib import Path

from loguru import logger

from .models import ServerStatus


class LeanServerManager:
    def __init__(self, env_path: str, server_dir: str | None = None):
        self.env_path = Path(env_path)
        self.server_dir = Path(server_dir) if server_dir else self.env_path.parent
        self._process: asyncio.subprocess.Process | None = None
        self._status = ServerStatus.STOPPED
        self._default_max_repls: int | None = None
        self._current_max_repls: int | None = None
        self._oom_count = 0

        if not self.env_path.exists():
            logger.warning(f".env file not found at {self.env_path}")

    @property
    def status(self) -> ServerStatus:
        return self._status

    @property
    def oom_count(self) -> int:
        return self._oom_count

    @property
    def current_max_repls(self) -> int | None:
        return self._current_max_repls

    @property
    def default_max_repls(self) -> int | None:
        return self._default_max_repls

    def _read_env(self) -> dict[str, str]:
        """Read .env file and return key-value pairs."""
        if not self.env_path.exists():
            return {}

        env_vars = {}
        with open(self.env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.match(r"^([A-Z_]+)=(.*)$", line)
                if match:
                    key, value = match.groups()
                    env_vars[key] = value
        return env_vars

    def _write_env(self, env_vars: dict[str, str]) -> None:
        """Write key-value pairs to .env file."""
        lines = []
        if self.env_path.exists():
            with open(self.env_path) as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        lines.append(line)
                        continue

                    match = re.match(r"^([A-Z_]+)=", stripped)
                    if match:
                        key = match.group(1)
                        if key in env_vars:
                            lines.append(f"{key}={env_vars[key]}\n")
                            del env_vars[key]
                        else:
                            lines.append(line)
                    else:
                        lines.append(line)

        # Add any new keys
        for key, value in env_vars.items():
            lines.append(f"{key}={value}\n")

        with open(self.env_path, "w") as f:
            f.writelines(lines)

    def _get_max_repls(self) -> int | None:
        """Get current MAX_REPLS from .env file."""
        env_vars = self._read_env()
        max_repls_str = env_vars.get("LEAN_SERVER_MAX_REPLS", "")

        if not max_repls_str or max_repls_str.strip() == "":
            return None

        try:
            return int(max_repls_str)
        except ValueError:
            logger.warning(f"Invalid MAX_REPLS value: {max_repls_str}")
            return None

    def _set_max_repls(self, value: int) -> None:
        """Set MAX_REPLS in .env file."""
        env_vars = self._read_env()
        env_vars["LEAN_SERVER_MAX_REPLS"] = str(value)
        self._write_env(env_vars)
        logger.info(f"Updated LEAN_SERVER_MAX_REPLS to {value}")

    async def start(self) -> bool:
        """Start the Lean server."""
        if self._status == ServerStatus.RUNNING:
            logger.warning("Lean server is already running")
            return True

        self._status = ServerStatus.RUNNING
        logger.info("Starting Lean server...")

        try:
            self._process = await asyncio.create_subprocess_exec(
                "python",
                "-m",
                "server",
                cwd=str(self.server_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Store the default max_repls on first start
            if self._default_max_repls is None:
                self._default_max_repls = self._get_max_repls()
            self._current_max_repls = self._get_max_repls()

            logger.info(f"Lean server started with PID {self._process.pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to start Lean server: {e}")
            self._status = ServerStatus.ERROR
            return False

    async def stop(self) -> bool:
        """Stop the Lean server."""
        if self._status == ServerStatus.STOPPED:
            logger.warning("Lean server is not running")
            return True

        logger.info("Stopping Lean server...")

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Lean server did not stop gracefully, killing...")
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.error(f"Error stopping Lean server: {e}")
                return False

        self._process = None
        self._status = ServerStatus.STOPPED
        logger.info("Lean server stopped")
        return True

    async def restart(self, reduce_max_repls: bool = False) -> bool:
        """Restart the Lean server, optionally reducing MAX_REPLS by 50%."""
        self._status = ServerStatus.RESTARTING
        logger.info(f"Restarting Lean server (reduce_max_repls={reduce_max_repls})...")

        await self.stop()

        if reduce_max_repls:
            current = self._get_max_repls()
            if current is not None and current > 1:
                new_value = max(1, current // 2)
                self._set_max_repls(new_value)
                logger.info(f"Reduced MAX_REPLS from {current} to {new_value}")
            else:
                logger.warning("Cannot reduce MAX_REPLS (current value is None or 1)")

        return await self.start()

    async def restart_to_default(self) -> bool:
        """Restart the Lean server with default MAX_REPLS."""
        if self._default_max_repls is None:
            logger.warning("Default MAX_REPLS not set, cannot restore")
            return await self.restart(reduce_max_repls=False)

        logger.info(f"Restarting Lean server with default MAX_REPLS={self._default_max_repls}")
        await self.stop()
        self._set_max_repls(self._default_max_repls)
        return await self.start()

    def increment_oom_count(self) -> None:
        """Increment the OOM error counter."""
        self._oom_count += 1
        logger.warning(f"OOM count increased to {self._oom_count}")