# AbletonMCP - Ableton Live Model Context Protocol Integration
[![smithery badge](https://smithery.ai/badge/@ahujasid/ableton-mcp)](https://smithery.ai/server/@ahujasid/ableton-mcp)

AbletonMCP connects Ableton Live to AI assistants through the Model Context Protocol (MCP), allowing direct interaction with and control of Ableton Live. This integration enables AI-assisted music production, track creation, and Live session manipulation.

### Join the Community

Give feedback, get inspired, and build on top of the MCP: [Discord](https://discord.gg/3ZrMyGKnaU). Made by [Siddharth](https://x.com/sidahuj)

## Features

- **67 tools** for complete Ableton Live control
- **Async connection** — non-blocking I/O with response caching for speed
- **AI music theory tools** — chord generators, scale helpers, rhythm patterns, basslines, melodies
- **Batch commands** — send multiple commands in a single TCP round-trip
- **Full session snapshots** — get complete session state in one call (replaces N+1 queries)

### Tool Categories

| Category | Tools | Description |
|----------|-------|-------------|
| Session | 4 | Session info, full state snapshot, all tracks summary |
| Tracks | 11 | Create/delete/duplicate tracks, volume, pan, mute, solo, arm, sends |
| Clips | 9 | Create/delete/duplicate clips, add/get/remove notes, loop, quantize |
| Scenes | 8 | Create/delete/duplicate/fire scenes, stop all clips |
| Devices | 6 | Get/set parameters (by index or name), toggle, delete devices |
| Transport | 15 | Play/stop, undo/redo, metronome, loop, tempo, record, capture MIDI |
| Browser | 5 | Browse tree, search by name, load instruments/effects/drum kits |
| AI/Music Theory | 9 | Chords, scales, progressions, rhythms, basslines, melodies, harmony |

## Architecture

```
┌──────────────────┐     TCP/JSON      ┌──────────────────────────┐
│   MCP Client     │◄──────────────────►│  MCP Server (async)      │
│  (Claude, etc.)  │                    │  - Response caching      │
└──────────────────┘                    │  - 67 tools in 8 modules │
                                        │  - AI music theory       │
                                        └──────────┬───────────────┘
                                                   │ TCP :9877
                                        ┌──────────▼───────────────┐
                                        │  Ableton Remote Script   │
                                        │  - 61 command handlers   │
                                        │  - Batch command support  │
                                        │  - Thread-safe execution  │
                                        └──────────────────────────┘
```

## Installation

### Installing via Smithery

To install Ableton Live Integration for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@ahujasid/ableton-mcp):

```bash
npx -y @smithery/cli install @ahujasid/ableton-mcp --client claude
```

### Prerequisites

- Ableton Live 10 or newer
- Python 3.10 or newer
- [uv package manager](https://astral.sh/uv)

If you're on Mac, please install uv as:
```
brew install uv
```

Otherwise, install from [uv's official website](https://docs.astral.sh/uv/getting-started/installation/)

### Claude for Desktop Integration

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Go to Claude > Settings > Developer > Edit Config > claude_desktop_config.json to include the following:

```json
{
    "mcpServers": {
        "AbletonMCP": {
            "command": "uvx",
            "args": [
                "ableton-mcp"
            ]
        }
    }
}
```

### Cursor Integration

Run ableton-mcp without installing it permanently through uvx. Go to Cursor Settings > MCP and paste this as a command:

```
uvx ableton-mcp
```

Only run one instance of the MCP server (either on Cursor or Claude Desktop), not both.

### Installing the Ableton Remote Script

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Download the `AbletonMCP_Remote_Script/__init__.py` file from this repo

2. Copy the folder to Ableton's MIDI Remote Scripts directory:

   **For macOS:**
   - Method 1: Go to Applications > Right-click on Ableton Live app > Show Package Contents > Navigate to:
     `Contents/App-Resources/MIDI Remote Scripts/`
   - Method 2: If it's not there in the first method, use the direct path (replace XX with your version number):
     `/Users/[Username]/Library/Preferences/Ableton/Live XX/User Remote Scripts`

   **For Windows:**
   - Method 1:
     `C:\Users\[Username]\AppData\Roaming\Ableton\Live x.x.x\Preferences\User Remote Scripts`
   - Method 2:
     `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   - Method 3:
     `C:\Program Files\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   *Note: Replace XX with your Ableton version number (e.g., 10, 11, 12)*

4. Create a folder called 'AbletonMCP' in the Remote Scripts directory and paste the downloaded `__init__.py` file

3. Launch Ableton Live

4. Go to Settings/Preferences > Link, Tempo & MIDI

5. In the Control Surface dropdown, select "AbletonMCP"

6. Set Input and Output to "None"

## Usage

### Starting the Connection

1. Ensure the Ableton Remote Script is loaded in Ableton Live
2. Make sure the MCP server is configured in Claude Desktop or Cursor
3. The connection should be established automatically when you interact with Claude

### Example Commands

Here are some examples of what you can ask Claude to do:

- "Create an 80s synthwave track" [Demo](https://youtu.be/VH9g66e42XA)
- "Create a Metro Boomin style hip-hop beat"
- "Generate a jazz chord progression in Bb and add it to a new track"
- "Create a 4-bar drum pattern in trap style"
- "Add reverb to my drums and set the decay to 3 seconds"
- "What chords would harmonize with this melody?"
- "Generate a walking bassline over ii-V-I in C minor"
- "Set up a loop from bar 5 to bar 9"
- "Get the full session state and tell me what I'm working with"
- "Duplicate track 1 and mute the original"

### AI Music Theory Tools

The server includes built-in music theory tools that work without Ableton:

- **Chords**: 23 chord types (major, minor, dim, aug, maj7, min7, dom7, sus2, sus4, add9, etc.)
- **Scales**: 15 scale types (major, minor, dorian, phrygian, lydian, mixolydian, pentatonic, blues, etc.)
- **Progressions**: Roman numeral parsing with 8 presets (pop, jazz, blues, rock, reggaeton, etc.)
- **Rhythm patterns**: 10 styles (rock, hiphop, trap, house, dnb, reggaeton, bossa nova, jazz, funk)
- **Basslines**: 5 styles (basic, walking, octave, arpeggiated, syncopated)
- **Melodies**: Configurable density and style with musical heuristics
- **Harmony analysis**: Suggest chords for a given melody

## Performance

### Speed Improvements

- **Async connection**: Non-blocking I/O that doesn't freeze the event loop
- **Response caching**: Read-only queries are cached (2s TTL for session data, 60s for browser)
- **No sleep() calls**: Removed all blocking delays from the command pipeline
- **Full session snapshot**: `get_full_session_state` returns everything in 1 call instead of N+1
- **Batch commands**: Send multiple commands in a single TCP transmission

## Troubleshooting

- **Connection issues**: Make sure the Ableton Remote Script is loaded, and the MCP server is configured on Claude
- **Timeout errors**: Try simplifying your requests or breaking them into smaller steps
- **Restart**: If you're still having connection errors, try restarting both Claude and Ableton Live
- **Browser slow**: Browser operations are cached for 60 seconds; first call may be slow but subsequent ones are fast

## Technical Details

### Communication Protocol

The system uses a JSON-based protocol over TCP sockets:

- Commands are sent as JSON objects with a `type` and optional `params`
- Responses are JSON objects with a `status` and `result` or `message`
- Batch mode: send a JSON array of commands, receive a JSON array of responses

### Project Structure

```
MCP_Server/
  server.py           # Main server entry point
  connection.py       # Async TCP connection with reconnection
  cache.py            # TTL-based response cache
  tools/
    session_tools.py  # Session info and full state snapshots
    track_tools.py    # Track CRUD and mixer controls
    clip_tools.py     # Clip operations and MIDI note editing
    scene_tools.py    # Scene management
    device_tools.py   # Device parameter control
    transport_tools.py # Transport, undo/redo, metronome, loop
    browser_tools.py  # Browser navigation and search
    ai_tools.py       # Music theory and pattern generation

AbletonMCP_Remote_Script/
  __init__.py         # Ableton Remote Script (61 command handlers)
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This is a third-party integration and not made by Ableton.
