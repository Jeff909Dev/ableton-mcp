# AbletonMCP — Project Guide

## Architecture

Two-component system communicating via TCP JSON on port 9877:

1. **MCP Server** (`MCP_Server/`) — Python async server using FastMCP. 39 tools in 8 modules under `MCP_Server/tools/`.
2. **Ableton Remote Script** (`AbletonMCP_Remote_Script/__init__.py`) — Runs inside Ableton's Python runtime. Socket server that receives commands and executes them via Ableton's Live API.

## Tool Architecture (39 tools, producer-focused)

| Module | Tools | Purpose |
|--------|-------|---------|
| `production_tools.py` (5) | `create_beat`, `create_bassline`, `create_melody`, `create_chords`, `create_pad` | Quick workflows: create track + generate pattern + write notes + try to load sound |
| `browser_tools.py` (7) | `search_browser`, `browse_folder`, `load_browser_item`, `load_sample_to_drum_pad`, `build_drum_rack`, `get_browser_tree`, `list_user_folders` | Navigate Ableton's browser, find/load instruments and samples, build custom drum kits |
| `session_tools.py` (2) | `get_session`, `get_clip_notes` | Read session state |
| `arrangement_tools.py` (4) | `create_scene`, `duplicate_scene`, `fire_scene`, `stop_all` | Scene/arrangement |
| `track_tools.py` (4) | `create_track`, `delete_track`, `set_track_name`, `mix_track` | Track management |
| `clip_tools.py` (8) | `create_audio_clip`, `create_clip`, `add_notes_to_clip`, `delete_clip`, `duplicate_clip`, `get_audio_clip_info`, `set_clip_pitch`, `set_clip_warp` | Clip operations + audio clip management |
| `device_tools.py` (3) | `find_and_load_instrument`, `get_device_parameters`, `tweak_device` | Instruments & effects |
| `transport_tools.py` (6) | `play`, `stop`, `set_tempo`, `undo`, `redo`, `capture_midi` | Transport |

### Two ways to create music: Production tools vs Browser + Primitives

**Production tools** (quick, opinionated) — Each handles a full workflow: create track, generate pattern, write notes, try to load a sound. Only searches built-in content.

**Browser tools + primitives** (flexible, precise) — The LLM composes its own workflow. Preferred when:
- The user names a specific artist/pack or user library content
- Building custom drum kits from individual samples
- Loading audio loops into specific clip slots
- Production tools failed to load the right instrument

**Workflow for user sample packs (single hits → drum rack):**
1. `list_user_folders()` → discover folders
2. `browse_folder(folder_path, filter="artist")` → find the pack
3. `browse_folder(pack_path)` → see subfolders
4. `browse_folder(drums_path)` → find WAVs with URIs and file_paths
5. `build_drum_rack(track, [{pad_note: 36, path_or_uri: kick_path}, ...])` → one call builds entire kit

**Workflow for audio loops (into specific clip slots):**
1. `browse_folder(path, filter="loop")` → find loop WAVs (includes `file_path`)
2. `create_track(type="audio")` → create audio track
3. `create_audio_clip(track, clip_index, file_path)` → load loop into ANY scene slot
4. `set_clip_warp(track, clip_index, warping=True, warp_mode=6)` → warp for tempo sync
5. `set_clip_pitch(track, clip_index, semitones=3)` → transpose to match key

### Ableton instrument types (what needs what)

| Type | Examples | Needs samples? | Notes |
|------|----------|---------------|-------|
| Synths | Analog, Wavetable, Operator, Drift | No — generates sound | Just load and write MIDI |
| Sampler instruments | Simpler, Sampler | Yes — needs a sample loaded | WAVs auto-create a Simpler |
| Drum Rack | Drum Rack | Yes — needs samples in pads | Use `build_drum_rack` or `load_sample_to_drum_pad` |
| Preset kits | "909 Kit", "Acoustic Kit" | No — preset includes samples | Load the preset directly |
| Audio effects | Reverb, Compressor, EQ | N/A | Chain onto existing devices |

