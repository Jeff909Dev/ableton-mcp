"""Device and instrument tools for AbletonMCP."""
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("AbletonMCPServer")


def register(mcp: FastMCP, get_connection, cache):
    """Register device tools."""

    @mcp.tool()
    async def find_and_load_instrument(track_index: int, query: str, category: str = "") -> str:
        """Find an instrument/effect in Ableton's browser and load it onto a track.

        Browses Ableton's built-in categories to find matching items by name.
        Much faster than search_browser for common instruments.

        Args:
            track_index: Track to load the instrument onto.
            query: Name to search for (e.g. "Drum Rack", "Analog", "909", "Reverb").
            category: Browser category to search. Leave empty to try common
                categories automatically. Options: "instruments", "drums",
                "sounds", "audio_effects", "midi_effects".
        """
        try:
            conn = await get_connection()

            # Determine which categories to search
            if category:
                categories_to_try = [category]
            else:
                # Smart category guessing based on query
                q = query.lower()
                if any(k in q for k in ("drum", "kit", "808", "909", "perc")):
                    categories_to_try = ["drums", "instruments"]
                elif any(k in q for k in ("reverb", "delay", "comp", "eq", "filter", "chorus")):
                    categories_to_try = ["audio_effects"]
                elif any(k in q for k in ("arp", "chord", "scale", "note")):
                    categories_to_try = ["midi_effects"]
                else:
                    categories_to_try = ["sounds", "instruments", "drums"]

            # Browse each category with filter
            for cat in categories_to_try:
                try:
                    result = await conn.send_command("get_browser_items_at_path", {
                        "path": cat.capitalize() if cat in ("drums", "instruments", "sounds") else cat,
                    })
                    items = result.get("items", [])
                    query_lower = query.lower()
                    for item in items:
                        name = item.get("name", "")
                        if query_lower in name.lower() and item.get("is_loadable"):
                            uri = item.get("uri", "")
                            if uri:
                                await conn.send_command("load_browser_item", {
                                    "track_index": track_index, "item_uri": uri,
                                })
                                cache.invalidate_all()
                                return json.dumps({
                                    "status": "loaded",
                                    "track_index": track_index,
                                    "instrument": name,
                                    "category": cat,
                                }, indent=2)
                except Exception:
                    continue

            return json.dumps({
                "error": "No loadable match for '{}' in {}".format(query, categories_to_try),
                "tip": "Use browse_folder to navigate categories manually.",
            })
        except Exception as e:
            logger.error("Error loading instrument: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_device_parameters(track_index: int, device_index: int) -> str:
        """Get all parameters of a device on a track.

        Returns parameter names, current values, min/max ranges, and whether
        they're quantized. Use this before tweak_device to see what's available.

        Args:
            track_index: Track containing the device.
            device_index: Device position on the track (0-based).
        """
        try:
            cache_key = "device_params_{}_{}".format(track_index, device_index)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            conn = await get_connection()
            result = await conn.send_command("get_device_parameters", {
                "track_index": track_index, "device_index": device_index,
            })
            response = json.dumps(result, indent=2)
            cache.set(cache_key, response, ttl=2)
            return response
        except Exception as e:
            logger.error("Error getting device parameters: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def tweak_device(
        track_index: int,
        device_index: int,
        parameter_name: str,
        value: float,
    ) -> str:
        """Adjust a device parameter by name.

        Use get_device_parameters first to see available parameters and ranges.

        Args:
            track_index: Track containing the device.
            device_index: Device position on the track (0-based).
            parameter_name: Parameter name (e.g. "Filter Freq", "Cutoff", "Decay").
            value: New value (check ranges with get_device_parameters).
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("set_device_parameter_by_name", {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_name": parameter_name,
                "value": value,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error tweaking device: %s", e)
            return json.dumps({"error": str(e)})
