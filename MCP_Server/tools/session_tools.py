"""Session state tools for AbletonMCP."""
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("AbletonMCPServer")


def register(mcp: FastMCP, get_connection, cache):
    """Register session tools."""

    @mcp.tool()
    async def get_session() -> str:
        """Get the complete state of the current Ableton session in one call.

        Returns all tracks (with clips, devices), scenes, return tracks, master
        track, tempo, and time signature. Always use this instead of querying
        individual tracks — it's faster and gives you the full picture.
        """
        try:
            cached = cache.get("full_session")
            if cached is not None:
                return cached
            conn = await get_connection()
            result = await conn.send_command("get_full_session_state")
            response = json.dumps(result, indent=2)
            cache.set("full_session", response, ttl=3)
            return response
        except Exception as e:
            logger.error("Error getting session: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_clip_notes(track_index: int, clip_index: int) -> str:
        """Get the MIDI notes from a clip.

        Returns all notes with pitch, start_time, duration, velocity, and mute.

        Args:
            track_index: Track containing the clip.
            clip_index: Clip slot index.
        """
        try:
            cache_key = "clip_notes_{}_{}".format(track_index, clip_index)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            conn = await get_connection()
            result = await conn.send_command("get_clip_notes", {
                "track_index": track_index, "clip_index": clip_index,
            })
            response = json.dumps(result, indent=2)
            cache.set(cache_key, response, ttl=2)
            return response
        except Exception as e:
            logger.error("Error getting clip notes: %s", e)
            return json.dumps({"error": str(e)})
