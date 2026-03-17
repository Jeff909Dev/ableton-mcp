#!/usr/bin/env bash
# AbletonMCP Installer
# Installs the MCP Server, builds pattern models, and installs the Ableton Remote Script
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_SCRIPT_SRC="$SCRIPT_DIR/AbletonMCP_Remote_Script/__init__.py"

echo "=== AbletonMCP Installer ==="
echo ""

# --- Step 1: Install the MCP Server ---
echo "[1/3] Installing MCP Server..."
if command -v uv &>/dev/null; then
    if [ ! -d "$SCRIPT_DIR/.venv" ]; then
        uv venv "$SCRIPT_DIR/.venv"
    fi
    uv pip install -e "$SCRIPT_DIR"
    echo "  MCP Server installed via uv."
elif command -v pip3 &>/dev/null; then
    pip3 install -e "$SCRIPT_DIR"
    echo "  MCP Server installed via pip3."
else
    echo "  ERROR: Neither uv nor pip3 found. Install uv first: brew install uv"
    exit 1
fi

# --- Step 2: Build MIDI pattern models (if not already built) ---
echo ""
echo "[2/3] Building MIDI pattern models..."

# Determine which Python to use
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PY="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PY="python3"
else
    PY="python"
fi

# Install mido if not present
$PY -c "import mido" 2>/dev/null || $PY -m pip install mido -q

MODELS_SRC="$SCRIPT_DIR/midi_patterns/markov_models.json"
MODELS_PKG="$SCRIPT_DIR/MCP_Server/data/markov_models.json"

if [ -f "$MODELS_SRC" ]; then
    echo "  Markov models found (midi_patterns/markov_models.json)."
    echo "  To rebuild: $PY scripts/build_pattern_index.py && $PY scripts/build_markov_models.py"
else
    # Need to build from MIDI files
    if ls "$SCRIPT_DIR/midi_patterns/"*/*.mid 1>/dev/null 2>&1; then
        echo "  Building pattern index from MIDI files..."
        $PY "$SCRIPT_DIR/scripts/build_pattern_index.py"
        echo "  Training Markov models..."
        $PY "$SCRIPT_DIR/scripts/build_markov_models.py"
    else
        echo "  WARNING: No MIDI patterns found and no pre-built models."
        echo "  Pattern generation will use fallback templates."
        echo "  To add patterns: place .mid files in midi_patterns/{bass,drums,synth,...}/"
    fi
fi

# Copy models into the Python package so the server is self-contained
if [ -f "$MODELS_SRC" ]; then
    mkdir -p "$SCRIPT_DIR/MCP_Server/data"
    cp "$MODELS_SRC" "$MODELS_PKG"
    echo "  Models bundled into MCP_Server/data/ for self-contained operation."
fi

# --- Step 3: Install the Remote Script into Ableton ---
echo ""
echo "[3/3] Installing Ableton Remote Script..."

# Find MIDI Remote Scripts inside Ableton app bundles
DIRS=()
while IFS= read -r -d '' dir; do
    DIRS+=("$dir")
done < <(find /Applications -maxdepth 5 -type d -name "MIDI Remote Scripts" -path "*/Ableton*" -print0 2>/dev/null)

if [ ${#DIRS[@]} -eq 0 ]; then
    echo "  No Ableton installation found."
    echo "  Please manually copy AbletonMCP_Remote_Script/__init__.py"
    echo "  to your Ableton MIDI Remote Scripts/AbletonMCP/ folder."
    exit 1
fi

echo "  Found Ableton installations:"
for i in "${!DIRS[@]}"; do
    echo "    [$((i+1))] ${DIRS[$i]}"
done

# If only one, use it. Otherwise ask.
if [ ${#DIRS[@]} -eq 1 ]; then
    CHOSEN="${DIRS[0]}"
    echo ""
    echo "  Using: $CHOSEN"
else
    echo ""
    read -rp "  Which one? [1-${#DIRS[@]}, or 'a' for all]: " choice
    if [ "$choice" = "a" ]; then
        for dir in "${DIRS[@]}"; do
            TARGET="$dir/AbletonMCP"
            mkdir -p "$TARGET"
            cp "$REMOTE_SCRIPT_SRC" "$TARGET/__init__.py"
            echo "  Installed to: $TARGET"
        done
        echo ""
        echo "=== Done! ==="
        echo "Restart Ableton and select 'AbletonMCP' in Settings > Link, Tempo & MIDI > Control Surface."
        exit 0
    else
        idx=$((choice - 1))
        CHOSEN="${DIRS[$idx]}"
    fi
fi

TARGET="$CHOSEN/AbletonMCP"
mkdir -p "$TARGET"
cp "$REMOTE_SCRIPT_SRC" "$TARGET/__init__.py"
echo "  Installed to: $TARGET"

echo ""
echo "=== Done! ==="
echo ""
echo "Next steps:"
echo "  1. Restart Ableton Live"
echo "  2. Go to Settings > Link, Tempo & MIDI"
echo "  3. Set Control Surface to 'AbletonMCP'"
echo "  4. Set Input and Output to 'None'"
echo ""
echo "MCP client config (Claude Desktop / Cursor):"
echo '  { "mcpServers": { "AbletonMCP": { "command": "ableton-mcp" } } }'
