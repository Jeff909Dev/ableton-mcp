# AbletonMCP - Ableton Live + AI via Model Context Protocol

Connect Ableton Live to AI assistants (Claude, Cursor, etc.) and control your DAW with natural language. Create tracks, generate chord progressions, design drum patterns, tweak parameters — all through conversation.

---

> **This is a fork.** The original project was created by [Siddharth Ahuja](https://x.com/sidahuj) ([original repo](https://github.com/ahujasid/ableton-mcp)). Huge thanks to Siddharth for building this and sharing it with the world — we need more people like him pushing the boundaries of what's possible when music meets AI. The kind of innovation that moves the industry forward starts with people willing to experiment in the open.
>
> I picked up this project to experiment, learn, and see how far it can go. If you want to contribute, you're welcome — whether it's fixing a bug, adding a new tool, improving the docs, or just sharing ideas. This is an open playground.

---

## What can it do?

Ask your AI assistant things like:

- *"Create an 80s synthwave track"*
- *"Generate a hip-hop drum pattern and a walking bassline in C minor"*
- *"What chords would work over this melody?"*
- *"Add reverb to track 2 and set the decay to 3 seconds"*
- *"Show me the full session state"*
- *"Duplicate track 1, mute the original, and set the tempo to 95 BPM"*

## Features

**67 tools** organized in 8 categories:

| Category | What you get |
|----------|-------------|
| **Session** | Full session snapshots in one call, track summaries |
| **Tracks** | Create, delete, duplicate, volume, pan, mute, solo, arm, sends |
| **Clips** | Create, delete, duplicate, add/get/remove MIDI notes, loop, quantize |
| **Scenes** | Create, delete, duplicate, fire scenes, stop all clips |
| **Devices** | Get/set parameters by name or index, toggle on/off, load instruments |
| **Transport** | Play, stop, undo, redo, metronome, loop, tempo, record, capture MIDI |
| **Browser** | Search instruments/effects by name, browse tree, load presets |
| **AI/Music Theory** | Chords (23 types), scales (15 types), progressions, drum patterns, basslines, melodies, harmony suggestions — powered by Markov chains trained on 1100+ real MIDI patterns |

## Pattern Generation (Markov Chains)

The AI music tools don't just use hardcoded templates — they learn from real music. The repo includes **1105 MIDI patterns** extracted from professional sample packs, organized by category:

| Category | Patterns | What it generates |
|----------|----------|-------------------|
| Bass | 391 | Basslines with realistic rhythms and intervals |
| Synth | 251 | Synth lines and arpeggios |
| Keys | 155 | Piano, Rhodes, organ patterns |
| Chords | 96 | Chord progressions and stabs |
| Drums | 72 | Drum grooves and percussion |
| Pads | 50 | Pad voicings |
| Melody | 27 | Melodic phrases |

**How it works:**
1. MIDI patterns are parsed and analyzed (note intervals, rhythms, velocities, rest probabilities)
2. Markov chain models are trained on the transition probabilities
3. When you ask for a bassline or groove, the model generates new patterns based on learned probabilities — not random, not hardcoded, but statistically similar to real music
4. Results are transposable to any key and adjustable in length

The pre-trained models (`markov_models.json`, 97KB) are included in the repo, so pattern generation works out of the box for everyone.

You can also use the classic hardcoded styles (`basic`, `walking`, `house`, `funk`, etc.) by specifying the style parameter — but the default is `markov`.

### Adding your own MIDI patterns

Want to train on your own MIDI library? Place `.mid` files in `midi_patterns/{bass,drums,synth,chords,keys,pads,melody}/` and rebuild:

```bash
# Install mido (MIDI parser)
.venv/bin/pip install mido

# Parse MIDI files into index
.venv/bin/python scripts/build_pattern_index.py

# Train Markov models
.venv/bin/python scripts/build_markov_models.py
```

Or use the included extraction script to scan an existing sample library:

```bash
# Edit MIDI_SOURCE in scripts/organize_midi.sh to point to your library
bash scripts/organize_midi.sh
```

## Architecture

```
┌──────────────┐        ┌─────────────────────────────┐       ┌───────────────────┐
│  AI Client   │◄─MCP──►│  MCP Server                 │◄─TCP─►│  Ableton Live     │
│  (Claude,    │        │  (Python process on your     │ :9877 │                   │
│   Cursor)    │        │   machine)                   │       │  Remote Script    │
└──────────────┘        │                              │       │  (__init__.py)    │
                        │  67 tools                    │       │                   │
                        │  Markov pattern generator    │       │  Receives         │
                        │  Response cache              │       │  commands and     │
                        │  markov_models.json          │       │  executes them    │
                        └─────────────────────────────┘       │  via Ableton API  │
                                                               └───────────────────┘
```

**There are two separate components:**

1. **MCP Server** — A Python process that runs on your machine. This is the "brain": it generates MIDI patterns, manages tools, communicates with AI clients, and sends commands to Ableton. It lives in the project folder (`~/code/ableton-mcp/` or wherever you cloned it). **You must keep this folder — deleting it breaks the server.**

2. **Remote Script** — A single Python file (`__init__.py`) copied into Ableton's app bundle. It's a thin communication bridge: receives TCP commands from the MCP Server and executes them in Ableton's API. It does NOT generate patterns, does NOT have AI, and does NOT need the MIDI data.

When Claude asks to "generate a bass pattern in Am", this is what happens:

```
Claude → MCP Server → Markov model generates notes → MCP Server sends notes via TCP
    → Remote Script receives them → calls Ableton API → notes appear in clip
```

## Installation

### Prerequisites

- Ableton Live 10+ (Live 12 recommended)
- Python 3.10+
- [uv](https://astral.sh/uv) (`brew install uv` on Mac)

### Quick install (macOS)

```bash
git clone https://github.com/Jeff909Dev/ableton-mcp.git
cd ableton-mcp
./install.sh
```

The installer does three things:
1. Creates a Python virtual environment and installs the MCP Server
2. Builds/verifies MIDI pattern models for the Markov generator
3. Copies the Remote Script into Ableton's MIDI Remote Scripts folder

### Manual install

**1. MCP Server:**

```bash
git clone https://github.com/Jeff909Dev/ableton-mcp.git
cd ableton-mcp
uv venv
uv pip install -e .
```

**2. Remote Script** — copy `AbletonMCP_Remote_Script/__init__.py` into Ableton's app bundle:

- **macOS (Live 12):** Right-click `Ableton Live 12 Suite.app` → Show Package Contents → `Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/__init__.py`
- **macOS (Live 11):** Same method, or use `~/Library/Preferences/Ableton/Live XX/User Remote Scripts/AbletonMCP/`
- **Windows:** `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\AbletonMCP\`

**3. Enable in Ableton:** Settings → Link, Tempo & MIDI → Control Surface → select "AbletonMCP" → Input/Output: None

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

### Updating

```bash
cd ableton-mcp
git pull
./install.sh
```

Note: if you update Ableton, you'll need to re-run `./install.sh` to copy the Remote Script into the new app bundle.

## Project structure

```
MCP_Server/
  server.py              # Entry point
  connection.py          # Async TCP connection
  cache.py               # Response cache
  tools/
    session_tools.py     # Session info
    track_tools.py       # Track management
    clip_tools.py        # Clip operations
    scene_tools.py       # Scene management
    device_tools.py      # Device parameters
    transport_tools.py   # Transport controls
    browser_tools.py     # Browser navigation
    ai_tools.py          # Music theory + Markov generation
    pattern_generator.py # Markov chain pattern engine
  data/
    markov_models.json   # Pre-trained Markov models (bundled with package)

AbletonMCP_Remote_Script/
  __init__.py            # Runs inside Ableton (thin TCP bridge)

midi_patterns/           # 1105 MIDI files organized by category
  bass/                  # 391 bass patterns
  drums/                 # 72 drum patterns
  synth/                 # 251 synth patterns
  chords/                # 96 chord patterns
  keys/                  # 155 piano/keys patterns
  pads/                  # 50 pad patterns
  melody/                # 27 melody patterns
  markov_models.json     # Pre-trained Markov models (source copy)

scripts/
  organize_midi.sh       # Extract and categorize MIDIs from a sample library
  build_pattern_index.py # Parse MIDI files into structured JSON index
  build_markov_models.py # Train Markov chains on parsed patterns
```

## Performance

- **Async connection** — no `time.sleep()` blocking the pipeline
- **Session snapshots** — `get_full_session_state` returns everything in 1 call instead of N+1
- **Response caching** — repeated queries are instant (2s for session data, 60s for browser)
- **Batch commands** — multiple commands in a single TCP round-trip
- **Markov generation** — pattern generation is instant (cached models, pure computation)

## Contributing

This project is open to everyone. Whether you're a producer, a developer, or just curious about what happens when AI meets a DAW — feel free to open an issue, submit a PR, or just fork it and make it your own.

Some ideas if you want to contribute:
- Add your own MIDI patterns to improve generation quality
- New Markov model features (velocity-aware generation, genre-specific models)
- Support for audio clip operations
- Arrangement view tools
- Better browser search
- Tests

## Troubleshooting

- **AbletonMCP doesn't appear in Control Surface:** Make sure the script is in the correct location. For Live 12, it must be inside the app bundle (`Show Package Contents → Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/`), not in User Remote Scripts.
- **Can't connect:** Make sure the Remote Script is loaded in Ableton (check Settings → Link, Tempo & MIDI)
- **Pattern generation uses fallback:** Check that `MCP_Server/data/markov_models.json` exists. Re-run `./install.sh` to rebuild.
- **Timeouts:** Break complex requests into smaller steps
- **Still stuck:** Restart both Ableton and your AI client

## Credits

- **Original project:** [Siddharth Ahuja](https://github.com/ahujasid/ableton-mcp) — thank you for starting this
- **Community:** [Discord](https://discord.gg/3ZrMyGKnaU)

## Disclaimer

This is an independent, community-driven project. It is not affiliated with or endorsed by Ableton.
