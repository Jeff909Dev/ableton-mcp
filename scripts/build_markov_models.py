#!/usr/bin/env python3
"""Build Markov chain models from parsed MIDI pattern data.

Reads midi_patterns/index.json and trains transition-probability models for
each instrument category (bass, drums, synth, chords, keys, pads, melody).
Outputs midi_patterns/markov_models.json.

Usage:
    python scripts/build_markov_models.py
    python scripts/build_markov_models.py --input midi_patterns/index.json --output midi_patterns/markov_models.json
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_VERSION = 1

MELODIC_CATEGORIES = {"bass", "synth", "keys", "melody", "chords", "pads"}
DRUM_CATEGORY = "drums"

# Quantised duration values (in beats). Raw durations are snapped to the
# nearest bucket so that the transition matrices stay manageable.
DURATION_BUCKETS = [0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]

# Velocity bucket boundaries (MIDI 0-127)
VELOCITY_BOUNDARIES = {
    "soft": (0, 64),
    "medium": (64, 96),
    "hard": (96, 112),
    "accent": (112, 128),
}

# Standard GM drum mapping — used for categorising drum hits by instrument
GM_DRUM_MAP = {
    36: "kick",
    35: "kick",       # acoustic bass drum variant
    38: "snare",
    40: "snare",      # electric snare
    37: "rim",
    39: "clap",
    42: "closed_hh",
    44: "closed_hh",  # pedal hi-hat
    46: "open_hh",
    49: "crash",
    57: "crash",      # crash 2
    51: "ride",
    59: "ride",       # ride 2
    53: "ride",       # ride bell
    43: "tom_low",
    41: "tom_low",    # low floor tom
    45: "tom_mid",
    47: "tom_mid",    # low-mid tom
    48: "tom_hi",
    50: "tom_hi",     # high tom
}

# 16th-note grid resolution used for drum step-transition analysis
STEPS_PER_BAR = 16
STEP_SIZE = 0.25  # beats per step in 4/4 time


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def quantize_duration(raw: float) -> float:
    """Snap a raw duration to the closest canonical bucket value."""
    best = min(DURATION_BUCKETS, key=lambda b: abs(b - raw))
    return best


def velocity_bucket(vel: int) -> str:
    """Map a MIDI velocity (0-127) to a named bucket."""
    for name, (lo, hi) in VELOCITY_BOUNDARIES.items():
        if lo <= vel < hi:
            return name
    return "accent"  # fallback for vel == 127


def normalize_distribution(counter: Counter) -> dict:
    """Turn a Counter into a probability dict whose values sum to 1.0.

    Keys are converted to strings for JSON serialisation.
    Values are rounded to 6 decimal places.
    """
    total = sum(counter.values())
    if total == 0:
        return {}
    return {str(k): round(v / total, 6) for k, v in counter.items()}


def normalize_transition_matrix(matrix: dict) -> dict:
    """Normalize each row of a {state -> Counter} transition matrix.

    Returns {str(state): {str(next_state): probability, ...}, ...}.
    """
    result = {}
    for state, counter in matrix.items():
        total = sum(counter.values())
        if total == 0:
            continue
        row = {str(k): round(v / total, 6) for k, v in counter.items()}
        result[str(state)] = row
    return result


# ---------------------------------------------------------------------------
# Melodic model builder
# ---------------------------------------------------------------------------

def _extract_notes_sorted(pattern: dict) -> list:
    """Return the pattern's notes sorted by start_time then pitch."""
    notes = pattern.get("notes", [])
    return sorted(notes, key=lambda n: (n.get("start", n.get("start", n.get("start_time", 0))), n.get("pitch", 0)))


