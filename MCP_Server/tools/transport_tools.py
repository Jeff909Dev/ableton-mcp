"""Transport and playback tools for AbletonMCP."""
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("AbletonMCPServer")


def register(mcp: FastMCP, get_connection, cache):
    """Register transport tools."""

    @mcp.tool()
    async def play() -> str:
        """Start playback."""
        try:
            conn = await get_connection()
            result = await conn.send_command("start_playback")
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error starting playback: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def stop() -> str:
        """Stop playback."""
        try:
            conn = await get_connection()
            result = await conn.send_command("stop_playback")
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error stopping playback: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def set_tempo(bpm: float) -> str:
        """Set the session tempo.

        Args:
            bpm: Tempo in BPM (20-999).
        """
        try:
            bpm = max(20.0, min(999.0, bpm))
            conn = await get_connection()
            result = await conn.send_command("set_tempo", {"tempo": bpm})
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error setting tempo: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def undo() -> str:
        """Undo the last action in Ableton."""
        try:
            conn = await get_connection()
            result = await conn.send_command("undo")
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error undoing: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def redo() -> str:
        """Redo the last undone action in Ableton."""
        try:
            conn = await get_connection()
            result = await conn.send_command("redo")
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error redoing: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def capture_midi() -> str:
        """Capture recently played MIDI into a new clip.

        Records MIDI that was played while not in record mode.
        Requires Ableton Live 10.1 or later.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("capture_midi")
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error capturing MIDI: %s", e)
            return json.dumps({"error": str(e)})
