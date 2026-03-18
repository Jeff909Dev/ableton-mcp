"""Scene and arrangement tools for AbletonMCP."""
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("AbletonMCPServer")


def register(mcp: FastMCP, get_connection, cache):
    """Register arrangement tools."""

    @mcp.tool()
    async def create_scene(name: str = "", index: int = -1) -> str:
        """Create a new scene in the session.

        Args:
            name: Scene name (e.g. "Intro", "Drop", "Breakdown"). Default empty.
            index: Position to insert (-1 = append at end). Default -1.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("create_scene", {"index": index})
            scene_index = result.get("scene_index", index)
            if name:
                await conn.send_command("set_scene_name", {
                    "scene_index": scene_index, "name": name,
                })
            cache.invalidate_all()
            return json.dumps({
                "status": "ok",
                "scene_index": scene_index,
                "name": name or "(unnamed)",
            }, indent=2)
        except Exception as e:
            logger.error("Error creating scene: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def duplicate_scene(scene_index: int) -> str:
        """Duplicate a scene (copies all clips to a new scene below).

        Args:
            scene_index: Index of the scene to duplicate.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("duplicate_scene", {"scene_index": scene_index})
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error duplicating scene: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def fire_scene(scene_index: int) -> str:
        """Launch a scene (trigger all clips in the scene row).

        Args:
            scene_index: Index of the scene to launch.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("fire_scene", {"scene_index": scene_index})
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error firing scene: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def stop_all() -> str:
        """Stop all playing clips in the session."""
        try:
            conn = await get_connection()
            result = await conn.send_command("stop_all_clips")
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error stopping clips: %s", e)
            return json.dumps({"error": str(e)})