### Key detection and transpose

`clip_tools.py` has helper functions for audio loop workflows:
- `_parse_key_from_name("Bass_Am_125bpm.wav")` → `"Am"`
- `_parse_bpm_from_name("Bass_Am_125bpm.wav")` → `125`
- `_transpose_semitones("Am", "Cm")` → `3`

### Pattern generation pipeline

- **Drums**: Template-based with 3-4 variations per style + humanization. Styles: house, techno, rock, hiphop, trap, dnb, reggaeton, bossa_nova, jazz_swing, funk, basic.
- **Bass/Synth/Keys/Chords/Pads/Melody**: PatternEngine (search → pick → adapt → vary) using 1105 real MIDI patterns from `midi_patterns/`.
- **Chord progressions**: Roman numeral parsing with presets (pop, jazz, blues, rock, sad, epic, house, reggaeton, andalusian).

### GM Drum Mapping

| Note | Pitch | Drum |
|------|-------|------|
| C1 | 36 | Kick |
| C#1 | 37 | Rim / Side Stick |
| D1 | 38 | Snare |
| D#1 | 39 | Clap |
| F#1 | 42 | Closed Hi-Hat |
| A#1 | 46 | Open Hi-Hat |
| G1 | 43 | Low Tom |
| B1 | 47 | Mid Tom |
| D2 | 50 | High Tom |
| C#2 | 49 | Crash |
| D#2 | 51 | Ride |

## Ableton Live API Reference (Live Object Model)

The Remote Script interacts with Ableton via the **Live Object Model (LOM)** — an undocumented Python API. When unsure about any API detail, search the web for the official API stubs and decompiled scripts.

### Key references
- **API Stubs**: https://github.com/cylab/AbletonLive-API-Stub
- **Decompiled Scripts (Live 12)**: https://github.com/gluon/AbletonLive12_MIDIRemoteScripts
- **Decompiled Scripts (Live 11)**: https://github.com/gluon/AbletonLive11_MIDIRemoteScripts
- **Community reference**: https://structure-void.com/ableton-live-midi-remote-scripts/

### Browser API (critical for sample loading)

```
Browser (app.browser)
├── .instruments        — BrowserItem root for instruments
├── .sounds             — BrowserItem root for presets by type
├── .drums              — BrowserItem root for drum kits/hits
├── .audio_effects      — BrowserItem root for audio FX
├── .midi_effects       — BrowserItem root for MIDI FX
├── .packs              — BrowserItem root for installed packs
├── .user_library       — BrowserItem root for user presets
├── .user_folders       — list of BrowserItems for Places folders
├── .load_item(item)    — loads a BrowserItem onto selected track/pad
└── .hotswap_target     — current hotswap target device

BrowserItem
├── .name               — display name (str)
├── .children           — child BrowserItems (iterable)
├── .uri                — unique identifier string
├── .is_loadable        — True if load_item() works on it
├── .is_folder          — True if it's a navigable folder
└── .is_device          — True if it's an instrument/effect
```

### Audio Clip API (for loop loading and transpose)

```
Clip (audio clips only, where clip.is_audio_clip == True)
├── .pitch_coarse       — semitone transpose (-48 to 48, read/write)
├── .pitch_fine         — fine pitch in cents (-500 to 500, read/write)
├── .warping            — enable time-stretching (bool, read/write)
├── .warp_mode          — warp algorithm (int 0-6, read/write)
│   0=beats, 1=complex, 2=complex_pro, 3=repitch, 4=rex, 5=texture, 6=tones
├── .gain               — clip gain (float, read/write)
├── .file_path          — source audio file path (str, read-only)
└── .sample_length      — length in samples (int, read-only)

ClipSlot
└── .create_audio_clip(file_path)  — Live 12+ only, loads audio into specific slot
```

### How browser loading works

