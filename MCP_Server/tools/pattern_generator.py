"""Pattern generation using trained Markov chain models.

Loads pre-built models from midi_patterns/markov_models.json and provides
functions for generating musically coherent MIDI patterns. Designed to be
called from ai_tools.py as an enhancement to the existing hardcoded generators.

All functions are pure computation — no Ableton connection required.
"""
import json
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("AbletonMCPServer")

# ---------------------------------------------------------------------------
# Data paths — look inside the package first, then fall back to project root
# ---------------------------------------------------------------------------
_PACKAGE_DATA = Path(__file__).resolve().parent.parent / "data"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Prefer package-bundled models (survives repo deletion), fall back to project root
_MODELS_PATH = (
    _PACKAGE_DATA / "markov_models.json"
    if (_PACKAGE_DATA / "markov_models.json").exists()
    else _PROJECT_ROOT / "midi_patterns" / "markov_models.json"
)
_INDEX_PATH = _PROJECT_ROOT / "midi_patterns" / "index.json"

# ---------------------------------------------------------------------------
# Cached data — loaded once on first access
# ---------------------------------------------------------------------------
_models_cache: Optional[dict] = None
_index_cache: Optional[dict] = None

# ---------------------------------------------------------------------------
# Music theory constants (duplicated minimally to keep this module standalone)
# ---------------------------------------------------------------------------

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

FLAT_TO_SHARP = {
    "Cb": "B", "Db": "C#", "Eb": "D#", "Fb": "E",
    "Gb": "F#", "Ab": "G#", "Bb": "A#",
}

# GM drum pitches for drum generation
GM_DRUMS = {
    "kick": 36,
    "snare": 38,
    "closed_hh": 42,
    "open_hh": 46,
    "clap": 39,
    "rim": 37,
    "tom_low": 43,
    "tom_mid": 47,
    "tom_hi": 50,
    "crash": 49,
    "ride": 51,
}

# Default duration buckets (must match build_markov_models.py)
DURATION_BUCKETS = [0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]

