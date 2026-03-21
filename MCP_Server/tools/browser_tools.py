"""Browser navigation and loading tools for AbletonMCP.

These tools give the LLM direct access to Ableton's browser — searching for
instruments, effects, presets, and samples, navigating folder hierarchies
(including user-added sample libraries), and loading items onto tracks.

Use these when the production tools don't cover a workflow, or when you need
fine-grained control over sound selection.
"""
import json
import logging
from typing import Union
from urllib.parse import unquote
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("AbletonMCPServer")


def register(mcp: FastMCP, get_connection, cache):
    """Register browser tools."""

    @mcp.tool()
    async def search_browser(query: Union[str, int], category: str = "all") -> str:
        """Search Ableton's browser for instruments, effects, presets, and samples.

        Searches across Ableton's entire content library including factory packs,
        third-party packs, and user-added folders (Places section — artist sample
        packs, production libraries, etc.).

        Categories:
          - "all" — search everything (default)
          - "instruments" — Ableton instruments (Analog, Wavetable, Operator, etc.)
          - "sounds" — instrument presets organized by type (bass, keys, pad, lead)
          - "drums" — drum racks, kits, and individual drum hits
          - "audio_effects" — audio effects (Reverb, Compressor, EQ Eight, etc.)
          - "midi_effects" — MIDI effects (Arpeggiator, Chord, Scale, etc.)
          - "packs" — content from installed packs
          - "user_library" — user's own saved presets and content

        Each result includes:
          - name: display name of the item
          - is_folder: True if this is a folder you can navigate into with browse_folder
          - is_loadable: True if this can be loaded onto a track with load_browser_item
          - uri: unique identifier needed by load_browser_item (only present if loadable)

        Note: This searches the full browser tree which can be slow for
        broad queries. For user sample folders, prefer browse_folder() with
        the filter= parameter — it's faster and more reliable.

        Args:
            query: Search term — instrument name, preset, pack name, sample keyword, etc.
            category: Browser category to search. Default "all".
        """
        try:
            query = str(query)
            valid_categories = {
                "all", "instruments", "sounds", "drums",
                "audio_effects", "midi_effects", "packs", "user_library",
            }
            if category not in valid_categories:
                return json.dumps({
                    "error": "Unknown category: '{}'. Valid: {}".format(
                        category, ", ".join(sorted(valid_categories))),
                })

            cache_key = "browser_search_{}_{}".format(category, query)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            conn = await get_connection()
            try:
                result = await conn.send_command("search_browser", {
                    "query": query, "category_type": category,
                }, timeout=30.0)
            except Exception as first_err:
                # Browser search can be slow on large libraries — if we hit a
                # timeout or connection drop, reconnect and retry once.
                err_str = str(first_err)
                is_retryable = (
                    isinstance(first_err, (ConnectionError, BrokenPipeError, ConnectionResetError))
                    or "Timeout" in err_str
                    or "Connection closed" in err_str
                )
                if not is_retryable:
                    raise
                logger.warning("search_browser failed (%s), reconnecting and retrying", first_err)
                conn = await get_connection()
                result = await conn.send_command("search_browser", {
                    "query": query, "category_type": category,
                }, timeout=30.0)

            items = result.get("results", [])
            # Keep response compact
            compact = []
            for item in items:
                entry = {"name": item.get("name", "")}
                if item.get("is_folder"):
                    entry["folder"] = True
                    entry["path"] = item.get("path", "")
                if item.get("is_loadable"):
                    entry["loadable"] = True
                if item.get("uri"):
                    entry["uri"] = item["uri"]
                compact.append(entry)
            resp_obj = {
                "query": query,
                "count": len(compact),
                "results": compact,
            }
            # Surface timing / truncation info so the LLM can adapt
            if result.get("timed_out"):
                resp_obj["timed_out"] = True
                resp_obj["hint"] = (
                    "Search timed out before completing. Try a more "
                    "specific query or narrow the category."
                )
            if result.get("elapsed_seconds") is not None:
                resp_obj["elapsed_seconds"] = result["elapsed_seconds"]
            response = json.dumps(resp_obj, indent=2)
            cache.set(cache_key, response, ttl=30)
            return response
        except Exception as e:
            logger.error("Error searching browser: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def browse_folder(path: str, filter: Union[str, int] = "") -> str:
        """Navigate into a browser folder and list its contents.

        Use this to explore folder hierarchies found in search results or
        get_browser_tree output. Especially useful for browsing user sample
        libraries, pack contents, and preset categories.

        Use the 'filter' parameter to search within large folders instead
        of guessing exact folder names.

        Path formats:
          - User folders: "user_folders/FolderName/subfolder/..."
          - Categories: "Drums", "instruments", "sounds", etc.

        Returns items with: name, folder (bool), loadable (bool), uri.

        Args:
            path: Folder path to browse.
            filter: Optional name filter (case-insensitive). Only returns
                items whose name contains this string.
        """
        try:
            cache_key = "browser_folder_{}_{}".format(path, filter)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            conn = await get_connection()
            result = await conn.send_command("get_browser_items_at_path", {
                "path": path,
            })

            items = result.get("items", [])
            filter_lower = str(filter).strip().lower() if filter else ""

            # Keep response compact: name + folder/loadable + path for navigation
            compact_items = []
            for item in items:
                name = item.get("name", "")
                # Apply filter if provided
                if filter_lower and filter_lower not in name.lower():
                    continue
                entry = {"name": name}
                # Include full path so LLM can use it directly for navigation or loading
                entry["path"] = "{}/{}".format(path, name)
                if item.get("is_folder"):
                    entry["folder"] = True
                if item.get("is_loadable"):
                    entry["loadable"] = True
                uri = item.get("uri", "")
                if uri:
                    entry["uri"] = uri
                    # Extract real file path for create_audio_clip
                    if uri.startswith("userfolder:"):
                        try:
                            decoded = unquote(uri[len("userfolder:"):])
                            root, _, sub = decoded.partition("#")
                            if sub:
                                entry["file_path"] = "{}/{}".format(root, sub.replace(":", "/"))
                        except Exception:
                            pass
                compact_items.append(entry)
            resp = {
                "path": path,
                "count": len(compact_items),
                "items": compact_items,
            }
            if filter_lower:
                resp["filter"] = filter
            response = json.dumps(resp, indent=2)
            cache.set(cache_key, response, ttl=30)
            return response
        except Exception as e:
            logger.error("Error browsing folder: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def load_browser_item(track_index: int, uri: str) -> str:
        """Load a browser item (instrument, effect, preset, or sample) onto a track.

        Works with any loadable item from search_browser or browse_folder results.
        The URI uniquely identifies the item in Ableton's browser.

        Loading behavior:
          - Instrument presets (.adg): loads the instrument with all its settings
          - Audio effects: added to the track's device chain
          - WAV/AIF/FLAC samples: creates a Simpler device with the sample loaded.
            If the target track already has a Drum Rack with a pad selected, the
            sample loads into that pad instead (useful for building custom kits).
          - MIDI effects: added to the track's MIDI effect chain

        Always get the URI from search_browser or browse_folder results — do not
        construct URIs manually.

        Args:
            track_index: Track to load the item onto (0-based index).
            uri: The item's URI from search_browser or browse_folder results.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("load_browser_item", {
                "track_index": track_index, "item_uri": uri,
            })
            cache.invalidate_all()
            return json.dumps({
                "status": "loaded",
                "track_index": track_index,
                "uri": uri,
                "detail": result,
            }, indent=2)
        except Exception as e:
            logger.error("Error loading browser item: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_browser_tree(category: str = "instruments") -> str:
        """Get the hierarchical folder tree of a browser category.

        Returns the top-level structure of a browser category, useful for
        discovering what's available before searching. Shows folders you
        can navigate into with browse_folder.

        Categories:
          - "instruments" — Ableton instruments (Analog, Drift, Operator, etc.)
          - "sounds" — preset categories (Bass, Keys, Lead, Pad, etc.)
          - "drums" — drum racks and kits
          - "audio_effects" — audio effect devices
          - "midi_effects" — MIDI effect devices
          - "packs" — installed content packs
          - "user_library" — user's own presets and content

        Use this when you want to understand the overall structure before diving
        in with search_browser or browse_folder.

        Args:
            category: Browser category to get the tree for. Default "instruments".
        """
        try:
            valid_categories = {
                "instruments", "sounds", "drums",
                "audio_effects", "midi_effects", "packs", "user_library",
            }
            if category not in valid_categories:
                return json.dumps({
                    "error": "Unknown category: '{}'. Valid: {}".format(
                        category, ", ".join(sorted(valid_categories))),
                })

            cache_key = "browser_tree_{}".format(category)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            conn = await get_connection()
            result = await conn.send_command("get_browser_tree", {
                "category_type": category,
            })

            response = json.dumps({
                "category": category,
                "tree": result,
            }, indent=2)
            cache.set(cache_key, response, ttl=60)
            return response
        except Exception as e:
            logger.error("Error getting browser tree: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def list_user_folders() -> str:
        """List the user's custom folders added to Ableton's browser (Places).

        Call this when the user mentions any artist, sample pack, or library
        by name. Returns top-level folder names.

        Use browse_folder() with filter= to search inside large folders
        without needing to know the exact folder name.

        Workflow for user sample packs:
          1. list_user_folders() → discover available folders
          2. browse_folder(folder_path, filter="search term") → find content
          3. browse_folder(subfolder_path) → find WAV/AIF samples with URIs
          4. load_browser_item or load_sample_to_drum_pad to load them
        """
        try:
            cache_key = "browser_user_folders"
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            conn = await get_connection()
            result = await conn.send_command("get_browser_items_at_path", {
                "path": "user_folders",
            })

            items = result.get("items", [])
            folders = []
            for item in items:
                folders.append({
                    "name": item.get("name", ""),
                    "path": "user_folders/{}".format(item.get("name", "")),
                    "is_folder": item.get("is_folder", True),
                })

            response = json.dumps({
                "folder_count": len(folders),
                "folders": folders,
                "tip": "Use browse_folder with the path to explore any folder",
            }, indent=2)
            cache.set(cache_key, response, ttl=30)
            return response
        except Exception as e:
            logger.error("Error listing user folders: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def load_sample_to_drum_pad(
        track_index: int, pad_note: int, uri: str,
    ) -> str:
        """Load a sample (WAV/AIF) into a specific pad of a Drum Rack.

        Use this to build custom drum kits from individual samples. Each pad
        in a Drum Rack corresponds to a MIDI note. When you load a sample into
        a pad, Ableton creates a Simpler device inside that pad's chain.

        Standard GM drum mapping (most common):
          - 36 (C1): Kick
          - 37 (C#1): Rim / Side Stick
          - 38 (D1): Snare
          - 39 (D#1): Clap
          - 42 (F#1): Closed Hi-Hat
          - 46 (A#1): Open Hi-Hat
          - 43 (G1): Low Tom
          - 47 (B1): Mid Tom
          - 50 (D2): High Tom
          - 49 (C#2): Crash
          - 51 (D#2): Ride

        The target track MUST already have a Drum Rack loaded on it. Use
        load_browser_item to load a Drum Rack first, then use this tool to
        fill individual pads with samples.

        Workflow:
          1. Create a MIDI track
          2. search_browser("Drum Rack", "drums") to find a Drum Rack
          3. load_browser_item(track, drum_rack_uri) to load it
          4. browse_folder(path_to_drums_subfolder) to find kick/snare WAVs
          5. load_sample_to_drum_pad(track, 36, kick_uri) for the kick pad
          6. Repeat for snare (38), hats (42, 46), etc.

        Args:
            track_index: Track that has a Drum Rack loaded (0-based index).
            pad_note: MIDI note of the target pad (0-127). See mapping above.
            uri: URI of the sample from search_browser or browse_folder results.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("load_sample_to_drum_pad", {
                "track_index": track_index,
                "pad_note": pad_note,
                "item_uri": uri,
            })
            cache.invalidate_all()
            return json.dumps({
                "status": "loaded",
                "track_index": track_index,
                "pad_note": pad_note,
                "detail": result,
            }, indent=2)
        except Exception as e:
            logger.error("Error loading sample to drum pad: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def build_drum_rack(
        track_index: int,
        pad_samples: list,
    ) -> str:
        """Build a complete drum rack in ONE call: loads Drum Rack + all samples.

        This is MUCH faster than calling load_browser_item + load_sample_to_drum_pad
        individually for each sample. Does everything server-side in a single
        round-trip.

        First use browse_folder to find sample paths/URIs, then pass them here.

        Args:
            track_index: Track to load the Drum Rack onto (must be a MIDI track).
            pad_samples: List of dicts, each with:
                - pad_note (int): MIDI note for the pad (36=kick, 38=snare, 42=hat, etc.)
                - path_or_uri (str): Path or URI of the sample from browse_folder results.
                  Can be a navigable path like "user_folders/MyPack/Drums/Kicks/kick.wav"
                  or a URI from browse results.

        Example:
            build_drum_rack(track_index=0, pad_samples=[
                {"pad_note": 36, "path_or_uri": "user_folders/Pack/Kicks/kick1.wav"},
                {"pad_note": 38, "path_or_uri": "user_folders/Pack/Snares/snare1.wav"},
                {"pad_note": 42, "path_or_uri": "user_folders/Pack/Hats/hat1.wav"},
            ])
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("build_drum_rack", {
                "track_index": track_index,
                "pad_samples": pad_samples,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error building drum rack: %s", e)
            return json.dumps({"error": str(e)})