1. `browser.load_item(item)` needs a **BrowserItem object**, not a URI string
2. To load items, navigate the tree via `.children` to get the object
3. Path-based navigation (`_find_browser_item_by_path`) is fast — walks directly
4. URI-based search (`_find_browser_item_by_uri`) is slow — recursive, avoid when possible
5. For drum pads: select pad via `drum_rack.view.selected_drum_pad = pad`, then `load_item()`
6. **No search API exists** on the Browser — only tree navigation via `.children`

### When unsure about the API

Search the web: `site:github.com cylab AbletonLive-API-Stub ClassName method_name`

## Claude Code Configuration

- **`.mcp.json`**: Configures the Ableton MCP server for Claude Code. Server name is `ableton`, so tools appear as `mcp__ableton__<tool_name>`.
- **`.claude/settings.json`**: Contains PreToolUse hook configuration.
- **`.claude/hooks/ableton-pretool.mjs`**: PreToolUse hook that runs before every Ableton MCP tool call. It:
  1. **Fixes numeric string coercion** — converts `909` (int) to `"909"` (str) for parameters like `sound`, `query`, `name` that Pydantic expects as strings. Numeric params (`track_index`, `bars`, `pad_note`, etc.) are left as numbers.
  2. **Validates enum values** — warns about invalid `style`, `category`, `type`, and `warp_mode` values.

### Known pitfalls

- **Numeric-looking strings**: Values like "909", "808", "303" get JSON-serialized as integers. The PreToolUse hook fixes this automatically.
- **Connection timeouts**: The Remote Script socket can drop if Ableton is busy (loading samples, rendering). Retry after connection lost errors.
- **Browser search is slow**: `search_browser` does recursive tree traversal. Prefer `browse_folder` with a known path, or `find_and_load_instrument` for instruments.
- **Instrument load failures are silent**: Production tools (`create_beat`, etc.) generate MIDI notes even when the instrument fails to load. Always check the result message for "no instrument loaded" warnings.

## Key Constraints

- **Remote Script must stay Python 2/3 compatible**: uses `from __future__` imports, `.format()`, `Queue`/`queue` dual import. No f-strings.
- **Remote Script is a single file**: Ableton loads `__init__.py` from the Remote Scripts folder.
- **State-modifying commands must use `schedule_message`**: Ableton's API is not thread-safe. Write commands go through `self.schedule_message(0, callback)` with a Queue.
- **MCP Server tools are async**: All tools use `async def` and `await conn.send_command(...)`.
- **No hardcoded user data in tool descriptions**: Never put user-specific folder names, artist names, or paths in tool descriptions. Keep them generic.
- **Prefer path browsing over search**: Internal function `_find_browser_item_by_path` (used by `browse_folder`, `find_and_load_instrument`) walks the tree directly. `search_browser` does recursive traversal and can timeout on large libraries.

## Adding New Tools

1. Add handler in `AbletonMCP_Remote_Script/__init__.py`: register in `_command_handlers`, add to `_read_commands` or `_write_commands`
2. Add MCP tool in appropriate `MCP_Server/tools/*_tools.py` module
3. Follow the `register(mcp, get_connection, cache)` pattern

## Performance Notes

- Response cache: session 3s, device params 2s, browser 30s, tree 60s
- `get_session` returns everything in 1 call — prefer over N+1 queries
- `build_drum_rack` loads Drum Rack + all samples in 1 round-trip
- `create_audio_clip` loads loops into specific clip slots (Live 12+)
- `find_and_load_instrument` uses direct browsing, not recursive search
- Connection timeout: 15s

## Testing

- Pattern generation: `uv run python -c "from MCP_Server.tools.pattern_generator import generate_humanized_drums; print(len(generate_humanized_drums('house', 2)))"`
- Server import: `uv run python -c "from MCP_Server.server import mcp; print(len(mcp._tool_manager._tools))"`
- Full test requires Ableton running with Remote Script loaded

## Installation

Run `./install.sh` or manually:
- MCP Server: `uv pip install -e .`
- Remote Script: copy `AbletonMCP_Remote_Script/__init__.py` to Ableton's `User Remote Scripts/AbletonMCP/`
- Restart script: `./scripts/restart_ableton.sh`
