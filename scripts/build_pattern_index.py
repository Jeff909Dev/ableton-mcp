#!/usr/bin/env python3
"""
Build a structured JSON index from a directory of MIDI pattern files.

Scans midi_patterns/<category>/*.mid, extracts musical metadata and note data
from each file, and writes midi_patterns/index.json for consumption by MCP tools.

Usage:
    .venv/bin/python scripts/build_pattern_index.py
    .venv/bin/python scripts/build_pattern_index.py --midi-dir /path/to/midi_patterns
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Optional

try:
    import mido
except ImportError:
    sys.exit(
        "mido is required. Install it with:\n"
        "  uv pip install --python .venv/bin/python mido"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_CATEGORIES = {
    "bass",
    "drums",
    "synth",
    "chords",
    "keys",
    "pads",
    "melody",
    "other",
}

DEFAULT_TICKS_PER_BEAT = 480
DEFAULT_TEMPO = 500_000  # 120 BPM in microseconds-per-beat
DEFAULT_BPM = 120.0

# ---------------------------------------------------------------------------
# Filename parsing helpers
# ---------------------------------------------------------------------------

# BPM patterns: _126_, 125BPM, 125_bpm, 125-bpm, bpm125, bpm_125, etc.
_BPM_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:^|[_\-\s])(\d{2,3})\s*bpm(?:[_\-\s.]|$)", re.IGNORECASE),
    re.compile(r"(?:^|[_\-\s])bpm\s*(\d{2,3})(?:[_\-\s.]|$)", re.IGNORECASE),
    re.compile(r"(?:^|[_\-])(\d{2,3})(?=[_\-])", re.IGNORECASE),
]

# Key patterns: _Am_, _Gm_, _A#_, _Ebm_, Key C minor, _Cmaj_, _C#min_, etc.
# Note names: C, C#, Db, D, D#, Eb, E, F, F#, Gb, G, G#, Ab, A, A#, Bb, B
_NOTE_NAMES = r"[A-G][b#]?"
_KEY_PATTERNS: list[re.Pattern] = [
    # "Key C minor", "Key_C_minor", "Key-Ab-Major"
    re.compile(
        r"[Kk]ey[_\-\s]?(" + _NOTE_NAMES + r")[_\-\s]?(major|minor|maj|min|m)(?:[_\-\s.]|$)",
        re.IGNORECASE,
    ),
    # "_Am_", "_Ebm_", "_C#m_", "_Bbm_" (single 'm' for minor)
    re.compile(
        r"(?:^|[_\-\s])(" + _NOTE_NAMES + r")(m)(?=[_\-\s.]|$)",
        re.IGNORECASE,
    ),
    # "_Cmaj_", "_C#min_", "_Dbmaj_", "_Abminor_"
    re.compile(
        r"(?:^|[_\-\s])(" + _NOTE_NAMES + r")(major|minor|maj|min)(?=[_\-\s.]|$)",
        re.IGNORECASE,
    ),
    # Standalone note name that is clearly a key — only match between delimiters
    # e.g., "_C_", "_Ab_", "_F#_"
    re.compile(
        r"(?:^|[_\-\s])(" + _NOTE_NAMES + r")()(?=[_\-\s.]|$)",
    ),
]

# Map various quality labels to a short suffix
_QUALITY_MAP = {
    "major": "",
    "maj": "",
    "minor": "m",
    "min": "m",
    "m": "m",
    "": "",  # bare note name → assume major
}


def parse_bpm_from_filename(filename: str) -> Optional[float]:
    """Try to extract BPM from a filename. Returns None if not found."""
    stem = Path(filename).stem
    for pattern in _BPM_PATTERNS:
        m = pattern.search(stem)
        if m:
            bpm = float(m.group(1))
            # Sanity-check: realistic BPM range
            if 40 <= bpm <= 300:
                return bpm
    return None


def parse_key_from_filename(filename: str) -> Optional[str]:
    """Try to extract musical key from a filename. Returns e.g. 'Am', 'C', 'Ebm'."""
    stem = Path(filename).stem
    for pattern in _KEY_PATTERNS:
        m = pattern.search(stem)
        if m:
            note = m.group(1)
            quality_raw = m.group(2).lower() if m.group(2) else ""
            quality = _QUALITY_MAP.get(quality_raw)
            if quality is None:
                continue
            # Normalize note: first letter uppercase, accidental lowercase
            note = note[0].upper() + note[1:]
            return f"{note}{quality}"
    return None


# ---------------------------------------------------------------------------
# MIDI analysis
# ---------------------------------------------------------------------------


def _ticks_to_beats(ticks: int, ticks_per_beat: int) -> float:
    """Convert MIDI ticks to beat units."""
    return ticks / ticks_per_beat


def _extract_tempo_from_midi(mid: mido.MidiFile) -> Optional[float]:
    """Return BPM from the first set_tempo meta message, or None."""
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                return mido.tempo2bpm(msg.tempo)
    return None


def _extract_time_signature(mid: mido.MidiFile) -> tuple[int, int]:
    """Return (numerator, denominator) from the first time_signature message, default 4/4."""
    for track in mid.tracks:
        for msg in track:
            if msg.type == "time_signature":
                return (msg.numerator, msg.denominator)
    return (4, 4)


def _extract_notes(mid: mido.MidiFile) -> list[dict[str, Any]]:
    """
    Merge all tracks and extract note events with beat-relative timing.

    Returns a list of dicts: {pitch, start, duration, velocity} sorted by start time.
    """
    ticks_per_beat = mid.ticks_per_beat or DEFAULT_TICKS_PER_BEAT

    # Merge all tracks into a single sequence of absolute-tick events.
    # We need to handle note_on/note_off pairing.
    # Use mido.merge_tracks to combine all tracks with correct timing.
    try:
        merged = mido.merge_tracks(mid.tracks)
    except Exception:
        # Fallback: just concatenate
        merged = []
        for track in mid.tracks:
            merged.extend(track)

    absolute_tick = 0
    # Track active notes: key = (channel, pitch) → (start_tick, velocity)
    active_notes: dict[tuple[int, int], tuple[int, int]] = {}
    notes: list[dict[str, Any]] = []

    for msg in merged:
        absolute_tick += msg.time

        if msg.type == "note_on" and msg.velocity > 0:
            key = (msg.channel, msg.note)
            # If this note is already active, close it first (some MIDI files do this)
            if key in active_notes:
                start_tick, vel = active_notes.pop(key)
                dur_ticks = absolute_tick - start_tick
                notes.append(
                    {
                        "pitch": msg.note,
                        "start": round(_ticks_to_beats(start_tick, ticks_per_beat), 4),
                        "duration": round(
                            _ticks_to_beats(max(dur_ticks, 1), ticks_per_beat), 4
                        ),
                        "velocity": vel,
                    }
                )
            active_notes[key] = (absolute_tick, msg.velocity)

        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.channel, msg.note)
            if key in active_notes:
                start_tick, vel = active_notes.pop(key)
                dur_ticks = absolute_tick - start_tick
                notes.append(
                    {
                        "pitch": msg.note,
                        "start": round(_ticks_to_beats(start_tick, ticks_per_beat), 4),
                        "duration": round(
                            _ticks_to_beats(max(dur_ticks, 1), ticks_per_beat), 4
                        ),
                        "velocity": vel,
                    }
                )

    # Close any notes that were never terminated
    for (channel, pitch), (start_tick, vel) in active_notes.items():
        dur_ticks = absolute_tick - start_tick
        if dur_ticks > 0:
            notes.append(
                {
                    "pitch": pitch,
                    "start": round(_ticks_to_beats(start_tick, ticks_per_beat), 4),
                    "duration": round(
                        _ticks_to_beats(dur_ticks, ticks_per_beat), 4
                    ),
                    "velocity": vel,
                }
            )

    # Sort by start time, then pitch
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    return notes


def _is_polyphonic(notes: list[dict[str, Any]]) -> bool:
    """
    Determine if a note sequence is polyphonic (has overlapping notes).

    A pattern is polyphonic if at any point two or more notes are sounding
    simultaneously.
    """
    if len(notes) < 2:
        return False

    # Build list of (time, +1 for on / -1 for off) events
    events: list[tuple[float, int]] = []
    for n in notes:
        events.append((n["start"], 1))
        events.append((n["start"] + n["duration"], -1))

    # Sort: by time, with off (-1) before on (+1) at the same time
    events.sort(key=lambda e: (e[0], e[1]))

    active = 0
    for _, delta in events:
        active += delta
        if active > 1:
            return True
    return False


def analyze_midi_file(filepath: Path, category: str, pattern_id: str) -> Optional[dict[str, Any]]:
    """
    Parse a single MIDI file and return a pattern metadata dict,
    or None if the file is corrupt/empty.
    """
    try:
        mid = mido.MidiFile(str(filepath))
    except Exception as exc:
        log.warning("Skipping %s: failed to parse MIDI (%s)", filepath, exc)
        return None

    notes = _extract_notes(mid)
    if not notes:
        log.warning("Skipping %s: no note events found", filepath)
        return None

    ticks_per_beat = mid.ticks_per_beat or DEFAULT_TICKS_PER_BEAT
    filename = filepath.name

    # --- BPM ---
    bpm = _extract_tempo_from_midi(mid)
    filename_bpm = parse_bpm_from_filename(filename)
    # Prefer filename BPM (more reliable for sample packs) when MIDI has default 120
    if filename_bpm is not None:
        if bpm is None or abs(bpm - DEFAULT_BPM) < 0.01:
            bpm = filename_bpm
    if bpm is not None:
        bpm = round(bpm, 1)
        # Clean up: 120.0 -> 120
        if bpm == int(bpm):
            bpm = int(bpm)

    # --- Key ---
    key = parse_key_from_filename(filename)

    # --- Time signature ---
    time_sig = list(_extract_time_signature(mid))

    # --- Note statistics ---
    pitches = [n["pitch"] for n in notes]
    note_range = [min(pitches), max(pitches)]

    # Total duration: from first note start to the end of the last note
    last_end = max(n["start"] + n["duration"] for n in notes)
    first_start = notes[0]["start"]
    total_duration_beats = round(last_end, 4)

    # Note density: notes per beat over the sounding region
    sounding_duration = last_end - first_start
    if sounding_duration > 0:
        note_density = round(len(notes) / sounding_duration, 2)
    else:
        note_density = 0.0

    polyphonic = _is_polyphonic(notes)

    return {
        "id": pattern_id,
        "filename": filename,
        "path": f"{category}/{filename}",
        "bpm": bpm,
        "key": key,
        "time_signature": time_sig,
        "duration_beats": total_duration_beats,
        "note_range": note_range,
        "note_density": note_density,
        "polyphonic": polyphonic,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Main index builder
# ---------------------------------------------------------------------------


def build_index(midi_dir: Path) -> dict[str, Any]:
    """Scan midi_dir for categorized .mid files and return the full index dict."""
    if not midi_dir.is_dir():
        log.error("MIDI directory not found: %s", midi_dir)
        sys.exit(1)

    categories: dict[str, list[dict[str, Any]]] = {}
    total_patterns = 0
    skipped = 0

    # Discover category subdirectories
    subdirs = sorted(
        [d for d in midi_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )

    if not subdirs:
        log.error("No subdirectories found in %s", midi_dir)
        sys.exit(1)

    unexpected = {d.name for d in subdirs} - EXPECTED_CATEGORIES
    if unexpected:
        log.info("Found non-standard categories: %s", ", ".join(sorted(unexpected)))

    for subdir in subdirs:
        category = subdir.name
        midi_files = sorted(subdir.glob("*.mid")) + sorted(subdir.glob("*.MID"))
        # Deduplicate in case both globs match the same file (case-insensitive FS)
        seen_paths: set[Path] = set()
        unique_files: list[Path] = []
        for f in midi_files:
            resolved = f.resolve()
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                unique_files.append(f)
        midi_files = unique_files

        if not midi_files:
            log.info("Category '%s' has no .mid files, skipping", category)
            continue

        patterns: list[dict[str, Any]] = []
        for idx, fpath in enumerate(midi_files, start=1):
            pattern_id = f"{category}_{idx:03d}"
            result = analyze_midi_file(fpath, category, pattern_id)
            if result is not None:
                patterns.append(result)
                total_patterns += 1
            else:
                skipped += 1

        categories[category] = {
            "count": len(patterns),
            "patterns": patterns,
        }
        log.info(
            "  %-10s  %4d patterns indexed (%d files scanned)",
            category,
            len(patterns),
            len(midi_files),
        )

    index = {
        "version": 1,
        "generated": date.today().isoformat(),
        "total_patterns": total_patterns,
        "categories": categories,
    }

    if skipped:
        log.warning("Skipped %d file(s) due to errors or empty content", skipped)

    return index


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a JSON index of MIDI pattern files for MCP tools.",
    )
    parser.add_argument(
        "--midi-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "midi_patterns",
        help="Root directory containing category subdirectories of .mid files "
        "(default: <project_root>/midi_patterns)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: <midi-dir>/index.json)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print the JSON output (default: True)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        default=False,
        help="Write compact JSON (overrides --pretty)",
    )
    args = parser.parse_args()

    midi_dir: Path = args.midi_dir.resolve()
    output_path: Path = (args.output or (midi_dir / "index.json")).resolve()

    log.info("Scanning MIDI files in %s", midi_dir)
    index = build_index(midi_dir)
    log.info("Total patterns indexed: %d", index["total_patterns"])

    # Write JSON
    indent = None if args.compact else 2
    separators = (",", ":") if args.compact else None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=indent, separators=separators, ensure_ascii=False)
        f.write("\n")

    size_kb = output_path.stat().st_size / 1024
    log.info("Wrote %s (%.1f KB)", output_path, size_kb)


if __name__ == "__main__":
    main()