def build_melodic_model(patterns: list) -> dict:
    """Build a Markov model for a melodic category.

    Parameters
    ----------
    patterns : list[dict]
        Each dict should have a ``notes`` list of note dicts with keys
        ``pitch``, ``start_time``, ``duration``, ``velocity``.

    Returns
    -------
    dict with keys: sample_count, interval_transitions, rhythm_transitions,
    velocity_transitions, rest_probability, start_intervals.
    """
    interval_trans = defaultdict(Counter)   # interval -> Counter(next_interval)
    rhythm_trans = defaultdict(Counter)     # quant_dur -> Counter(next_quant_dur)
    velocity_trans = defaultdict(Counter)   # vel_bucket -> Counter(next_vel_bucket)
    start_intervals = Counter()             # interval from root (pitch % 12 == 0 proxy)
    total_notes = 0
    total_rests = 0

    for pattern in patterns:
        notes = _extract_notes_sorted(pattern)
        if len(notes) < 2:
            continue

        # First note: record starting interval (relative to first note as
        # implicit "root" — we use pitch mod 12 of the first note as 0).
        root_pc = notes[0]["pitch"] % 12
        start_interval = 0  # first note is always 0 relative to itself
        start_intervals[start_interval] += 1

        prev_interval = None
        prev_dur = quantize_duration(notes[0].get("duration", 1.0))
        prev_vel = velocity_bucket(notes[0].get("velocity", 80))

        for i in range(1, len(notes)):
            cur = notes[i]
            prv = notes[i - 1]

            # Compute interval (semitone delta between consecutive pitches)
            interval = cur["pitch"] - prv["pitch"]
            # Clamp extreme intervals to keep model tractable
            interval = max(-24, min(24, interval))

            # Duration
            cur_dur = quantize_duration(cur.get("duration", 1.0))
            cur_vel = velocity_bucket(cur.get("velocity", 80))

            # Detect rests: gap between previous note end and current note start
            prev_end = prv.get("start", 0) + prv.get("duration", 0)
            cur_start = cur.get("start", 0)
            if cur_start - prev_end > 0.1:  # more than a tiny gap → rest
                total_rests += 1

            total_notes += 1

            # Record transitions
            if prev_interval is not None:
                interval_trans[prev_interval][interval] += 1
            else:
                # First transition: record as coming from 0
                interval_trans[0][interval] += 1

            rhythm_trans[prev_dur][cur_dur] += 1
            velocity_trans[prev_vel][cur_vel] += 1

            # Record start interval for notes that begin at bar boundaries
            bar_position = cur.get("start", 0) % 4.0
            if bar_position < 0.05:  # very close to bar start
                rel_interval = (cur["pitch"] - notes[0]["pitch"]) % 12
                # Express as signed interval from root
                if rel_interval > 6:
                    rel_interval -= 12
                start_intervals[rel_interval] += 1

            prev_interval = interval
            prev_dur = cur_dur
            prev_vel = cur_vel

    rest_prob = round(total_rests / max(total_notes, 1), 4)

    return {
        "sample_count": len(patterns),
        "interval_transitions": normalize_transition_matrix(interval_trans),
        "rhythm_transitions": normalize_transition_matrix(rhythm_trans),
        "velocity_transitions": normalize_transition_matrix(velocity_trans),
        "rest_probability": rest_prob,
        "start_intervals": normalize_distribution(start_intervals),
    }


# ---------------------------------------------------------------------------
# Drum model builder
# ---------------------------------------------------------------------------

