"""AbletonMCP Server - MCP server for Ableton Live integration.

Producer-focused tool architecture (39 tools):
- Production: create_beat, create_bassline, create_melody, create_chords, create_pad
- Session: get_session, get_clip_notes
- Arrangement: create_scene, duplicate_scene, fire_scene, stop_all
- Tracks: create_track, delete_track, set_track_name, mix_track
- Clips: create_audio_clip, create_clip, add_notes_to_clip, delete_clip, duplicate_clip, get_audio_clip_info, set_clip_pitch, set_clip_warp
- Devices: find_and_load_instrument, get_device_parameters, tweak_device
- Browser: search_browser, browse_folder, load_browser_item, load_sample_to_drum_pad, build_drum_rack, get_browser_tree, list_user_folders
- Transport: play, stop, set_tempo, undo, redo, capture_midi
"""
from mcp.server.fastmcp import FastMCP
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any

from MCP_Server.connection import get_connection, cleanup_connection
from MCP_Server.cache import ResponseCache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("AbletonMCPServer")

cache = ResponseCache(default_ttl=2.0)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        try:
            conn = await get_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning("Could not connect to Ableton on startup: %s", e)
            logger.warning("Make sure the Ableton Remote Script is running")
        yield {}
    finally:
        await cleanup_connection()
        logger.info("AbletonMCP server shut down")


mcp = FastMCP("AbletonMCP", lifespan=server_lifespan)

# ---------------------------------------------------------------------------
# Register tool modules (28 tools total)
# ---------------------------------------------------------------------------
from MCP_Server.tools import (
    production_tools,
    session_tools,
    arrangement_tools,
    track_tools,
    clip_tools,
    device_tools,
    transport_tools,
    browser_tools,
)

production_tools.register(mcp, get_connection, cache)
session_tools.register(mcp, get_connection, cache)
arrangement_tools.register(mcp, get_connection, cache)
track_tools.register(mcp, get_connection, cache)
clip_tools.register(mcp, get_connection, cache)
device_tools.register(mcp, get_connection, cache)
transport_tools.register(mcp, get_connection, cache)
browser_tools.register(mcp, get_connection, cache)


def main():
    """Run the MCP server"""
    mcp.run()


if __name__ == "__main__":
    main()
