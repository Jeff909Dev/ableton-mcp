"""Track management tools for AbletonMCP."""
import json
import logging
from typing import Optional
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("AbletonMCPServer")


def register(mcp: FastMCP, get_connection, cache):
    """Register track tools."""

    @mcp.tool()
    async def create_track(type: str = "midi", name: str = "") -> str:
        """Create a new track.

        Args:
            type: "midi" or "audio". Default "midi".
            name: Track name. Default empty (Ableton assigns default name).
        """
        try:
            conn = await get_connection()
            command = "create_midi_track" if type == "midi" else "create_audio_track"
            result = await conn.send_command(command, {"index": -1})
            track_index = result.get("index", 0)
            if name:
                await conn.send_command("set_track_name", {
                    "track_index": track_index, "name": name,
                })
            cache.invalidate_all()
            return json.dumps({
                "status": "ok",
                "track_index": track_index,
                "type": type,
                "name": name or "(default)",
            }, indent=2)
        except Exception as e:
            logger.error("Error creating track: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def delete_track(track_index: int) -> str:
        """Delete a track.

        Args:
            track_index: Index of the track to delete.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("delete_track", {"track_index": track_index})
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error deleting track: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def set_track_name(track_index: int, name: str) -> str:
        """Rename a track.

        Args:
            track_index: Index of the track.
            name: New name for the track.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("set_track_name", {
                "track_index": track_index, "name": name,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error renaming track: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def mix_track(
        track_index: int,
        volume: Optional[float] = None,
        pan: Optional[float] = None,
        mute: Optional[bool] = None,
        solo: Optional[bool] = None,
    ) -> str:
        """Adjust a track's mixer settings in one call.

        All parameters are optional — only the ones you provide will be changed.

        Args:
            track_index: Index of the track.
            volume: Volume (0.0 to 1.0, where ~0.85 = 0dB). Optional.
            pan: Pan (-1.0 = left, 0.0 = center, 1.0 = right). Optional.
            mute: Mute state. Optional.
            solo: Solo state. Optional.
        """
        try:
            conn = await get_connection()
            changes = []

            if volume is not None:
                await conn.send_command("set_track_volume", {
                    "track_index": track_index, "volume": volume,
                })
                changes.append("volume={}".format(volume))

            if pan is not None:
                await conn.send_command("set_track_pan", {
                    "track_index": track_index, "pan": pan,
                })
                changes.append("pan={}".format(pan))

            if mute is not None:
                await conn.send_command("set_track_mute", {
                    "track_index": track_index, "mute": mute,
                })
                changes.append("mute={}".format(mute))

            if solo is not None:
                await conn.send_command("set_track_solo", {
                    "track_index": track_index, "solo": solo,
                })
                changes.append("solo={}".format(solo))

            if not changes:
                return json.dumps({"status": "no changes", "track_index": track_index})

            cache.invalidate_all()
            return json.dumps({
                "status": "ok",
                "track_index": track_index,
                "changes": changes,
            }, indent=2)
        except Exception as e:
            logger.error("Error mixing track: %s", e)
            return json.dumps({"error": str(e)})