def _pattern_length_beats(notes: list) -> float:
    """Estimate the total length of a pattern in beats."""
    if not notes:
        return 4.0
    max_end = max(n.get("start", n.get("start_time", 0)) + n.get("duration", 0.25) for n in notes)
    # Round up to nearest bar (4 beats in 4/4)
    bars = max(1, int((max_end + 3.99) // 4))
    return float(bars * 4)


def build_drum_model(patterns: list) -> dict:
    """Build a Markov model for the drum category.

    Each pattern's notes are mapped to GM drum instruments, then analysed on a
    16th-note step grid per instrument.

    Returns
    -------
    dict with key ``instruments``, each containing step_transitions,
    density, and velocity_transitions.
    """
    # Accumulate per-instrument data across all patterns
    instrument_step_trans = defaultdict(lambda: defaultdict(Counter))
    instrument_hit_counts = defaultdict(int)
    instrument_total_steps = defaultdict(int)
    instrument_vel_trans = defaultdict(lambda: defaultdict(Counter))

    for pattern in patterns:
        notes = pattern.get("notes", [])
        if not notes:
            continue

        length_beats = _pattern_length_beats(notes)
        total_steps = int(length_beats / STEP_SIZE)

        # Group notes by instrument
        inst_hits = defaultdict(list)  # instrument -> sorted list of step indices
        inst_vels = defaultdict(list)  # instrument -> list of (step, velocity)

        for note in notes:
            pitch = note.get("pitch", 0)
            inst_name = GM_DRUM_MAP.get(pitch)
            if inst_name is None:
                # Try to guess: pitches 35-81 are GM percussion
                if 35 <= pitch <= 81:
                    inst_name = "other"
                else:
                    continue

            step = int(round(note.get("start", 0) / STEP_SIZE))
            step = max(0, min(step, total_steps - 1))
            vel = note.get("velocity", 80)
            inst_hits[inst_name].append(step)
            inst_vels[inst_name].append((step, vel))

        # Build step transitions and density per instrument
        for inst_name, steps in inst_hits.items():
            steps_sorted = sorted(set(steps))
            hit_set = set(steps_sorted)
            hits_in_pattern = len(steps_sorted)

            instrument_hit_counts[inst_name] += hits_in_pattern
            instrument_total_steps[inst_name] += total_steps

            # Step transitions: for each step, is the next step a hit or not?
            # We encode this as transitions between "hit"/"rest" states on the
            # 16th-note grid.
            for s in range(total_steps):
                current_state = "hit" if s in hit_set else "rest"
                next_step = (s + 1) % total_steps
                next_state = "hit" if next_step in hit_set else "rest"
                instrument_step_trans[inst_name][current_state][next_state] += 1

            # Velocity transitions within hits for this instrument
            vels_sorted = sorted(inst_vels[inst_name], key=lambda x: x[0])
            for i in range(1, len(vels_sorted)):
                prev_vb = velocity_bucket(vels_sorted[i - 1][1])
                cur_vb = velocity_bucket(vels_sorted[i][1])
                instrument_vel_trans[inst_name][prev_vb][cur_vb] += 1

    # Assemble per-instrument models
    instruments = {}
    for inst_name in sorted(set(list(instrument_step_trans.keys()) + list(instrument_hit_counts.keys()))):
        total_hits = instrument_hit_counts.get(inst_name, 0)
        total_steps = instrument_total_steps.get(inst_name, 1)
        density = round(total_hits / max(total_steps, 1), 4)

        instruments[inst_name] = {
            "step_transitions": normalize_transition_matrix(
                instrument_step_trans.get(inst_name, {})
            ),
            "density": density,
            "velocity_transitions": normalize_transition_matrix(
                instrument_vel_trans.get(inst_name, {})
            ),
        }

    return {
        "sample_count": len(patterns),
        "instruments": instruments,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_index(path: str) -> dict:
    """Load and validate the index.json file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("index.json must be a JSON object at the top level")

    return data


def categorize_patterns(index: dict) -> dict:
    """Group patterns from the index by category.

    The index can be structured in various ways:
    - ``{"categories": {"bass": {"count": N, "patterns": [...]}, ...}}``
    - ``{"patterns": [{"category": "bass", "notes": [...], ...}, ...]}``
    - ``{"bass": [...], "drums": [...], ...}``

    Returns {category_name: [pattern_dicts]}.
    """
    categories = defaultdict(list)

    if "categories" in index and isinstance(index["categories"], dict):
        # Structure: {categories: {name: {count, patterns: [...]}}}
        for cat_name, cat_data in index["categories"].items():
            if isinstance(cat_data, dict) and "patterns" in cat_data:
                for item in cat_data["patterns"]:
                    if isinstance(item, dict):
                        categories[cat_name].append(item)
    elif "patterns" in index and isinstance(index["patterns"], list):
        # Flat list with category field
        for pattern in index["patterns"]:
            cat = pattern.get("category", "unknown")
            categories[cat].append(pattern)
    else:
        # Top-level keys are category names
        for key, value in index.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        categories[key].append(item)

    return dict(categories)


def build_all_models(index: dict) -> dict:
    """Build Markov models for every category in the index.

    Returns the full output structure ready for JSON serialisation.
    """
    cats = categorize_patterns(index)
    category_models = {}

    for cat_name, patterns in sorted(cats.items()):
        if not patterns:
            continue

        print(f"  {cat_name}: {len(patterns)} patterns ... ", end="", flush=True)

        if cat_name == DRUM_CATEGORY:
            model = build_drum_model(patterns)
        else:
            model = build_melodic_model(patterns)

        category_models[cat_name] = model
        print("done")

    return {
        "version": MODEL_VERSION,
        "categories": category_models,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build Markov chain models from parsed MIDI patterns."
    )
    project_root = Path(__file__).resolve().parent.parent
    default_input = project_root / "midi_patterns" / "index.json"
    default_output = project_root / "midi_patterns" / "markov_models.json"

    parser.add_argument(
        "--input", "-i",
        type=str,
        default=str(default_input),
        help="Path to index.json (default: midi_patterns/index.json)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=str(default_output),
        help="Path for output models JSON (default: midi_patterns/markov_models.json)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading index from {input_path} ...")
    index = load_index(str(input_path))

    print("Building Markov models ...")
    models = build_all_models(index)

    total_patterns = sum(
        m.get("sample_count", 0) for m in models["categories"].values()
    )
    print(f"Total patterns processed: {total_patterns}")
    print(f"Categories: {', '.join(sorted(models['categories'].keys()))}")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(str(output_path), "w", encoding="utf-8") as f:
        json.dump(models, f, indent=2, sort_keys=False)

    size_kb = output_path.stat().st_size / 1024
    print(f"Saved models to {output_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