# Velocity bucket centres for note generation
VELOCITY_CENTRES = {
    "soft": 50,
    "medium": 80,
    "hard": 104,
    "accent": 120,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_models() -> Optional[dict]:
    """Load Markov models from disk, caching after first load."""
    global _models_cache
    if _models_cache is not None:
        return _models_cache

    if not _MODELS_PATH.exists():
        logger.warning("Markov models not found at %s", _MODELS_PATH)
        return None

    try:
        with open(str(_MODELS_PATH), "r", encoding="utf-8") as f:
            _models_cache = json.load(f)
        logger.info("Loaded Markov models (version %s)", _models_cache.get("version"))
        return _models_cache
    except Exception as exc:
        logger.error("Failed to load Markov models: %s", exc)
        return None


def _load_index() -> Optional[dict]:
    """Load pattern index from disk, caching after first load."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    if not _INDEX_PATH.exists():
        logger.warning("Pattern index not found at %s", _INDEX_PATH)
        return None

    try:
        with open(str(_INDEX_PATH), "r", encoding="utf-8") as f:
            _index_cache = json.load(f)
        logger.info("Loaded pattern index")
        return _index_cache
    except Exception as exc:
        logger.error("Failed to load pattern index: %s", exc)
        return None


def reload_models() -> bool:
    """Force-reload models from disk. Returns True on success."""
    global _models_cache, _index_cache
    _models_cache = None
    _index_cache = None
    return _load_models() is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _note_name_to_pitch_class(name: str) -> int:
    """Convert a note name like 'C', 'F#', 'Bb', 'Am', 'C#m' to pitch class 0-11.

    Strips trailing 'm', 'min', 'maj', 'minor', 'major' and any octave digits.
    """
    name = name.strip()
    if not name:
        raise ValueError("Empty note name")
    # Strip mode suffixes
    import re
    cleaned = re.sub(r'(minor|major|min|maj|m)$', '', name, flags=re.IGNORECASE)
    # Strip octave digits
    cleaned = re.sub(r'\d+$', '', cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("Empty note name after cleaning: {}".format(name))
    name_upper = cleaned[0].upper() + cleaned[1:]
    if "b" in name_upper and name_upper in FLAT_TO_SHARP:
        name_upper = FLAT_TO_SHARP[name_upper]
    if name_upper not in NOTE_NAMES:
        raise ValueError("Unknown note name: {}".format(name))
    return NOTE_NAMES.index(name_upper)


def _weighted_choice(distribution: dict, rng: random.Random) -> str:
    """Pick a key from a {key: probability} dict using weighted random selection.

    Falls back to uniform random if probabilities don't sum properly.
    """
    if not distribution:
        return "0"
    keys = list(distribution.keys())
    weights = [float(distribution[k]) for k in keys]
    total = sum(weights)
    if total <= 0:
        return rng.choice(keys)

    r = rng.random() * total
    cumulative = 0.0
    for key, weight in zip(keys, weights):
        cumulative += weight
        if r <= cumulative:
            return key
    return keys[-1]  # rounding safety


def _clamp_midi(pitch: int) -> int:
    """Clamp a MIDI pitch to the valid 0-127 range."""
    return max(0, min(127, pitch))


def _quantize_duration(raw: float) -> float:
    """Snap a raw duration to the closest canonical bucket value."""
    return min(DURATION_BUCKETS, key=lambda b: abs(b - raw))


def _velocity_from_bucket(bucket: str, rng: random.Random) -> int:
    """Convert a velocity bucket name to a concrete MIDI velocity with jitter."""
    centre = VELOCITY_CENTRES.get(bucket, 80)
    jitter = rng.randint(-8, 8)
    return max(1, min(127, centre + jitter))


# ---------------------------------------------------------------------------
# Fallback generators (used when models aren't available)
# ---------------------------------------------------------------------------

def _fallback_melodic(key: str, bpm: int, bars: int, category: str, rng: random.Random) -> List[dict]:
    """Simple hardcoded generator used as fallback when no Markov model is available."""
    key_pc = _note_name_to_pitch_class(key)

    # Choose octave based on category
    octave_map = {
        "bass": 2, "synth": 4, "keys": 4,
        "melody": 5, "chords": 4, "pads": 4,
    }
    octave = octave_map.get(category, 4)
    base_midi = (octave + 1) * 12 + key_pc

    # Minor pentatonic intervals as a safe default
    scale = [0, 3, 5, 7, 10]
    beats_per_bar = 4
    total_beats = bars * beats_per_bar
    notes = []
    current_time = 0.0
    current_idx = 0

    while current_time < total_beats:
        duration = rng.choice([0.5, 0.5, 1.0, 1.0, 0.25])
        if current_time + duration > total_beats:
            duration = total_beats - current_time
        if duration <= 0:
            break

        step = rng.choice([-1, 0, 1, 1, 2, -2])
        current_idx = max(0, min(len(scale) - 1, current_idx + step))
        pitch = _clamp_midi(base_midi + scale[current_idx])

        # Occasional rest
        if rng.random() < 0.1:
            current_time += duration
            continue

        notes.append({
            "pitch": pitch,
            "start_time": round(current_time, 4),
            "duration": round(duration * 0.9, 4),
            "velocity": rng.randint(70, 110),
            "mute": False,
        })
        current_time += duration

    return notes


def _fallback_drums(bpm: int, bars: int, rng: random.Random) -> List[dict]:
    """Simple four-on-the-floor drum fallback."""
    notes = []
    beats_per_bar = 4
    for bar in range(bars):
        bar_offset = bar * beats_per_bar
        for beat in range(beats_per_bar):
            t = bar_offset + beat
            # Kick on every beat
            notes.append({
                "pitch": GM_DRUMS["kick"],
                "start_time": round(float(t), 4),
                "duration": 0.25,
                "velocity": 100 if beat % 2 == 0 else 85,
                "mute": False,
            })
            # Snare on 2 and 4
            if beat in (1, 3):
                notes.append({
                    "pitch": GM_DRUMS["snare"],
                    "start_time": round(float(t), 4),
                    "duration": 0.25,
                    "velocity": 100,
                    "mute": False,
                })
            # Closed hi-hat on every 8th
            for eighth in range(2):
                notes.append({
                    "pitch": GM_DRUMS["closed_hh"],
                    "start_time": round(t + eighth * 0.5, 4),
                    "duration": 0.25,
                    "velocity": rng.randint(60, 90),
                    "mute": False,
                })
    return notes


# ---------------------------------------------------------------------------
# Markov generation — melodic categories
# ---------------------------------------------------------------------------

def _generate_melodic_markov(
    model: dict,
    key: str,
    bpm: int,
    bars: int,
    category: str,
    rng: random.Random,
) -> List[dict]:
    """Generate a melodic pattern using Markov chain transitions.

    Parameters
    ----------
    model : dict
        The category's model from markov_models.json.
    key : str
        Root note name (e.g. "C", "F#", "Bb").
    bpm : int
        Tempo in BPM (affects nothing in current implementation but passed
        through for future tempo-aware generation).
    bars : int
        Number of bars to generate.
    category : str
        Category name, used to select octave range.
    rng : random.Random
        Seeded RNG for reproducibility.
    """
    key_pc = _note_name_to_pitch_class(key)

    # Choose octave range by category
    octave_map = {
        "bass": 2, "synth": 4, "keys": 4,
        "melody": 5, "chords": 4, "pads": 3,
    }
    octave = octave_map.get(category, 4)

    # MIDI pitch range constraints per category
    range_map = {
        "bass": (24, 60),
        "synth": (48, 96),
        "keys": (48, 96),
        "melody": (60, 96),
        "chords": (48, 84),
        "pads": (36, 84),
    }
    pitch_lo, pitch_hi = range_map.get(category, (36, 96))

    interval_trans = model.get("interval_transitions", {})
    rhythm_trans = model.get("rhythm_transitions", {})
    velocity_trans = model.get("velocity_transitions", {})
    rest_prob = model.get("rest_probability", 0.1)
    start_intervals_dist = model.get("start_intervals", {"0": 1.0})

    # Pick starting interval relative to root
    start_interval = int(_weighted_choice(start_intervals_dist, rng))
    base_midi = (octave + 1) * 12 + key_pc
    current_pitch = _clamp_midi(base_midi + start_interval)

    # Ensure starting pitch is in range
    while current_pitch < pitch_lo and current_pitch + 12 <= pitch_hi:
        current_pitch += 12
    while current_pitch > pitch_hi and current_pitch - 12 >= pitch_lo:
        current_pitch -= 12

    # Starting rhythm and velocity state
    current_dur_key = _weighted_choice(
        _first_keys(rhythm_trans), rng
    ) if rhythm_trans else "0.5"
    current_vel_key = _weighted_choice(
        _first_keys(velocity_trans), rng
    ) if velocity_trans else "medium"

    beats_per_bar = 4
    total_beats = bars * beats_per_bar
    notes = []
    current_time = 0.0
    prev_interval_key = "0"

    while current_time < total_beats:
        # Determine duration from Markov chain
        dur_dist = rhythm_trans.get(current_dur_key, {})
        if not dur_dist:
            # Fallback: pick from all available durations
            dur_dist = _uniform_from_keys(rhythm_trans)
        next_dur_key = _weighted_choice(dur_dist, rng) if dur_dist else "0.5"
        duration = float(next_dur_key)
        duration = _quantize_duration(duration)

        # Don't exceed total length
        if current_time + duration > total_beats:
            duration = total_beats - current_time
        if duration <= 0:
            break

        # Rest?
        if rng.random() < rest_prob and current_time > 0:
            current_time += duration
            current_dur_key = next_dur_key
            continue

        # Determine next pitch via interval transition
        int_dist = interval_trans.get(prev_interval_key, {})
        if not int_dist:
            int_dist = _uniform_from_keys(interval_trans)
        next_interval_key = _weighted_choice(int_dist, rng) if int_dist else "0"
        interval = int(float(next_interval_key))

        new_pitch = current_pitch + interval

        # Enforce pitch range with octave folding
        if new_pitch < pitch_lo:
            new_pitch += 12 * (1 + (pitch_lo - new_pitch) // 12)
        if new_pitch > pitch_hi:
            new_pitch -= 12 * (1 + (new_pitch - pitch_hi) // 12)
        new_pitch = _clamp_midi(new_pitch)

        # Determine velocity from Markov chain
        vel_dist = velocity_trans.get(current_vel_key, {})
        if not vel_dist:
            vel_dist = _uniform_from_keys(velocity_trans)
        next_vel_key = _weighted_choice(vel_dist, rng) if vel_dist else "medium"
        velocity = _velocity_from_bucket(next_vel_key, rng)

        # Accent downbeats slightly
        if current_time % beats_per_bar < 0.05:
            velocity = min(127, velocity + 10)

        notes.append({
            "pitch": new_pitch,
            "start_time": round(current_time, 4),
            "duration": round(duration * 0.9, 4),  # slight gap for articulation
            "velocity": velocity,
            "mute": False,
        })

        current_pitch = new_pitch
        prev_interval_key = next_interval_key
        current_dur_key = next_dur_key
        current_vel_key = next_vel_key
        current_time += duration

    return notes


def _first_keys(trans_matrix: dict) -> dict:
    """Build a uniform distribution over all states that appear as rows."""
    if not trans_matrix:
        return {}
    keys = list(trans_matrix.keys())
    prob = 1.0 / len(keys)
    return {k: prob for k in keys}


def _uniform_from_keys(trans_matrix: dict) -> dict:
    """Collect all destination states from a transition matrix into a uniform dist."""
    all_keys = set()
    for row in trans_matrix.values():
        if isinstance(row, dict):
            all_keys.update(row.keys())
    if not all_keys:
        return {}
    prob = 1.0 / len(all_keys)
    return {k: prob for k in all_keys}


# ---------------------------------------------------------------------------
# Markov generation — drums
# ---------------------------------------------------------------------------

def _generate_drum_markov(
    model: dict,
    bpm: int,
    bars: int,
    rng: random.Random,
) -> List[dict]:
    """Generate a drum pattern using per-instrument Markov step transitions.

    Parameters
    ----------
    model : dict
        The drums model from markov_models.json (has ``instruments`` key).
    bpm : int
        Tempo (reserved for future use).
    bars : int
        Number of bars to generate.
    rng : random.Random
        Seeded RNG.
    """
    instruments = model.get("instruments", {})
    if not instruments:
        return _fallback_drums(bpm, bars, rng)

    steps_per_bar = 16
    total_steps = steps_per_bar * bars
    step_duration = 0.25  # beats per 16th note step in 4/4

    notes = []

    for inst_name, inst_model in instruments.items():
        midi_pitch = GM_DRUMS.get(inst_name)
        if midi_pitch is None:
            continue

        step_trans = inst_model.get("step_transitions", {})
        density = inst_model.get("density", 0.25)
        vel_trans = inst_model.get("velocity_transitions", {})

        if not step_trans:
            # No transition data — generate using density as hit probability
            current_vel_bucket = "medium"
            for step in range(total_steps):
                if rng.random() < density:
                    vel = _velocity_from_bucket(current_vel_bucket, rng)
                    notes.append({
                        "pitch": midi_pitch,
                        "start_time": round(step * step_duration, 4),
                        "duration": round(step_duration, 4),
                        "velocity": vel,
                        "mute": False,
                    })
            continue

        # Use Markov chain to decide hit/rest at each step
        # Start with a state based on density
        current_state = "hit" if rng.random() < density else "rest"
        current_vel_bucket = "medium"

        for step in range(total_steps):
            if current_state == "hit":
                # Determine velocity
                vd = vel_trans.get(current_vel_bucket, {})
                if vd:
                    current_vel_bucket = _weighted_choice(vd, rng)
                vel = _velocity_from_bucket(current_vel_bucket, rng)

                notes.append({
                    "pitch": midi_pitch,
                    "start_time": round(step * step_duration, 4),
                    "duration": round(step_duration, 4),
                    "velocity": vel,
                    "mute": False,
                })

            # Transition to next state
            dist = step_trans.get(current_state, {})
            if dist:
                current_state = _weighted_choice(dist, rng)
            else:
                # No transition data for this state — use density
                current_state = "hit" if rng.random() < density else "rest"

    # Sort by time, then pitch
    notes.sort(key=lambda n: (n["start_time"], n["pitch"]))
    return notes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_from_markov(
    category: str,
    key: str = "C",
    bpm: int = 120,
    bars: int = 4,
    seed: Optional[int] = None,
) -> List[dict]:
    """Generate a MIDI pattern using trained Markov chain models.

    Parameters
    ----------
    category : str
        Pattern category: bass, drums, synth, chords, keys, pads, or melody.
    key : str
        Root note name (e.g. "C", "F#", "Bb"). Ignored for drums.
    bpm : int
        Tempo in BPM. Default 120.
    bars : int
        Number of bars to generate (1-16). Default 4.
    seed : int, optional
        Random seed for reproducibility. If None, uses system randomness.

    Returns
    -------
    list[dict]
        List of note dicts with keys: pitch, start_time, duration, velocity, mute.
    """
    bars = max(1, min(16, bars))
    rng = random.Random(seed)

    models = _load_models()

    # Try to use trained model
    if models is not None:
        cat_model = models.get("categories", {}).get(category)
        if cat_model is not None:
            if category == "drums":
                return _generate_drum_markov(cat_model, bpm, bars, rng)
            else:
                return _generate_melodic_markov(
                    cat_model, key, bpm, bars, category, rng
                )

    # Fallback to hardcoded patterns
    logger.info(
        "No Markov model for category '%s', using fallback generator", category
    )
    if category == "drums":
        return _fallback_drums(bpm, bars, rng)
    else:
        return _fallback_melodic(key, bpm, bars, category, rng)


def find_similar_pattern(
    category: str,
    key: Optional[str] = None,
    bpm: Optional[int] = None,
) -> Optional[dict]:
    """Find the closest matching pattern from the index.

    Searches midi_patterns/index.json for a pattern matching the given
    category and, optionally, key and BPM.

    Parameters
    ----------
    category : str
        Pattern category to search within.
    key : str, optional
        Preferred key. Patterns in this key are scored higher.
    bpm : int, optional
        Preferred BPM. Closer tempos score higher.

    Returns
    -------
    dict or None
        The best-matching pattern dict, or None if nothing found.
    """
    index = _load_index()
    if index is None:
        return None

    # Gather patterns in the requested category
    patterns = _get_patterns_for_category(index, category)
    if not patterns:
        return None

    key_pc = None
    if key is not None:
        try:
            key_pc = _note_name_to_pitch_class(key)
        except ValueError:
            key_pc = None

    best_pattern = None
    best_score = -1

    for pattern in patterns:
        score = 0.0

        # Key matching
        if key_pc is not None:
            pattern_key = pattern.get("key", pattern.get("root_note"))
            if pattern_key is not None:
                try:
                    pattern_pc = _note_name_to_pitch_class(str(pattern_key))
                    if pattern_pc == key_pc:
                        score += 10.0
                    else:
                        # Favour closely related keys (perfect 5th = 7 semitones)
                        diff = abs(pattern_pc - key_pc)
                        diff = min(diff, 12 - diff)
                        if diff <= 2:
                            score += 5.0
                        elif diff == 7 or diff == 5:
                            score += 3.0
                except ValueError:
                    pass

        # BPM matching
        if bpm is not None:
            pattern_bpm = pattern.get("bpm", pattern.get("tempo"))
            if pattern_bpm is not None:
                try:
                    bpm_diff = abs(float(pattern_bpm) - bpm)
                    if bpm_diff < 5:
                        score += 5.0
                    elif bpm_diff < 20:
                        score += 3.0
                    elif bpm_diff < 40:
                        score += 1.0
                except (ValueError, TypeError):
                    pass

        # Prefer patterns with more notes (richer data)
        note_count = len(pattern.get("notes", []))
        score += min(note_count / 20.0, 2.0)

        if score > best_score:
            best_score = score
            best_pattern = pattern

    return best_pattern


def transpose_pattern(
    pattern_notes: List[dict],
    from_key: str,
    to_key: str,
) -> List[dict]:
    """Transpose a list of note dicts from one key to another.

    Each note's pitch is shifted by the semitone difference between the two
    keys. Notes that would fall outside MIDI range (0-127) are octave-folded.

    Parameters
    ----------
    pattern_notes : list[dict]
        List of note dicts (each must have a ``pitch`` key).
    from_key : str
        Original key (e.g. "C", "F#", "Bb").
    to_key : str
        Target key (e.g. "D", "Ab", "E").

    Returns
    -------
    list[dict]
        New list of note dicts with transposed pitches. Original list is not
        modified.
    """
    from_pc = _note_name_to_pitch_class(from_key)
    to_pc = _note_name_to_pitch_class(to_key)
    semitone_shift = to_pc - from_pc

    result = []
    for note in pattern_notes:
        new_note = dict(note)  # shallow copy
        pitch = note.get("pitch", 60)
        new_pitch = pitch + semitone_shift

        # Octave-fold if out of MIDI range
        while new_pitch < 0:
            new_pitch += 12
        while new_pitch > 127:
            new_pitch -= 12

        new_note["pitch"] = new_pitch
        result.append(new_note)

    return result


# ---------------------------------------------------------------------------
# Internal helpers for index access
# ---------------------------------------------------------------------------

def _get_patterns_for_category(index: dict, category: str) -> list:
    """Extract patterns for a given category from the index.

    Handles multiple index structures:
    - {"categories": {"bass": {"count": N, "patterns": [...]}, ...}}
    - {"patterns": [{"category": "bass", ...}, ...]}
    - {"bass": [...], "drums": [...], ...}
    """
    if "categories" in index and isinstance(index["categories"], dict):
        cat_data = index["categories"].get(category, {})
        if isinstance(cat_data, dict) and "patterns" in cat_data:
            return cat_data["patterns"]

    if "patterns" in index and isinstance(index["patterns"], list):
        return [p for p in index["patterns"] if p.get("category") == category]

    if category in index and isinstance(index[category], list):
        return index[category]

    return []
