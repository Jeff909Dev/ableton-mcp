# AbletonMCP - Ableton Live + AI via Model Context Protocol

Connect Ableton Live to AI assistants (Claude, Cursor, etc.) and control your DAW with natural language. Create tracks, load samples from your library, generate drum patterns, build custom kits, load audio loops — all through conversation.

---

> **This is a fork.** The original project was created by [Siddharth Ahuja](https://x.com/sidahuj) ([original repo](https://github.com/ahujasid/ableton-mcp)). Huge thanks to Siddharth for building this and sharing it with the world. I picked up this project to experiment and push it further — particularly around user library browsing, sample loading, and audio loop workflows.

---

## What can it do?

- *"Make me a house beat with Sidney Charles samples"* → browses your library, finds the pack, builds a drum rack from individual hits
- *"Load loops from Chris Stussy, Cuartero, and East End Dubs into different scenes"* → creates audio tracks, loads loops into specific clip slots
- *"Create a bassline in Am with Analog"* → generates a pattern from real MIDI, loads the synth
- *"Set the tempo to 126 and add reverb to track 2"*
- *"Transpose the loop on track 3 up 3 semitones"*

## Features

**39 tools** organized in 8 categories:

| Category | What you get |
|----------|-------------|
| **Production** | One-call workflows: create_beat, create_bassline, create_melody, create_chords, create_pad |
| **Browser** | Navigate Ableton's browser, search content, browse user folders, load instruments/samples |
| **Session** | Full session snapshots, clip note data |
| **Tracks** | Create (MIDI/audio), delete, rename, mix (volume/pan/mute/solo) |
| **Clips** | Create MIDI clips, load audio clips into specific slots, transpose, warp |
| **Arrangement** | Create/duplicate/fire scenes, stop all |
| **Devices** | Find and load instruments, get/set device parameters |
| **Transport** | Play, stop, tempo, undo/redo, capture MIDI |

### User Library Browsing

Browse your own sample packs and production libraries — not just Ableton's built-in content:

- `list_user_folders()` — discover what packs you have
- `browse_folder(path, filter="keyword")` — search within large folders
- `build_drum_rack(track, samples)` — load Drum Rack + all samples in one call
- `create_audio_clip(track, clip_index, file_path)` — load loops into any scene slot (Live 12+)

### Pattern Generation

The MCP includes **1105 real MIDI patterns** organized by category:

| Category | Patterns |
|----------|----------|
| Bass | 385 |
| Synth | 250 |
| Keys | 150 |
| Chords | 96 |
| Drums | 72 (+ 3-4 template variations per style) |
| Pads | 50 |
| Melody | 27 |

Drums use template-based generation with multiple variations per style (house, techno, hiphop, trap, etc.) plus humanization. Melodic content uses a search-pick-adapt-vary pipeline over real MIDI patterns.

### Audio Clip Support

- Load audio loops into specific clip slots with `create_audio_clip`
- Transpose audio clips with `set_clip_pitch` (-48 to +48 semitones)
- Set warp mode with `set_clip_warp` (beats, complex, tones, etc.)
- Read clip properties with `get_audio_clip_info`
- Key detection from filenames (parses "Bass_Am_125bpm.wav" → key=Am, bpm=125)

## Architecture

```
┌──────────────┐        ┌─────────────────────────────┐       ┌───────────────────┐
│  AI Client   │◄─MCP──►│  MCP Server                 │◄─TCP─►│  Ableton Live     │
│  (Claude,    │        │  (Python, 39 tools)          │ :9877 │                   │
│   Cursor)    │        │                              │       │  Remote Script    │
└──────────────┘        │  Pattern generator           │       │  (__init__.py)    │
                        │  Key/BPM detection           │       │                   │
                        │  Response cache              │       │  Executes via     │
                        └─────────────────────────────┘       │  Ableton Live API │
                                                               └───────────────────┘
```

**Two components:**

1. **MCP Server** — Python process on your machine. Generates patterns, manages tools, communicates with AI clients and Ableton.
2. **Remote Script** — Single Python file inside Ableton. Thin TCP bridge that receives commands and executes them via Ableton's Live Object Model API.

## Installation

### Prerequisites

- Ableton Live 11+ (Live 12 recommended for audio clip features)
- Python 3.10+
- [uv](https://astral.sh/uv) (`brew install uv` on Mac)

### Quick install (macOS)

```bash
git clone https://github.com/Jeff909Dev/ableton-mcp.git
cd ableton-mcp
./install.sh
```

### Manual install

**1. MCP Server:**

```bash
cd ableton-mcp
uv venv && uv pip install -e .
```

**2. Remote Script** — copy `AbletonMCP_Remote_Script/__init__.py` to:

- **macOS:** `~/Library/Preferences/Ableton/Live XX/User Remote Scripts/AbletonMCP/`
- **Windows:** `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\AbletonMCP\`

**3. Enable in Ableton:** Settings → Link, Tempo & MIDI → Control Surface → "AbletonMCP" → Input/Output: None

### Configure your AI client

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "AbletonMCP": {
      "command": "ableton-mcp"
    }
  }
}
```

**Cursor** — Settings → MCP → add command: `ableton-mcp`

## Project structure

```
MCP_Server/
  server.py              # Entry point, registers all tool modules
  connection.py          # Async TCP connection with batch support
  cache.py               # Response cache with TTL
  tools/
    production_tools.py  # Quick creation workflows (beat, bass, melody, chords, pad)
    browser_tools.py     # Browser navigation, sample loading, drum rack building
    session_tools.py     # Session state reading
    track_tools.py       # Track management
    clip_tools.py        # Clip operations + audio clip pitch/warp/key detection
    arrangement_tools.py # Scene management
    device_tools.py      # Device parameters and instrument loading
    transport_tools.py   # Transport controls
    pattern_generator.py # PatternEngine + drum templates + humanization

AbletonMCP_Remote_Script/
  __init__.py            # Runs inside Ableton (TCP bridge to Live API)

midi_patterns/           # 1105 MIDI files organized by category
  bass/ synth/ keys/ chords/ drums/ pads/ melody/
  index.json             # Parsed pattern index

scripts/
  build_pattern_index.py # Parse MIDI files into index.json
  restart_ableton.sh     # Restart Ableton (used after Remote Script updates)
```

## Performance Tips

- **Model selection**: Use Haiku in Claude Desktop for faster responses on simple tasks
- **Batch operations**: `build_drum_rack` loads Drum Rack + all samples in 1 call
- **Direct browsing**: `browse_folder` with `filter=` is much faster than `search_browser`
- **Audio clips**: `create_audio_clip` loads loops into specific slots (avoids load_browser_item limitations)
- **Session snapshots**: `get_session` returns everything in 1 call

## Troubleshooting

- **AbletonMCP doesn't appear:** Check the Remote Script is in the correct User Remote Scripts folder
- **Can't connect:** Make sure Ableton has the control surface enabled in Settings
- **Timeouts on search:** Use `browse_folder` with `filter=` instead of `search_browser`
- **Loops load to wrong slot:** Use `create_audio_clip(track, clip_index, file_path)` for precise placement
- **Still stuck:** Run `./scripts/restart_ableton.sh` to restart Ableton with latest Remote Script

## Credits

- **Original project:** [Siddharth Ahuja](https://github.com/ahujasid/ableton-mcp)
- **Community:** [Discord](https://discord.gg/3ZrMyGKnaU)
- **Ableton API Reference:** [AbletonLive-API-Stub](https://github.com/cylab/AbletonLive-API-Stub)

## Disclaimer

This is an independent, community-driven project. Not affiliated with or endorsed by Ableton.
