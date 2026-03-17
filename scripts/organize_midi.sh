#!/usr/bin/env bash
#
# organize_midi.sh — Copy and categorize MIDI files from the production library
# into midi_patterns/<category>/ with clean, consistent filenames.
#
# Idempotent: removes and recreates the target directory on each run.
# Compatible with bash 3.2+ (macOS default).

set -euo pipefail

SOURCE="/Users/jeff/Music/PRODUCTION LIBS"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$REPO_ROOT/midi_patterns"

# Categories
CATEGORIES="bass drums synth chords keys pads melody other"

# ── Clean slate ──────────────────────────────────────────────────────────────
echo "Cleaning target directory: $TARGET"
rm -rf "$TARGET"
for cat in $CATEGORIES; do
    mkdir -p "$TARGET/$cat"
done

# Temp directory for tracking duplicates and counts
TMPDIR_TRACK="$(mktemp -d)"
trap "rm -rf '$TMPDIR_TRACK'" EXIT

# Initialize counters
for cat in $CATEGORIES; do
    echo "0" > "$TMPDIR_TRACK/count_$cat"
done

# ── Helpers ──────────────────────────────────────────────────────────────────

categorize() {
    # Takes the full source path (lowercased) and filename (lowercased).
    # Echoes the matching category.
    local lc_path="$1"
    local lc_name="$2"

    # Bass
    case "$lc_name" in *bass*) echo "bass"; return;; esac
    case "$lc_path" in *bass*) echo "bass"; return;; esac

    # Drums
    for kw in drum kick snare hat perc rhythm; do
        case "$lc_name" in *${kw}*) echo "drums"; return;; esac
        case "$lc_path" in *${kw}*) echo "drums"; return;; esac
    done
    # "top" needs special handling — check path for /tops/ and filename for _top_ or _top.
    case "$lc_name" in *_top_*|*_top.*|*_tops_*|*_tops.*) echo "drums"; return;; esac
    case "$lc_path" in */tops/*|*/top/*) echo "drums"; return;; esac

    # Chords (before synth)
    for kw in chord stab; do
        case "$lc_name" in *${kw}*) echo "chords"; return;; esac
        case "$lc_path" in *${kw}*) echo "chords"; return;; esac
    done

    # Keys
    for kw in piano keys rhode rhodes organ wurli; do
        case "$lc_name" in *${kw}*) echo "keys"; return;; esac
        case "$lc_path" in *${kw}*) echo "keys"; return;; esac
    done

    # Pads
    case "$lc_name" in *pad*) echo "pads"; return;; esac
    case "$lc_path" in *pad*) echo "pads"; return;; esac

    # Synth (after keys/chords/pads)
    for kw in synth arp lead; do
        case "$lc_name" in *${kw}*) echo "synth"; return;; esac
        case "$lc_path" in *${kw}*) echo "synth"; return;; esac
    done

    # Melody
    case "$lc_name" in *melod*) echo "melody"; return;; esac
    case "$lc_path" in *melod*) echo "melody"; return;; esac

    echo "other"
}

clean_name() {
    # Clean a filename: lowercase, spaces to underscores, remove leading dots/underscores,
    # replace # with "sharp", collapse multiple underscores, ensure .mid extension.
    local name="$1"

    # Lowercase
    name="$(echo "$name" | tr '[:upper:]' '[:lower:]')"

    # Strip extension
    local base="${name%.midi}"
    base="${base%.mid}"

    # Replace # with "sharp" (for musical keys like A#, C#)
    base="$(echo "$base" | sed 's/#/sharp/g')"

    # Replace spaces and hyphens with underscores
    base="$(echo "$base" | tr ' ' '_')"

    # Remove any characters that aren't alphanumeric, underscore, or hyphen
    base="$(echo "$base" | tr -cd 'a-z0-9_-')"

    # Remove leading dots and underscores
    base="$(echo "$base" | sed 's/^[._]*//')"

    # Collapse multiple underscores
    base="$(echo "$base" | sed 's/__*/_/g')"

    # Remove trailing underscores
    base="$(echo "$base" | sed 's/_*$//')"

    echo "${base}.mid"
}

# ── Main loop ────────────────────────────────────────────────────────────────

file_count=0

while IFS= read -r -d '' filepath; do
    filename="$(basename "$filepath")"

    # Skip macOS resource fork files (._*)
    case "$filename" in ._*) continue;; esac

    # Lowercase path and filename for categorization
    lc_path="$(echo "$filepath" | tr '[:upper:]' '[:lower:]')"
    lc_name="$(echo "$filename" | tr '[:upper:]' '[:lower:]')"

    # Determine category
    category="$(categorize "$lc_path" "$lc_name")"

    # Clean the filename
    cleaned="$(clean_name "$filename")"

    # Handle duplicates using temp files
    dup_file="$TMPDIR_TRACK/dup_${category}_${cleaned}"
    if [ -f "$dup_file" ]; then
        dup_count=$(cat "$dup_file")
        dup_count=$((dup_count + 1))
        echo "$dup_count" > "$dup_file"
        # Insert _N before .mid
        local_base="${cleaned%.mid}"
        cleaned="${local_base}_${dup_count}.mid"
    else
        echo "1" > "$dup_file"
    fi

    # Copy
    cp "$filepath" "$TARGET/$category/$cleaned"

    # Increment category counter
    cur=$(cat "$TMPDIR_TRACK/count_$category")
    echo $((cur + 1)) > "$TMPDIR_TRACK/count_$category"

    file_count=$((file_count + 1))

done < <(find "$SOURCE" \( -name "*.mid" -o -name "*.midi" \) \
    ! -path '*__MACOSX*' ! -name '._*' -print0)

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "========================================="
echo "  MIDI Organization Complete"
echo "========================================="
echo ""
printf "  %-12s %s\n" "Category" "Count"
printf "  %-12s %s\n" "--------" "-----"

total=0
for cat in $CATEGORIES; do
    c=$(cat "$TMPDIR_TRACK/count_$cat")
    printf "  %-12s %d\n" "$cat" "$c"
    total=$((total + c))
done

echo ""
echo "  Total files: $total"
echo "  Target dir:  $TARGET"
echo "========================================="
