"""Pattern generation using real MIDI pattern library.

Search-select-adapt-vary pipeline over 1105 real MIDI patterns from
midi_patterns/index.json.  Template-based drum generation with humanization.

All functions are pure computation — no Ableton connection required.
"""
import json
import logging
import random
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("AbletonMCPServer")

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_INDEX_PATH = _PROJECT_ROOT / "midi_patterns" / "index.json"

# ---------------------------------------------------------------------------
# Cached data — loaded once on first access
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

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


def _clamp_midi(pitch: int) -> int:
    """Clamp a MIDI pitch to the valid 0-127 range."""
    return max(0, min(127, pitch))


# ---------------------------------------------------------------------------
# Fallback generators (used when pattern library has no matches)
# ---------------------------------------------------------------------------

def _fallback_melodic(key: str, bpm: int, bars: int, category: str, rng: random.Random) -> List[dict]:
    """Simple hardcoded generator used as fallback when no patterns are found."""
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
# PatternEngine — Search-Select-Adapt-Vary pipeline using real MIDI patterns
# ---------------------------------------------------------------------------

class PatternEngine:
    """Generate music by searching, selecting, adapting, and varying real MIDI patterns."""

    def __init__(self):
        self._patterns_by_category: Dict[str, List[dict]] = {}
        self._inferred_keys: Dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        index = _load_index()
        if index is None:
            logger.warning("PatternEngine: index.json not found")
            return

        categories = index.get("categories", {})
        for cat_name, cat_data in categories.items():
            if not isinstance(cat_data, dict):
                continue
            raw_patterns = cat_data.get("patterns", [])
            # Filter out corrupt patterns
            sane = [p for p in raw_patterns if self._is_sane(p)]
            # Infer keys for patterns without key metadata
            for p in sane:
                if not p.get("key"):
                    inferred = self._infer_key(p)
                    if inferred:
                        self._inferred_keys[p.get("id", "")] = inferred
            self._patterns_by_category[cat_name] = sane
            logger.info("PatternEngine: %s = %d patterns (%d with key, %d inferred)",
                        cat_name, len(sane),
                        sum(1 for p in sane if p.get("key")),
                        sum(1 for p in sane if p.get("id", "") in self._inferred_keys))

    def _is_sane(self, pattern: dict) -> bool:
        dur = pattern.get("duration_beats", 0)
        notes = pattern.get("notes", [])
        if dur > 500 or len(notes) < 1:
            return False
        if notes and max(n.get("start", 0) for n in notes) > 500:
            return False
        return True

    def _infer_key(self, pattern: dict) -> Optional[str]:
        notes = pattern.get("notes", [])
        if len(notes) < 3:
            return None

        pc_counts = [0] * 12
        for n in notes:
            pc_counts[n["pitch"] % 12] += 1

        major_intervals = [0, 2, 4, 5, 7, 9, 11]
        minor_intervals = [0, 2, 3, 5, 7, 8, 10]

        best_key = None
        best_score = -1

        for root in range(12):
            for intervals, suffix in [(major_intervals, ""), (minor_intervals, "m")]:
                score = sum(pc_counts[(root + iv) % 12] for iv in intervals)
                if score > best_score:
                    best_score = score
                    best_key = NOTE_NAMES[root] + suffix

        return best_key

    def search_patterns(
        self,
        category: str,
        key: Optional[str] = None,
        bpm: Optional[int] = None,
        min_notes: int = 4,
    ) -> List[dict]:
        """Search for patterns matching the given criteria. Returns top 10 scored matches."""
        self._ensure_loaded()
        patterns = self._patterns_by_category.get(category, [])
        candidates = [p for p in patterns if len(p.get("notes", [])) >= min_notes]

        if not candidates:
            return []

        if key is None and bpm is None:
            return random.Random().sample(candidates, min(10, len(candidates)))

        target_pc = None
        target_is_minor = False
        if key is not None:
            try:
                target_pc = _note_name_to_pitch_class(key)
                target_is_minor = key.strip().endswith("m") or "min" in key.lower()
            except ValueError:
                target_pc = None

        scored = []
        for p in candidates:
            score = 0.0

            # Key scoring (max 10)
            if target_pc is not None:
                p_key = p.get("key") or self._inferred_keys.get(p.get("id", ""))
                if p_key:
                    try:
                        p_pc = _note_name_to_pitch_class(p_key)
                        p_is_minor = p_key.endswith("m")
                        if p_pc == target_pc and p_is_minor == target_is_minor:
                            score += 10.0
                        elif p_pc == target_pc:
                            score += 7.0
                        else:
                            rel_diff = (p_pc - target_pc) % 12
                            if rel_diff == 3 and target_is_minor and not p_is_minor:
                                score += 9.0
                            elif rel_diff == 9 and not target_is_minor and p_is_minor:
                                score += 9.0
                            else:
                                diff = min(rel_diff, 12 - rel_diff)
                                if diff <= 1:
                                    score += 6.0
                                elif diff in (5, 7):
                                    score += 5.0
                                elif diff == 2:
                                    score += 3.0
                                else:
                                    score += 1.0
                    except ValueError:
                        pass
                else:
                    score += 2.0

            # BPM scoring (max 5)
            if bpm is not None:
                p_bpm = p.get("bpm")
                if p_bpm is not None:
                    try:
                        diff = abs(float(p_bpm) - bpm)
                        if diff < 3: score += 5.0
                        elif diff < 10: score += 4.0
                        elif diff < 20: score += 3.0
                        elif diff < 40: score += 1.0
                    except (ValueError, TypeError):
                        pass

            # Note richness (max 2)
            score += min(len(p.get("notes", [])) / 20.0, 2.0)

            # Random perturbation so same inputs don't always return same top 10
            score += random.random() * 2.0

            scored.append((score, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:10]]

    def pick_pattern(self, matches: List[dict], seed: Optional[int] = None) -> dict:
        """Pick one pattern from matches with weighted randomness (better scores more likely)."""
        if not matches:
            raise ValueError("No patterns to pick from")
        if len(matches) == 1:
            return matches[0]

        rng = random.Random(seed)
        n = len(matches)
        weights = [max(1.0, 5.0 - i * 0.4) for i in range(n)]
        total = sum(weights)
        r = rng.random() * total
        cumulative = 0.0
        for i, w in enumerate(weights):
            cumulative += w
            if r <= cumulative:
                return matches[i]
        return matches[-1]

    def adapt_pattern(
        self,
        pattern: dict,
        target_key: str,
        target_bars: int,
        target_bpm: Optional[int] = None,
    ) -> List[dict]:
        """Adapt a real pattern: transpose to key, loop/truncate to bars, convert to Ableton format."""
        notes = pattern.get("notes", [])
        if not notes:
            return []

        # Normalize timing (shift so first note starts at beat 0)
        min_start = min(n.get("start", 0) for n in notes)
        normalized = []
        for n in notes:
            normalized.append({
                "pitch": n["pitch"],
                "start": n.get("start", 0) - min_start,
                "duration": n["duration"],
                "velocity": n["velocity"],
            })

        # Determine source pattern length in bars
        pattern_duration = pattern.get("duration_beats", 0)
        if pattern_duration <= 0 or pattern_duration > 500:
            last_end = max(n["start"] + n["duration"] for n in normalized)
            pattern_duration = last_end
        else:
            pattern_duration = pattern_duration - min_start

        pattern_bars = max(1, int((pattern_duration + 3.99) // 4))
        pattern_beats = pattern_bars * 4

        # Transpose to target key
        source_key = pattern.get("key") or self._inferred_keys.get(pattern.get("id", ""))
        if source_key and target_key:
            try:
                from_pc = _note_name_to_pitch_class(source_key)
                to_pc = _note_name_to_pitch_class(target_key)
                shift = to_pc - from_pc
                for n in normalized:
                    new_pitch = n["pitch"] + shift
                    while new_pitch < 0:
                        new_pitch += 12
                    while new_pitch > 127:
                        new_pitch -= 12
                    n["pitch"] = new_pitch
            except ValueError:
                pass

        # Loop or truncate to target_bars
        target_beats = target_bars * 4
        result = []

        if pattern_beats >= target_beats:
            for n in normalized:
                if n["start"] < target_beats:
                    note = dict(n)
                    if note["start"] + note["duration"] > target_beats:
                        note["duration"] = target_beats - note["start"]
                    result.append(note)
        else:
            repetitions = (target_beats + pattern_beats - 1) // pattern_beats
            for rep in range(repetitions):
                offset = rep * pattern_beats
                for n in normalized:
                    new_start = n["start"] + offset
                    if new_start >= target_beats:
                        continue
                    note = dict(n)
                    note["start"] = new_start
                    if note["start"] + note["duration"] > target_beats:
                        note["duration"] = target_beats - note["start"]
                    result.append(note)

        # Convert to Ableton format
        ableton_notes = []
        for n in result:
            ableton_notes.append({
                "pitch": n["pitch"],
                "start_time": round(n["start"], 4),
                "duration": round(max(n["duration"], 0.01), 4),
                "velocity": max(1, min(127, n["velocity"])),
                "mute": False,
            })

        ableton_notes.sort(key=lambda n: (n["start_time"], n["pitch"]))
        return ableton_notes

    def vary_pattern(
        self,
        notes: List[dict],
        amount: float = 0.3,
        seed: Optional[int] = None,
    ) -> List[dict]:
        """Apply subtle humanization: velocity variation, micro-timing, occasional omission."""
        if not notes or amount <= 0:
            return list(notes)

        rng = random.Random(seed)
        amount = max(0.0, min(1.0, amount))
        result = []

        for note in notes:
            if rng.random() < amount * 0.1:
                continue

            new_note = dict(note)

            vel_range = int(amount * 20)
            if vel_range > 0:
                new_note["velocity"] = max(1, min(127,
                    note["velocity"] + rng.randint(-vel_range, vel_range)))

            timing_range = amount * 0.05
            if timing_range > 0:
                new_note["start_time"] = round(max(0.0,
                    note["start_time"] + rng.uniform(-timing_range, timing_range)), 4)

            dur_factor = 1.0 + rng.uniform(-amount * 0.1, amount * 0.1)
            new_note["duration"] = round(max(0.01, note["duration"] * dur_factor), 4)

            result.append(new_note)

        result.sort(key=lambda n: (n["start_time"], n["pitch"]))
        return result

    def generate(
        self,
        category: str,
        key: str = "C",
        bars: int = 4,
        bpm: Optional[int] = None,
        variation: float = 0.3,
        seed: Optional[int] = None,
    ) -> List[dict]:
        """Generate by searching real patterns, picking one, adapting it, and varying it."""
        bars = max(1, min(16, bars))

        matches = self.search_patterns(category, key=key, bpm=bpm)
        if not matches:
            matches = self.search_patterns(category, bpm=bpm, min_notes=2)
        if not matches:
            logger.warning("PatternEngine: no patterns found for %s, using fallback", category)
            rng = random.Random(seed)
            return _fallback_melodic(key, bpm or 120, bars, category, rng)

        pattern = self.pick_pattern(matches, seed=seed)
        notes = self.adapt_pattern(pattern, target_key=key, target_bars=bars, target_bpm=bpm)

        if variation > 0:
            vary_seed = (seed * 31 + 7) if seed is not None else None
            notes = self.vary_pattern(notes, amount=variation, seed=vary_seed)

        return notes


# ---------------------------------------------------------------------------
# Module-level singleton and public API
# ---------------------------------------------------------------------------

_engine: Optional[PatternEngine] = None


def _get_engine() -> PatternEngine:
    global _engine
    if _engine is None:
        _engine = PatternEngine()
    return _engine


def generate_from_patterns(
    category: str,
    key: str = "C",
    bars: int = 4,
    bpm: Optional[int] = None,
    variation: float = 0.3,
    seed: Optional[int] = None,
) -> List[dict]:
    """Generate a MIDI pattern using the search-select-adapt-vary pipeline.

    Uses real MIDI patterns from the library instead of generating from scratch.
    """
    return _get_engine().generate(category, key, bars, bpm, variation, seed)


# ---------------------------------------------------------------------------
# Drum pattern templates with multiple variations per style
# ---------------------------------------------------------------------------

def _get_drum_pattern(style, steps_per_bar, variation=None):
    """Return drum patterns as {midi_pitch: [(step, velocity), ...]}.

    All patterns assume a 16-step grid per bar (for 4/4 time).
    If steps_per_bar differs, patterns are scaled/truncated.

    Each style has multiple variations. Pass variation=0,1,2,... to select one,
    or leave as None for a random pick.
    """
    kick = GM_DRUMS["kick"]
    snare = GM_DRUMS["snare"]
    closed_hh = GM_DRUMS["closed_hh"]
    open_hh = GM_DRUMS["open_hh"]
    clap = GM_DRUMS["clap"]
    rim = GM_DRUMS["rim"]
    tom_low = GM_DRUMS["tom_low"]
    tom_mid = GM_DRUMS["tom_mid"]
    tom_hi = GM_DRUMS["tom_hi"]
    crash = GM_DRUMS["crash"]
    ride = GM_DRUMS["ride"]

    variations = None

    if style == "house":
        variations = [
            # Classic: four-on-the-floor + clap + offbeat hh + open hh accents
            {
                kick: [(0, 110), (4, 110), (8, 110), (12, 110)],
                clap: [(4, 100), (12, 100)],
                closed_hh: [(i, 80) for i in range(1, 16, 2)],
                open_hh: [(2, 85), (6, 85), (10, 85), (14, 85)],
            },
            # Offbeat kick: ghost kick on 7 + hh every 2 steps
            {
                kick: [(0, 110), (4, 110), (7, 70), (8, 110), (12, 110)],
                clap: [(4, 100), (12, 100)],
                closed_hh: [(i, 80 if i % 4 == 0 else 65) for i in range(0, 16, 2)],
                open_hh: [(6, 80), (14, 80)],
            },
            # Shuffled: ride on beats + hh with swing feel
            {
                kick: [(0, 110), (4, 110), (8, 110), (12, 110)],
                clap: [(4, 100), (12, 100)],
                closed_hh: [(0, 75), (3, 60), (4, 75), (7, 60), (8, 75), (11, 60), (12, 75), (15, 60)],
                ride: [(0, 90), (4, 90), (8, 90), (12, 90)],
            },
            # Minimal: rim instead of clap + hh every step with velocity variation
            {
                kick: [(0, 110), (4, 110), (8, 110), (12, 110)],
                rim: [(4, 95), (12, 95)],
                closed_hh: [(i, 85 if i % 4 == 0 else 55 + (i % 3) * 10) for i in range(16)],
                open_hh: [(6, 70), (14, 70)],
            },
        ]
    elif style == "techno":
        variations = [
            # Driving: kick every beat + 16th hh + clap
            {
                kick: [(0, 120), (4, 115), (8, 120), (12, 115)],
                closed_hh: [(i, 85 if i % 2 == 0 else 65) for i in range(16)],
                clap: [(4, 95), (12, 95)],
            },
            # Industrial: rim on offbeats + sparse hh + crash on 0
            {
                kick: [(0, 120), (4, 115), (8, 120), (12, 115)],
                rim: [(2, 75), (6, 70), (10, 75), (14, 70)],
                closed_hh: [(0, 80), (4, 80), (8, 80), (12, 80)],
                crash: [(0, 90)],
            },
            # Hypnotic: ride pattern + subtle toms + clap
            {
                kick: [(0, 120), (4, 115), (8, 120), (12, 115)],
                ride: [(i, 75 if i % 4 == 0 else 55) for i in range(0, 16, 2)],
                tom_mid: [(6, 60), (14, 55)],
                tom_low: [(10, 55)],
                clap: [(4, 95), (12, 95)],
            },
            # Broken: syncopated kick + triplet feel hh + open hh accents
            {
                kick: [(0, 120), (3, 100), (8, 115), (11, 95)],
                clap: [(4, 100), (12, 100)],
                closed_hh: [(0, 80), (3, 65), (5, 70), (8, 80), (11, 65), (13, 70)],
                open_hh: [(2, 75), (7, 70), (10, 75), (15, 70)],
            },
        ]
    elif style == "hiphop":
        variations = [
            # Classic: syncopated kick + snare + 16th hh
            {
                kick: [(0, 110), (3, 80), (7, 90), (10, 85)],
                snare: [(4, 100), (12, 100)],
                closed_hh: [(i, 75 if i % 2 == 0 else 55) for i in range(16)],
                open_hh: [(6, 70), (14, 70)],
            },
            # Boom bap: sparse kick + snare + hh with open accents + ride bell
            {
                kick: [(0, 110), (8, 100)],
                snare: [(4, 105), (12, 105)],
                closed_hh: [(i, 70 if i % 2 == 0 else 50) for i in range(16)],
                open_hh: [(3, 75), (11, 75)],
                ride: [(0, 65), (4, 65), (8, 65), (12, 65)],
            },
            # Trap-influenced: syncopated kick + rapid hh + open hh
            {
                kick: [(0, 115), (7, 95), (10, 90)],
                snare: [(4, 105), (12, 105)],
                closed_hh: [(i, 70 + (i % 3) * 8) for i in range(16)],
                open_hh: [(3, 65), (7, 65), (11, 65), (15, 65)],
            },
        ]
    elif style == "trap":
        variations = [
            # Classic trap
            {
                kick: [(0, 120), (7, 100), (11, 90)],
                snare: [(4, 110), (12, 110)],
                closed_hh: [(i, 70 + (i % 3) * 10) for i in range(16)],
                open_hh: [(3, 60), (7, 60), (11, 60), (15, 60)],
                clap: [(4, 100), (12, 100)],
            },
            # 808: rolling hh with 32nd feel in places + open hh
            {
                kick: [(0, 120), (6, 100), (10, 95)],
                snare: [(4, 110), (12, 110)],
                closed_hh: [(0, 75), (1, 55), (2, 70), (3, 55), (4, 75), (5, 55),
                            (6, 70), (7, 55), (8, 75), (9, 60), (10, 75), (11, 60),
                            (12, 80), (13, 65), (14, 80), (15, 65)],
                open_hh: [(7, 65), (15, 65)],
            },
            # Minimal: sparse kick + clap + sparse hh + rim accents
            {
                kick: [(0, 120), (8, 105)],
                clap: [(4, 105), (12, 105)],
                closed_hh: [(0, 70), (2, 60), (4, 70), (8, 70), (10, 60), (12, 70)],
                rim: [(6, 65), (14, 65)],
            },
        ]
    elif style == "rock":
        variations = [
            # Classic rock
            {
                kick: [(0, 110), (6, 90), (8, 100)],
                snare: [(4, 110), (12, 110)],
                closed_hh: [(i, 90 if i % 4 == 0 else 70) for i in range(16)],
                crash: [(0, 90)],
            },
            # Driving rock: straight 8ths + heavier kick
            {
                kick: [(0, 115), (4, 90), (8, 110), (10, 85)],
                snare: [(4, 115), (12, 115)],
                closed_hh: [(i, 85 if i % 2 == 0 else 65) for i in range(0, 16, 2)],
                crash: [(0, 95)],
            },
            # Half-time rock
            {
                kick: [(0, 110), (10, 90)],
                snare: [(8, 110)],
                closed_hh: [(i, 80 if i % 4 == 0 else 60) for i in range(0, 16, 2)],
                open_hh: [(14, 75)],
                crash: [(0, 85)],
            },
        ]
    elif style == "dnb":
        variations = [
            # Classic DnB
            {
                kick: [(0, 120), (10, 100)],
                snare: [(4, 110), (13, 105)],
                closed_hh: [(i, 80) for i in range(0, 16, 2)],
                ride: [(i, 70) for i in range(1, 16, 4)],
            },
            # Amen-style: busier snare pattern
            {
                kick: [(0, 120), (8, 100), (14, 85)],
                snare: [(4, 110), (10, 90), (13, 105)],
                closed_hh: [(i, 75 if i % 2 == 0 else 55) for i in range(16)],
                open_hh: [(6, 70)],
            },
            # Roller: driving kick + rides
            {
                kick: [(0, 115), (4, 100), (10, 110)],
                snare: [(4, 105), (13, 100)],
                ride: [(i, 80 if i % 2 == 0 else 60) for i in range(16)],
                crash: [(0, 80)],
            },
        ]
    elif style == "reggaeton":
        variations = [
            # Classic dembow
            {
                kick: [(0, 110), (4, 90), (8, 110), (12, 90)],
                snare: [(3, 100), (7, 100), (11, 100), (15, 100)],
                closed_hh: [(i, 75) for i in range(0, 16, 2)],
                rim: [(3, 85), (7, 85), (11, 85), (15, 85)],
            },
            # Dembow with open hh accents
            {
                kick: [(0, 110), (4, 90), (8, 110), (12, 90)],
                snare: [(3, 100), (7, 100), (11, 100), (15, 100)],
                closed_hh: [(i, 70) for i in range(0, 16, 2)],
                open_hh: [(3, 80), (11, 80)],
            },
        ]
    elif style == "bossa_nova":
        variations = [
            # Classic bossa
            {
                kick: [(0, 90), (6, 80), (10, 85)],
                rim: [(2, 75), (5, 70), (8, 75), (12, 70), (15, 65)],
                closed_hh: [(i, 60) for i in range(0, 16, 2)],
            },
            # Bossa with brush feel
            {
                kick: [(0, 85), (6, 75), (10, 80)],
                rim: [(2, 70), (5, 65), (8, 70), (12, 65), (15, 60)],
                closed_hh: [(i, 55) for i in range(16)],
                ride: [(0, 65), (4, 60), (8, 65), (12, 60)],
            },
        ]
    elif style == "jazz_swing":
        variations = [
            # Classic swing ride pattern
            {
                ride: [
                    (0, 95), (3, 70), (4, 90), (7, 70),
                    (8, 95), (11, 70), (12, 90), (15, 70),
                ],
                kick: [(0, 70), (10, 60)],
                closed_hh: [(4, 65), (12, 65)],
                snare: [(7, 50), (15, 55)],
            },
            # Jazz with brush comping
            {
                ride: [
                    (0, 90), (3, 65), (4, 85), (7, 65),
                    (8, 90), (11, 65), (12, 85), (15, 65),
                ],
                kick: [(0, 65), (6, 55), (10, 60)],
                snare: [(3, 45), (7, 50), (11, 45), (15, 50)],
                closed_hh: [(4, 60), (12, 60)],
            },
        ]
    elif style == "funk":
        variations = [
            # Classic funk
            {
                kick: [(0, 110), (3, 80), (6, 90), (10, 100), (13, 80)],
                snare: [(4, 110), (12, 110)],
                closed_hh: [(i, 85 if i % 2 == 0 else 65) for i in range(16)],
                open_hh: [(7, 80), (15, 80)],
                clap: [(4, 70)],
            },
            # Syncopated funk: busier kick + ghost snares
            {
                kick: [(0, 110), (3, 75), (6, 95), (8, 85), (10, 100), (14, 80)],
                snare: [(4, 110), (12, 110), (7, 50), (15, 50)],
                closed_hh: [(i, 80 if i % 2 == 0 else 60) for i in range(16)],
                open_hh: [(3, 75), (11, 75)],
            },
            # Funk with ride
            {
                kick: [(0, 105), (5, 80), (8, 100), (13, 75)],
                snare: [(4, 110), (12, 110)],
                ride: [(i, 75 if i % 4 == 0 else 55) for i in range(0, 16, 2)],
                closed_hh: [(7, 70), (15, 70)],
                clap: [(4, 65)],
            },
        ]
    elif style == "basic":
        variations = [
            # Classic basic
            {
                kick: [(0, 100), (8, 100)],
                snare: [(4, 100), (12, 100)],
                closed_hh: [(i, 80 if i % 4 == 0 else 60) for i in range(0, 16, 2)],
            },
            # Basic with open hh
            {
                kick: [(0, 100), (8, 100)],
                snare: [(4, 100), (12, 100)],
                closed_hh: [(i, 75 if i % 4 == 0 else 55) for i in range(0, 16, 2)],
                open_hh: [(6, 70), (14, 70)],
            },
        ]
    else:
        return None

    # Pick a variation
    if variation is not None and 0 <= variation < len(variations):
        raw_patterns = variations[variation]
    else:
        raw_patterns = random.choice(variations)

    if steps_per_bar != 16:
        scale_factor = steps_per_bar / 16.0
        scaled = {}
        for pitch, hits in raw_patterns.items():
            scaled[pitch] = [
                (round(step * scale_factor), vel)
                for step, vel in hits
                if round(step * scale_factor) < steps_per_bar
            ]
        return scaled

    return raw_patterns


def generate_humanized_drums(
    style: str,
    bars: int = 4,
    humanize: float = 0.3,
    seed: Optional[int] = None,
) -> List[dict]:
    """Generate drums from templates with velocity humanization and micro-variation."""

    rng = random.Random(seed)
    bars = max(1, min(16, bars))
    humanize = max(0.0, min(1.0, humanize))
    beats_per_bar = 4
    steps_per_bar = 16
    step_duration = 0.25

    raw_patterns = _get_drum_pattern(style, steps_per_bar)
    if raw_patterns is None:
        return _fallback_drums(120, bars, rng)

    notes = []
    for bar in range(bars):
        bar_offset = bar * beats_per_bar
        for pitch, hits in raw_patterns.items():
            for step, base_velocity in hits:
                start = bar_offset + step * step_duration

                vel_range = int(humanize * 35)
                vel = base_velocity + rng.randint(-vel_range, vel_range)
                vel = max(1, min(127, vel))

                timing_range = humanize * 0.08
                time_delta = rng.uniform(-timing_range, timing_range)
                start = max(0.0, start + time_delta)

                # Ghost note injection
                ghost_prob = humanize * 0.15
                if rng.random() < ghost_prob and step > 0:
                    ghost_start = start - step_duration
                    if ghost_start >= bar_offset:
                        notes.append({
                            "pitch": pitch,
                            "start_time": round(ghost_start, 4),
                            "duration": round(step_duration, 4),
                            "velocity": max(1, base_velocity // 3),
                            "mute": False,
                        })

                # Occasional note skip
                if rng.random() < humanize * 0.08:
                    continue

                notes.append({
                    "pitch": pitch,
                    "start_time": round(start, 4),
                    "duration": round(step_duration, 4),
                    "velocity": vel,
                    "mute": False,
                })

    notes.sort(key=lambda n: (n["start_time"], n["pitch"]))
    return notes
