"""Async connection to Ableton Live Remote Script.

Replaces the old blocking socket connection with asyncio streams.
Key improvements:
- Non-blocking I/O (doesn't freeze the event loop)
- No time.sleep() calls
- Automatic reconnection with retry on failure
- Batch command support
- Connection locking for thread safety
- Lightweight ping-based health checks
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AbletonMCPServer")

# Environment-configurable defaults
DEFAULT_HOST = os.environ.get("ABLETON_MCP_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("ABLETON_MCP_PORT", "9877"))
DEFAULT_TIMEOUT = float(os.environ.get("ABLETON_MCP_TIMEOUT", "15.0"))
CONNECT_TIMEOUT = float(os.environ.get("ABLETON_MCP_CONNECT_TIMEOUT", "5.0"))


class AbletonConnection:
    """Async TCP connection to the Ableton Remote Script.

    Connection parameters can be overridden via environment variables:
    - ABLETON_MCP_HOST (default: localhost)
    - ABLETON_MCP_PORT (default: 9877)
    - ABLETON_MCP_TIMEOUT (default: 15.0s) — read timeout for commands
    - ABLETON_MCP_CONNECT_TIMEOUT (default: 5.0s) — TCP connect timeout
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Whether the connection appears to be alive."""
        return self._connected and self.writer is not None and not self.writer.is_closing()

    async def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=CONNECT_TIMEOUT,
            )
            self._connected = True
            logger.info("Connected to Ableton at %s:%d", self.host, self.port)
            return True
        except Exception as e:
            logger.error("Failed to connect to Ableton: %s", e)
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect from the Ableton Remote Script."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None
        if self._connected:
            logger.info("Disconnected from Ableton")
        self._connected = False

    async def ensure_connected(self):
        """Ensure we have an active connection, reconnecting if needed."""
        if self.is_connected:
            return

        self._connected = False
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Connecting to Ableton (attempt %d/%d)...", attempt, max_attempts
            )
            if await self.connect():
                # Validate with a lightweight ping (falls back to
                # get_session_info for older Remote Script versions)
                try:
                    await self._send_and_receive("ping", timeout=3.0)
                    logger.info("Connection validated (ping)")
                    return
                except Exception as ping_exc:
                    if "Unknown command" in str(ping_exc) and self.is_connected:
                        # Remote Script is alive but doesn't have ping yet —
                        # the connection is valid, no need to retry
                        logger.info(
                            "Connection validated (ping not supported, "
                            "but response received)"
                        )
                        return
                    # Real connection failure — try get_session_info as
                    # a heavier validation on a fresh connection
                    if not self.is_connected:
                        await self.disconnect()
                        if not await self.connect():
                            continue
                    try:
                        await self._send_and_receive(
                            "get_session_info", timeout=5.0
                        )
                        logger.info("Connection validated (get_session_info)")
                        return
                    except Exception as e:
                        logger.warning("Connection validation failed: %s", e)
                        await self.disconnect()

            if attempt < max_attempts:
                await asyncio.sleep(0.5)

        raise ConnectionError(
            "Could not connect to Ableton. Make sure the Remote Script is running."
        )

    async def ping(self) -> bool:
        """Lightweight health check. Returns True if the connection is alive.

        Does not raise; returns False on any error.
        """
        try:
            async with self._lock:
                if not self.is_connected:
                    return False
                await self._send_and_receive("ping", timeout=3.0)
                return True
        except Exception:
            return False

    async def send_command(
        self,
        command_type: str,
        params: Dict[str, Any] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send a command to Ableton and return the response.

        If the connection drops mid-command, attempts to reconnect once and
        retry the command. This handles the common case of a prior timeout
        (e.g. from slow ``search_browser``) leaving the connection dead for
        the next call.

        Args:
            command_type: The command name recognised by the Remote Script.
            params: Optional dict of parameters for the command.
            timeout: Override the default read timeout (seconds) for slow
                     commands like browser search.  ``None`` keeps the
                     instance default.
        """
        async with self._lock:
            await self.ensure_connected()
            try:
                return await self._send_and_receive(
                    command_type, params, timeout=timeout
                )
            except (
                ConnectionError,
                BrokenPipeError,
                ConnectionResetError,
                OSError,
            ) as e:
                # Connection died — try reconnecting once and replaying
                logger.warning(
                    "Connection lost during '%s', reconnecting: %s",
                    command_type,
                    e,
                )
                await self._reconnect_or_raise()
                logger.info("Retrying '%s' after reconnect", command_type)
                return await self._send_and_receive(
                    command_type, params, timeout=timeout
                )
            except Exception as e:
                if self._is_timeout_error(e):
                    # Timeout errors also leave the connection in a bad state
                    logger.warning(
                        "Timeout during '%s', reconnecting: %s",
                        command_type,
                        e,
                    )
                    await self._reconnect_or_raise()
                    logger.info("Retrying '%s' after reconnect", command_type)
                    return await self._send_and_receive(
                        command_type, params, timeout=timeout
                    )
                raise

    async def send_batch(
        self, commands: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Send multiple commands in a single batch for efficiency.

        Falls back to sequential execution if the Remote Script
        doesn't support batch mode. Retries once on connection failure.
        """
        async with self._lock:
            await self.ensure_connected()
            try:
                return await self._execute_batch(commands)
            except (
                ConnectionError,
                BrokenPipeError,
                ConnectionResetError,
                OSError,
            ) as e:
                logger.warning("Connection lost during batch, reconnecting: %s", e)
                await self._reconnect_or_raise()
                logger.info("Retrying batch (%d commands) after reconnect", len(commands))
                return await self._execute_batch(commands)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _reconnect_or_raise(self):
        """Disconnect and re-establish the connection.

        Called from within the lock. Raises ConnectionError if reconnection
        fails — callers should NOT catch this, so we don't retry forever.
        """
        await self.disconnect()
        # Re-use ensure_connected logic (up to 3 TCP attempts)
        await self.ensure_connected()

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        """Check if an exception represents a timeout."""
        if isinstance(exc, asyncio.TimeoutError):
            return True
        # _send_and_receive wraps TimeoutError in a generic Exception
        return "Timeout waiting for Ableton response" in str(exc)

    async def _execute_batch(
        self, commands: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Execute a batch of commands (must be called inside the lock)."""
        batch = [
            {"type": cmd["type"], "params": cmd.get("params", {})}
            for cmd in commands
        ]
        payload = json.dumps(batch).encode("utf-8")

        try:
            self.writer.write(payload)
            await self.writer.drain()

            response_data = await self._read_json_response()
            responses = json.loads(response_data.decode("utf-8"))

            if isinstance(responses, list):
                results = []
                for resp in responses:
                    if resp.get("status") == "error":
                        results.append(
                            {"error": resp.get("message", "Unknown error")}
                        )
                    else:
                        results.append(resp.get("result", {}))
                return results
            else:
                # Server returned single response — batch not supported
                return [responses.get("result", {})]
        except Exception as e:
            logger.error("Batch command error: %s", e)
            self._connected = False
            raise

    async def _send_and_receive(
        self,
        command_type: str,
        params: Dict[str, Any] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send a single command and receive the response.

        This is the low-level method — it does NOT retry. Callers are
        responsible for reconnection logic.
        """
        command = {"type": command_type, "params": params or {}}

        try:
            self.writer.write(json.dumps(command).encode("utf-8"))
            await self.writer.drain()

            response_data = await self._read_json_response(timeout=timeout)
            response = json.loads(response_data.decode("utf-8"))

            if response.get("status") == "error":
                error_msg = response.get("message", "Unknown error from Ableton")
                # "Unknown command: ping" is NOT a connection error — it means
                # the Remote Script is alive but doesn't support ping yet.
                if "Unknown command: ping" in error_msg:
                    raise Exception(error_msg)
                raise Exception(error_msg)

            return response.get("result", {})
        except asyncio.TimeoutError:
            logger.error(
                "Timeout waiting for Ableton response (command=%s, timeout=%s)",
                command_type,
                timeout or self.timeout,
            )
            self._connected = False
            raise Exception(
                "Timeout waiting for Ableton response (command: {})".format(
                    command_type
                )
            )
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error("Connection error during '%s': %s", command_type, e)
            self._connected = False
            raise
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON response from '%s': %s", command_type, e)
            self._connected = False
            raise

    async def _read_json_response(self, timeout: Optional[float] = None) -> bytes:
        """Read a complete JSON response using incremental parsing."""
        effective_timeout = timeout if timeout is not None else self.timeout
        buffer = b""
        while True:
            chunk = await asyncio.wait_for(
                self.reader.read(8192), timeout=effective_timeout
            )
            if not chunk:
                if not buffer:
                    raise ConnectionError("Connection closed before receiving data")
                break

            buffer += chunk

            try:
                json.loads(buffer.decode("utf-8"))
                return buffer
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

        # Final check on accumulated buffer
        try:
            json.loads(buffer.decode("utf-8"))
            return buffer
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise Exception("Incomplete JSON response received")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_connection: Optional[AbletonConnection] = None


async def get_connection() -> AbletonConnection:
    """Get or create the global Ableton connection."""
    global _connection
    if _connection is None:
        _connection = AbletonConnection()
    await _connection.ensure_connected()
    return _connection


async def cleanup_connection():
    """Clean up the global connection on shutdown."""
    global _connection
    if _connection:
        await _connection.disconnect()
        _connection = None
